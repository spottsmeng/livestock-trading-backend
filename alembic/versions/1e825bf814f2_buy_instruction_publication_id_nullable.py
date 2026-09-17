"""buy_instruction_publication_id_nullable

Revision ID: 1e825bf814f2
Revises: 914773cb42d7
Create Date: 2026-09-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1e825bf814f2'
down_revision: Union[str, None] = '914773cb42d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A DnbpPublication must never come into existence except as the result
    # of publishing an already-approved BuyInstruction (see
    # services/buy_instruction_service.py's `publish`), so an instruction is
    # now generated straight from a CALCULATED snapshot with no publication
    # yet in hand — publication_id stays NULL through DRAFT and is only set
    # once `publish()` actually creates the publication and links it.
    op.alter_column('buy_instructions', 'publication_id', existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    op.alter_column('buy_instructions', 'publication_id', existing_type=sa.UUID(), nullable=False)
