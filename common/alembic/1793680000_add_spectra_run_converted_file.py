"""Add the mzML converted from a raw file to spectra runs."""

import sqlalchemy as sa
import sqlalchemy_utils
from alembic import op

# revision identifiers, used by Alembic.
revision = '1793680000'
down_revision = '1793667500'
branch_labels = ()
depends_on = None


def upgrade():
    """Upgrade database."""
    op.add_column(
        'spectra_run', sa.Column('converted_file_id', sqlalchemy_utils.types.uuid.UUIDType(), nullable=True)
    )
    op.create_foreign_key(
        op.f('fk_spectra_run_converted_file_id_files_files'),
        'spectra_run',
        'files_files',
        ['converted_file_id'],
        ['id'],
    )


def downgrade():
    """Downgrade database."""
    op.drop_constraint(op.f('fk_spectra_run_converted_file_id_files_files'), 'spectra_run', type_='foreignkey')
    op.drop_column('spectra_run', 'converted_file_id')
