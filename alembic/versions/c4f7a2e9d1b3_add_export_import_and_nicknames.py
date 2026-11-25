"""
Add the Reddit data export import tables, the comment parent post id, and reddit object nicknames.

- export_import, chat_channel, chat_message and private_message hold what is imported from a Reddit data export.
  People in conversations (chat authors, message senders and recipients) reference reddit objects, so that a subreddit
  sender (modmail) can be stored as a subreddit; an import references its owner, and a chat channel its subreddit.
  A chat channel belongs to no import or account (several accounts' exports can share it); its messages record the
  import they came from.
- comment.link_reddit_id keeps the parent post's reddit id for imported comments whose post is not stored, so the
  comment can be attached when the post is added later.
- reddit_object.nickname is an optional user-chosen label shown in place of the reddit name, and
  chat_channel.nickname likewise names a chat whose channel name Reddit left empty (or overrides it).
- chat_message and private_message record whether their media links were extracted (extracted, extraction_date,
  extraction_error, error_message), and content.chat_message_id / content.private_message_id tie the content
  extracted from a message to that message.
- chat_reaction stores each distinct chat reaction image once, shared by every chat, and chat_message.reaction_id
  points a reaction message to it.  Reddit's export records a reaction as a chat message whose whole text is the url
  of one of Reddit's reaction images (GIF or PNG) on i.redd.it, replying to the message reacted to; reaction messages already stored
  are linked here, with the same rule the application uses, and marked extracted so their image is not downloaded
  again for each message.

DatabaseHandler runs create_all() before the migrator runs, so the new tables and their indexes normally exist
already, empty, by the time this migration runs.  Every step is therefore skipped when what it creates exists, and the
message extraction columns and chat_message.reaction_id are also added to message tables created by an earlier form of
this revision.


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

import logging
import re
from datetime import datetime

import sqlalchemy as sa
from alembic import op


logger = logging.getLogger(f'DownloaderForReddit.{__name__}')

# revision identifiers, used by Alembic.
revision = 'c4f7a2e9d1b3'  # pylint: disable=invalid-name  # names required by alembic
down_revision = '7b1f4c8a9d2e'  # pylint: disable=invalid-name  # names required by alembic
branch_labels = None  # pylint: disable=invalid-name  # names required by alembic
depends_on = None  # pylint: disable=invalid-name  # names required by alembic

_NEW_TABLES = ('private_message', 'chat_message', 'chat_reaction', 'chat_channel', 'export_import')  # dependants first
_MESSAGE_TABLES = ('chat_message', 'private_message')
# The content columns tying content to a message: column name -> (referenced table, index name, foreign key name).
_CONTENT_MESSAGE_COLUMNS = {
    'chat_message_id': ('chat_message', 'ix_content_chat_message_id', 'fk_content_chat_message_id'),
    'private_message_id': ('private_message', 'ix_content_private_message_id', 'fk_content_private_message_id'),
}
_REACTION_INDEX = 'ix_chat_message_reaction_id'
_REACTION_FOREIGN_KEY = 'fk_chat_message_reaction_id'
_STORED_DATE_FORMAT = '%Y-%m-%d %H:%M:%S.%f'  # how SQLAlchemy's DateTime stores dates in SQLite
# The rule of utils.chat_reactions.REACTION_URL, copied so the migration does not change if the rule does.
_REACTION_URL = re.compile(r'^https?://i\.redd\.it/[a-z0-9]+\.(gif|png)$', re.IGNORECASE)
# The members of core.errors.Error, as stored by the Enum(Error) columns.  Listed here so the migration does not
# change if the enum does.
_ERROR_NAMES = ('UNSUCCESSFUL_RESPONSE', 'UNSUPPORTED_DOMAIN', 'DOES_NOT_EXIST', 'FAILED_TO_LOCATE', 'FORBIDDEN',
                'TEXT_LINK_FAILURE', 'FAILED_TO_EXTRACT', 'FAILED_SELF_POST', 'DUPLICATE_CONTENT', 'FAILED_FILTER',
                'MULTIPART_FAILURE', 'UNKNOWN_ERROR', 'CONNECTION_ERROR', 'DOWNLOAD_STOPPED', 'TEXT_FAILURE',
                'UNRECOGNIZED_EXTENSION', 'RATE_LIMIT_ERROR', 'CREDIT_ERROR')


def _extraction_columns() -> list[sa.Column]:
    """
    Returns new copies of the columns that record a message's link extraction.  Copies are needed because a column
    can belong to only one table.  No CHECK constraints are made: SQLite cannot add them to an existing table, and the
    ORM's Enum type validates the values.
    :return: The columns.
    :rtype: list[sa.Column]
    """
    return [
        sa.Column('extracted', sa.Boolean(create_constraint=False), nullable=True),
        sa.Column('extraction_date', sa.DateTime(), nullable=True),
        sa.Column('extraction_error', sa.Enum(*_ERROR_NAMES, name='error', create_constraint=False), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
    ]


def _inspector() -> sa.engine.reflection.Inspector:
    """
    Returns an inspector for the database being migrated.
    :return: The inspector.
    :rtype: sa.engine.reflection.Inspector
    """
    return sa.inspect(op.get_bind())  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy


def _table_names() -> list[str]:
    """
    Lists the tables in the database being migrated.
    :return: The table names.
    :rtype: list[str]
    """
    return _inspector().get_table_names()


def _column_names(table: str) -> set[str]:
    """
    Lists the columns of a table in the database being migrated.
    :param table: The table name.
    :type table: str
    :return: The column names.
    :rtype: set[str]
    """
    return {column['name'] for column in _inspector().get_columns(table)}


def _index_names(table: str) -> set[str]:
    """
    Lists the indexes of a table in the database being migrated.
    :param table: The table name.
    :type table: str
    :return: The index names.
    :rtype: set[str]
    """
    return {index['name'] for index in _inspector().get_indexes(table)}


def _create_table(name: str, *columns: sa.Column) -> None:
    """
    Creates a table unless it exists.
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
    if name not in _index_names(table):
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
    if column.name not in _column_names(table):
        op.add_column(table, column)  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy


