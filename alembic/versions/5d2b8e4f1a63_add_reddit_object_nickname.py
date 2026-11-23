"""
Add the optional nickname column to the reddit_object table.

A nickname is a user-chosen label shown in place of a user's or subreddit's reddit name in the main window lists.


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
revision = '5d2b8e4f1a63'  # pylint: disable=invalid-name  # names required by alembic
down_revision = '3e5a9c1d7b42'  # pylint: disable=invalid-name  # names required by alembic
branch_labels = None  # pylint: disable=invalid-name  # names required by alembic
depends_on = None  # pylint: disable=invalid-name  # names required by alembic


def _reddit_object_columns() -> list[str]:
    """
    Lists the columns of the reddit_object table in the database being migrated.
    :return: The column names.
    :rtype: list[str]
    """
    inspector = sa.inspect(op.get_bind())  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy
    return [column['name'] for column in inspector.get_columns('reddit_object')]


def upgrade() -> None:
    """
    Adds the nullable nickname column to reddit_object, unless it already exists.
    :return: None
    :rtype: None
    """
    if 'nickname' not in _reddit_object_columns():
        op.add_column('reddit_object', sa.Column('nickname', sa.String(collation='NOCASE'), nullable=True))  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy


def downgrade() -> None:
    """
    Removes the nickname column from reddit_object.  SQLite cannot drop columns in place, so a batch operation
    rebuilds the table.
    :return: None
    :rtype: None
    """
    if 'nickname' in _reddit_object_columns():
        with op.batch_alter_table('reddit_object') as batch_op:  # pylint: disable=no-member  # approved: alembic.op is a runtime proxy
            batch_op.drop_column('nickname')
