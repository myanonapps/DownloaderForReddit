"""Add reddit_id columns to User and Subreddit tables."""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = '7b1f4c8a9d2e'
down_revision = 'cea7c1daec2b'
branch_labels = None
depends_on = None


def upgrade():
    """Add reddit_id column to user and subreddit tables."""
    # Add reddit_id column to user table
    op.add_column('user', sa.Column('reddit_id', sa.String(collation='NOCASE'), nullable=True))
    
    # Add reddit_id column to subreddit table
    op.add_column('subreddit', sa.Column('reddit_id', sa.String(collation='NOCASE'), nullable=True))


def downgrade():
    """Remove reddit_id columns from user and subreddit tables."""
    # Remove reddit_id column from user table
    op.drop_column('user', 'reddit_id')
    
    # Remove reddit_id column from subreddit table
    op.drop_column('subreddit', 'reddit_id')