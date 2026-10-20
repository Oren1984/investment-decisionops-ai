"""Meeting links for Zoom, Google Meet, Microsoft Teams and other https providers (decision D-A).

Adds meeting.link_provider. Existing manual and Zoom-API meetings could only hold Zoom links, so they are
backfilled as 'zoom'; simulated (mock) meetings have no link.

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("meeting", sa.Column("link_provider", sa.String(16), nullable=True))
    op.execute("UPDATE meeting SET link_provider = 'zoom' WHERE provider IN ('manual', 'zoom')")


def downgrade() -> None:
    op.drop_column("meeting", "link_provider")