def upgrade() -> None:
    """
    Creates the export import tables, adds comment.link_reddit_id and reddit_object.nickname, and links the chat
    reaction messages already stored.
    :return: None
    :rtype: None
    """
    _create_table(
        'export_import',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('file_name', sa.String(), nullable=True),
        sa.Column('file_sha256', sa.String(), nullable=True),
        sa.Column('import_date', sa.DateTime(), nullable=True),
        sa.Column('post_count', sa.Integer(), nullable=True),
        sa.Column('comment_count', sa.Integer(), nullable=True),
        sa.Column('chat_message_count', sa.Integer(), nullable=True),
        sa.Column('private_message_count', sa.Integer(), nullable=True),
        sa.Column('owner_id', sa.Integer(), sa.ForeignKey('user.id'), nullable=True),
        sa.Column('download_session_id', sa.Integer(), sa.ForeignKey('download_session.id'), nullable=True),
    )
    _create_index('ix_export_import_file_sha256', 'export_import', ['file_sha256'])

    _create_table(
        'chat_channel',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('channel_url', sa.String(), nullable=True, unique=True),
        sa.Column('channel_name', sa.String(collation='NOCASE'), nullable=True),
        sa.Column('nickname', sa.String(collation='NOCASE'), nullable=True),
        sa.Column('conversation_type', sa.String(), nullable=True),
        sa.Column('subreddit_id', sa.Integer(), sa.ForeignKey('subreddit.id'), nullable=True),
    )

    _create_table(
        'chat_reaction',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('url', sa.String(collation='NOCASE'), nullable=True, unique=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('enabled', sa.Boolean(create_constraint=False), nullable=True),
        sa.Column('file_name', sa.String(), nullable=True),
        sa.Column('fetch_error', sa.String(), nullable=True),
        sa.Column('date_added', sa.DateTime(), nullable=True),
    )

    _create_table(
        'chat_message',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('message_id', sa.String(), nullable=True, unique=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('date_posted', sa.DateTime(), nullable=True),
        sa.Column('date_updated', sa.DateTime(), nullable=True),
        sa.Column('thread_parent_message_id', sa.String(), nullable=True),
        sa.Column('channel_id', sa.Integer(), sa.ForeignKey('chat_channel.id'), nullable=True),
        sa.Column('author_id', sa.Integer(), sa.ForeignKey('reddit_object.id'), nullable=True),
        sa.Column('export_import_id', sa.Integer(), sa.ForeignKey('export_import.id'), nullable=True),
        sa.Column('reaction_id', sa.Integer(), sa.ForeignKey('chat_reaction.id'), nullable=True),
        *_extraction_columns(),
    )
    _create_index('ix_chat_message_date_posted', 'chat_message', ['date_posted'])

    _create_table(
        'private_message',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('reddit_id', sa.String(collation='NOCASE'), nullable=True, unique=True),
        sa.Column('thread_id', sa.String(collation='NOCASE'), nullable=True),
        sa.Column('subject', sa.String(), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('date_sent', sa.DateTime(), nullable=True),
        sa.Column('archived', sa.Boolean(), nullable=True),
        sa.Column('sender_id', sa.Integer(), sa.ForeignKey('reddit_object.id'), nullable=True),
        sa.Column('recipient_id', sa.Integer(), sa.ForeignKey('reddit_object.id'), nullable=True),
        sa.Column('export_import_id', sa.Integer(), sa.ForeignKey('export_import.id'), nullable=True),
        *_extraction_columns(),
    )
    _create_index('ix_private_message_thread_id', 'private_message', ['thread_id'])
    _create_index('ix_private_message_date_sent', 'private_message', ['date_sent'])

    _add_column('comment', sa.Column('link_reddit_id', sa.String(collation='NOCASE'), nullable=True))
    _create_index('ix_comment_link_reddit_id', 'comment', ['link_reddit_id'])
    _add_column('reddit_object', sa.Column('nickname', sa.String(collation='NOCASE'), nullable=True))

    for table in _MESSAGE_TABLES:  # message tables made by an earlier form of this revision lack these
        for column in _extraction_columns():
            _add_column(table, column)
    _add_content_message_columns()
    _add_chat_reaction_column()
    _link_existing_reactions()


def _add_chat_reaction_column() -> None:
    """
    Adds chat_message.reaction_id, with its foreign key and index, unless it exists.  SQLite cannot add a foreign key
    to an existing table, so a batch operation rebuilds the chat_message table.
    :return: None
    :rtype: None
    """
    if 'reaction_id' not in _column_names('chat_message'):
        with op.batch_alter_table('chat_message') as batch_op:  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy
            batch_op.add_column(sa.Column('reaction_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key(_REACTION_FOREIGN_KEY, 'chat_reaction', ['reaction_id'], ['id'])
    _create_index(_REACTION_INDEX, 'chat_message', ['reaction_id'])


def _link_existing_reactions() -> None:
    """
    Links the chat messages already stored that are reactions: replies whose whole text is a reaction image url.  Each
    distinct url becomes one chat_reaction row, and its messages are marked extracted.
    :return: None
    :rtype: None
    """
    bind = op.get_bind()  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy
    reaction_ids = {url.lower(): reaction_id for reaction_id, url in bind.execute(sa.text('SELECT id, url FROM chat_reaction'))}
    rows = bind.execute(sa.text("SELECT id, body FROM chat_message WHERE reaction_id IS NULL AND body LIKE '%i.redd.it/%' "
                                "AND thread_parent_message_id IS NOT NULL AND thread_parent_message_id != ''")).fetchall()
    linked = 0
    for message_id, body in rows:
        url = (body or '').strip()
        if not _REACTION_URL.match(url):
            continue
        if url.lower() not in reaction_ids:
            bind.execute(sa.text('INSERT INTO chat_reaction (url, enabled, date_added) VALUES (:url, 1, :now)'),
                         {'url': url, 'now': datetime.now().strftime(_STORED_DATE_FORMAT)})
            reaction_ids[url.lower()] = bind.execute(sa.text('SELECT id FROM chat_reaction WHERE url = :url'), {'url': url}).scalar()
        bind.execute(sa.text('UPDATE chat_message SET reaction_id = :reaction_id, extracted = 1 WHERE id = :id'),
                     {'reaction_id': reaction_ids[url.lower()], 'id': message_id})
        linked += 1
    if linked:
        logger.info('Linked %d chat reaction messages to %d reactions', linked, len(reaction_ids))


def _add_content_message_columns() -> None:
    """
    Adds the content columns that tie content to a message, with their foreign keys and indexes, unless they exist.
    SQLite cannot add a foreign key to an existing table, so a batch operation rebuilds the content table.
    :return: None
    :rtype: None
    """
    missing = {name: spec for name, spec in _CONTENT_MESSAGE_COLUMNS.items() if name not in _column_names('content')}
    if missing:
        with op.batch_alter_table('content') as batch_op:  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy
            for name, (table, _index, foreign_key) in missing.items():
                batch_op.add_column(sa.Column(name, sa.Integer(), nullable=True))
                batch_op.create_foreign_key(foreign_key, table, [name], ['id'])
    for name, (_table, index, _foreign_key) in _CONTENT_MESSAGE_COLUMNS.items():
        _create_index(index, 'content', [name])


def _drop_content_message_columns() -> None:
    """
    Removes the content columns that tie content to a message, with their indexes and foreign keys.
    :return: None
    :rtype: None
    """
    present = [name for name in _CONTENT_MESSAGE_COLUMNS if name in _column_names('content')]
    if not present:
        return
    indexes = _index_names('content')
    with op.batch_alter_table('content') as batch_op:  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy
        for name in present:
            index = _CONTENT_MESSAGE_COLUMNS[name][1]
            if index in indexes:
                batch_op.drop_index(index)
            batch_op.drop_column(name)


def downgrade() -> None:
    """
    Removes everything added by upgrade().  SQLite cannot drop columns in place, so batch operations rebuild the
    altered tables.
    :return: None
    :rtype: None
    """
    _drop_content_message_columns()
    for table in _NEW_TABLES:
        if table in _table_names():
            op.drop_table(table)  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy
    if 'link_reddit_id' in _column_names('comment'):
        with op.batch_alter_table('comment') as batch_op:  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy
            if 'ix_comment_link_reddit_id' in _index_names('comment'):
                batch_op.drop_index('ix_comment_link_reddit_id')
            batch_op.drop_column('link_reddit_id')
    if 'nickname' in _column_names('reddit_object'):
        with op.batch_alter_table('reddit_object') as batch_op:  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy
            batch_op.drop_column('nickname')
