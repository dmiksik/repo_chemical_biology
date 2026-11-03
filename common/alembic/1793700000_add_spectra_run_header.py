"""Add the mzML header (instrument, software, source files) to spectra runs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '1793700000'
down_revision = '1793680000'
branch_labels = ()
depends_on = None


def upgrade():
    """Upgrade database."""
    op.add_column(
        'spectra_run', sa.Column('header', sa.JSON().with_variant(postgresql.JSONB(), 'postgresql'), nullable=True)
    )


def downgrade():
    """Downgrade database."""
    op.drop_column('spectra_run', 'header')
