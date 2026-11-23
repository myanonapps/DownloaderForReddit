"""
Add tables and columns used when importing a Reddit data export archive.

Adds the export_import, chat_channel, chat_message and private_message tables, plus permalink columns on post and
comment and the link_reddit_id column on comment.


Copyright (C) 2017, Kyle Hickey


This file is part of the Downloader for Reddit.

Downloader for Reddit is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Downloader for Reddit is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Downloader for Reddit.  If not, see <http://www.gnu.org/licenses/>.
"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = '3e5a9c1d7b42'  # pylint: disable=invalid-name  # names required by alembic
down_revision = '7b1f4c8a9d2e'  # pylint: disable=invalid-name  # names required by alembic
branch_labels = None  # pylint: disable=invalid-name  # names required by alembic
depends_on = None  # pylint: disable=invalid-name  # names required by alembic


def _table_names() -> list[str]:
    """
    Lists the tables in the database being migrated.
    :return: The table names.
    :rtype: list[str]
    """
    return sa.inspect(op.get_bind()).get_table_names()  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy


def _create_table(name: str, *columns: sa.Column) -> None:
    """
    Creates a table unless it exists.  DatabaseHandler runs create_all() before the migrator runs, so the new tables
    are normally there already, empty, by the time this migration runs.
    :param name: The table name.
    :type name: str
    :param columns: The table's columns.
    :type columns: sa.Column
    :return: None
    :rtype: None
    """
    if name not in _table_names():
        op.create_table(name, *columns)  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy


def _create_index(name: str, table: str, columns: list[str]) -> None:
    """
    Creates an index unless it exists.
    :param name: The index name.
    :type name: str
    :param table: The table to index.
    :type table: str
    :param columns: The indexed columns.
    :type columns: list[str]
    :return: None
    :rtype: None
    """
    existing = {index['name'] for index in sa.inspect(op.get_bind()).get_indexes(table)}  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy
    if name not in existing:
        op.create_index(name, table, columns)  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy


def _add_column(table: str, column: sa.Column) -> None:
    """
    Adds a column to an existing table unless it is there already.
    :param table: The table name.
    :type table: str
    :param column: The column to add.
    :type column: sa.Column
    :return: None
    :rtype: None
    """
    existing = {info['name'] for info in sa.inspect(op.get_bind()).get_columns(table)}  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy
    if column.name not in existing:
        op.add_column(table, column)  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy


def upgrade() -> None:
    """
    Creates the export import tables and adds the new post and comment columns.  Every step is skipped when its
    table, column or index already exists.
    :return: None
    :rtype: None
    """
    _create_table(
        'export_import',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('file_name', sa.String(), nullable=True),
        sa.Column('file_sha256', sa.String(), nullable=True),
        sa.Column('account_name', sa.String(collation='NOCASE'), nullable=True),
        sa.Column('import_date', sa.DateTime(), nullable=True),
        sa.Column('post_count', sa.Integer(), nullable=True),
        sa.Column('comment_count', sa.Integer(), nullable=True),
        sa.Column('chat_message_count', sa.Integer(), nullable=True),
        sa.Column('private_message_count', sa.Integer(), nullable=True),
        sa.Column('download_session_id', sa.Integer(), sa.ForeignKey('download_session.id'), nullable=True),
    )
    _create_index('ix_export_import_file_sha256', 'export_import', ['file_sha256'])

    _create_table(
        'chat_channel',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('channel_url', sa.String(), nullable=True, unique=True),
        sa.Column('channel_name', sa.String(collation='NOCASE'), nullable=True),
        sa.Column('subreddit_name', sa.String(collation='NOCASE'), nullable=True),
        sa.Column('conversation_type', sa.String(), nullable=True),
        sa.Column('export_import_id', sa.Integer(), sa.ForeignKey('export_import.id'), nullable=True),
    )

    _create_table(
        'chat_message',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('message_id', sa.String(), nullable=True, unique=True),
        sa.Column('author_name', sa.String(collation='NOCASE'), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('date_posted', sa.DateTime(), nullable=True),
        sa.Column('date_updated', sa.DateTime(), nullable=True),
        sa.Column('thread_parent_message_id', sa.String(), nullable=True),
        sa.Column('channel_id', sa.Integer(), sa.ForeignKey('chat_channel.id'), nullable=True),
        sa.Column('author_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('export_import_id', sa.Integer(), sa.ForeignKey('export_import.id'), nullable=True),
    )
    _create_index('ix_chat_message_date_posted', 'chat_message', ['date_posted'])

    _create_table(
        'private_message',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('reddit_id', sa.String(collation='NOCASE'), nullable=True, unique=True),
        sa.Column('thread_id', sa.String(collation='NOCASE'), nullable=True),
        sa.Column('permalink', sa.String(), nullable=True),
        sa.Column('sender_name', sa.String(collation='NOCASE'), nullable=True),
        sa.Column('recipient_name', sa.String(collation='NOCASE'), nullable=True),
        sa.Column('subject', sa.String(), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('date_sent', sa.DateTime(), nullable=True),
        sa.Column('archived', sa.Boolean(), nullable=True),
        sa.Column('sender_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('recipient_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('export_import_id', sa.Integer(), sa.ForeignKey('export_import.id'), nullable=True),
    )
    _create_index('ix_private_message_thread_id', 'private_message', ['thread_id'])
    _create_index('ix_private_message_date_sent', 'private_message', ['date_sent'])

    _add_column('post', sa.Column('permalink', sa.String(), nullable=True))
    _add_column('comment', sa.Column('permalink', sa.String(), nullable=True))
    _add_column('comment', sa.Column('link_reddit_id', sa.String(collation='NOCASE'), nullable=True))
    _create_index('ix_comment_link_reddit_id', 'comment', ['link_reddit_id'])


def downgrade() -> None:
    """
    Removes everything added by upgrade().
    :return: None
    :rtype: None
    """
    with op.batch_alter_table('comment') as batch_op:  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy
        batch_op.drop_index('ix_comment_link_reddit_id')
        batch_op.drop_column('link_reddit_id')
        batch_op.drop_column('permalink')
    with op.batch_alter_table('post') as batch_op:  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy
        batch_op.drop_column('permalink')
    op.drop_table('private_message')  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy
    op.drop_table('chat_message')  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy
    op.drop_table('chat_channel')  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy
    op.drop_table('export_import')  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy
