"""Create spectra index tables."""

import sqlalchemy as sa
import sqlalchemy_utils
from alembic import op

# revision identifiers, used by Alembic.
revision = '1793667500'
down_revision = '1793667388'
branch_labels = ()
depends_on = None


def upgrade():
    """Upgrade database."""
    op.create_table(
        'spectra_run',
        sa.Column('id', sqlalchemy_utils.types.uuid.UUIDType(), nullable=False),
        sa.Column('record_pid', sa.String(length=255), nullable=False),
        sa.Column('file_key', sa.Text(), nullable=False),
        sa.Column('ms_run', sa.Text(), nullable=False),
        sa.Column('checksum', sa.String(length=255), nullable=True),
        sa.Column('status', sa.CHAR(1), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('spectra_count', sa.Integer(), nullable=True),
        sa.Column('created', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_spectra_run')),
        sa.UniqueConstraint('record_pid', 'ms_run', name='uq_spectra_run_record_ms_run'),
    )
    op.create_index(op.f('ix_spectra_run_record_pid'), 'spectra_run', ['record_pid'])

    op.create_table(
        'spectra_index',
        sa.Column('run_id', sqlalchemy_utils.types.uuid.UUIDType(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('native_id', sa.Text(), nullable=False),
        sa.Column('scan', sa.Integer(), nullable=True),
        sa.Column('offset', sa.BigInteger(), nullable=False),
        sa.Column('length', sa.Integer(), nullable=False),
        sa.Column('ms_level', sa.SmallInteger(), nullable=True),
        sa.Column('rt', sa.Float(), nullable=True),
        sa.Column('precursor_mz', sa.Float(), nullable=True),
        sa.Column('charge', sa.SmallInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ['run_id'], ['spectra_run.id'], name=op.f('fk_spectra_index_run_id_spectra_run'), ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('run_id', 'position', name=op.f('pk_spectra_index')),
    )
    op.create_index('ix_spectra_index_run_scan', 'spectra_index', ['run_id', 'scan'])
    op.create_index('ix_spectra_index_run_native_id', 'spectra_index', ['run_id', 'native_id'])


def downgrade():
    """Downgrade database."""
    op.drop_table('spectra_index')
    op.drop_table('spectra_run')
