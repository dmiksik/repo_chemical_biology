# SPDX-FileCopyrightText: 2016-2018 CERN.
# SPDX-License-Identifier: MIT

"""Create repository branch."""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1793667388'
down_revision = None
branch_labels = ('repository',)
depends_on = 'dbdbc1b19cf2'


def upgrade():
    """Upgrade database."""
    pass


def downgrade():
    """Downgrade database."""
    pass
