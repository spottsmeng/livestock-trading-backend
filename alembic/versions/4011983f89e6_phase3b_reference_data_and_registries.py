"""phase3b_reference_data_and_registries

Revision ID: 4011983f89e6
Revises: 1a0dff07b31d
Create Date: 2026-09-08 12:15:57.771977

Includes a data migration seeding the first reference_data_versions row (and
species_registry/product_type_registry rows) from
fixtures/reference-data-seed.json — the exact values Phase 1-3 already had
live via core.reference_data's static JSON loader. This is a continuity
migration, not a business change: cif_buffer/dnbp_factor/standard_weight
keep their current values, `is_active=True` immediately so
get_active_everhealth_config finds a version on first read, and
`impact_previewed_at` is stamped at migration time since there is no
meaningful "before" state to preview a value that has already been live
since Phase 1 against (§6.5's impact-preview gate protects a *future*
change, not the data's own introduction).

fixtures/ is vendored inside backend/ (Phase 5 — see backend/fixtures/
README.md) so this migration is reproducible from a bare checkout; it
previously reached one level above backend/ into a shared, untracked
folder, which meant `alembic upgrade head` could never actually complete
in CI.
"""
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '4011983f89e6'
down_revision: Union[str, None] = '1a0dff07b31d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SEED_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "reference-data-seed.json"


def _load_seed() -> dict:
    return json.loads(_SEED_PATH.read_text())


def _seed_reference_data(data: dict) -> None:
    everhealth = data["everhealth"]
    effective_from = datetime.combine(date.fromisoformat(data["effective_from"]), datetime.min.time(), tzinfo=UTC)
    now = datetime.now(UTC)
    version_id = str(uuid.uuid4())

    versions_table = sa.table(
        "reference_data_versions",
        sa.column("id", sa.UUID()),
        sa.column("effective_from", sa.DateTime(timezone=True)),
        sa.column("created_by", sa.UUID()),
        sa.column("note", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("activated_at", sa.DateTime(timezone=True)),
        sa.column("impact_previewed_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        versions_table,
        [
            {
                "id": version_id,
                "effective_from": effective_from,
                "created_by": None,
                "note": "Seeded from fixtures/reference-data-seed.json at migration time (Phase 3b) — "
                "continuity migration, not a business change.",
                "is_active": True,
                "activated_at": now,
                "impact_previewed_at": now,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )

    entries_table = sa.table(
        "reference_data_entries",
        sa.column("id", sa.UUID()),
        sa.column("version_id", sa.UUID()),
        sa.column(
            "table_key",
            postgresql.ENUM(
                "CIF_BUFFER_PER_KG",
                "DNBP_FACTOR",
                "STANDARD_WEIGHT",
                name="reference_data_table_key",
                create_type=False,
            ),
        ),
        sa.column("key1", sa.String()),
        sa.column("key2", sa.String()),
        sa.column("value", sa.Numeric(18, 10)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    def _entry(table_key: str, key1: str | None, value) -> dict:
        return {
            "id": str(uuid.uuid4()),
            "version_id": version_id,
            "table_key": table_key,
            "key1": key1,
            "key2": None,
            "value": Decimal(str(value)),
            "created_at": now,
            "updated_at": now,
        }

    entries = [_entry("CIF_BUFFER_PER_KG", None, everhealth["cif_buffer_per_kg"]["value"])]
    entries += [
        _entry("DNBP_FACTOR", species, factor)
        for species, factor in everhealth["dnbp_factor_by_species"]["values"].items()
    ]
    entries += [
        _entry("STANDARD_WEIGHT", species, weight)
        for species, weight in everhealth["standard_weight_by_species"]["values"].items()
    ]
    op.bulk_insert(entries_table, entries)


def _seed_registries(data: dict) -> None:
    now = datetime.now(UTC)

    species_table = sa.table(
        "species_registry",
        sa.column("code", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_by", sa.UUID()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        species_table,
        [
            {
                "code": code,
                "display_name": code.title(),
                "is_active": True,
                "created_by": None,
                "created_at": now,
                "updated_at": now,
            }
            for code in data["open_registries"]["species"]["seed_rows"]
        ],
    )

    product_type_table = sa.table(
        "product_type_registry",
        sa.column("code", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_by", sa.UUID()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        product_type_table,
        [
            {
                "code": code,
                "display_name": code,  # e.g. "6 WAY", "CCS" — title-casing would mangle the acronym
                "is_active": True,
                "created_by": None,
                "created_at": now,
                "updated_at": now,
            }
            for code in data["open_registries"]["product_type"]["seed_rows"]
        ],
    )


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('product_type_registry',
    sa.Column('code', sa.String(), nullable=False),
    sa.Column('display_name', sa.String(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('code')
    )
    op.create_table('reference_data_versions',
    sa.Column('effective_from', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('note', sa.String(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('impact_previewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reference_data_versions_is_active'), 'reference_data_versions', ['is_active'], unique=False)
    op.create_table('species_registry',
    sa.Column('code', sa.String(), nullable=False),
    sa.Column('display_name', sa.String(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('code')
    )
    op.create_table('reference_data_drift',
    sa.Column('snapshot_id', sa.UUID(), nullable=False),
    sa.Column('table_key', sa.String(), nullable=False),
    sa.Column('key1', sa.String(), nullable=False),
    sa.Column('old_value', sa.Numeric(precision=18, scale=10), nullable=True),
    sa.Column('new_value', sa.Numeric(precision=18, scale=10), nullable=True),
    sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('acknowledged_by', sa.UUID(), nullable=True),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['acknowledged_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['snapshot_id'], ['order_snapshots.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reference_data_drift_snapshot_id'), 'reference_data_drift', ['snapshot_id'], unique=False)
    op.create_table('reference_data_entries',
    sa.Column('version_id', sa.UUID(), nullable=False),
    sa.Column('table_key', sa.Enum('CIF_BUFFER_PER_KG', 'DNBP_FACTOR', 'STANDARD_WEIGHT', name='reference_data_table_key'), nullable=False),
    sa.Column('key1', sa.String(), nullable=True),
    sa.Column('key2', sa.String(), nullable=True),
    sa.Column('value', sa.Numeric(precision=18, scale=10), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['version_id'], ['reference_data_versions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reference_data_entries_version_id'), 'reference_data_entries', ['version_id'], unique=False)
    # ### end Alembic commands ###

    seed = _load_seed()
    _seed_reference_data(seed)
    _seed_registries(seed)


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('ix_reference_data_entries_version_id'), table_name='reference_data_entries')
    op.drop_table('reference_data_entries')
    op.drop_index(op.f('ix_reference_data_drift_snapshot_id'), table_name='reference_data_drift')
    op.drop_table('reference_data_drift')
    op.drop_table('species_registry')
    op.drop_index(op.f('ix_reference_data_versions_is_active'), table_name='reference_data_versions')
    op.drop_table('reference_data_versions')
    op.drop_table('product_type_registry')
    # ### end Alembic commands ###
    # Autogenerate drops the table but never the enum type behind
    # table_key — without this, a later re-upgrade fails with
    # "type reference_data_table_key already exists" (found by actually
    # running the down/up cycle, not just eyeballing the diff).
    sa.Enum(name='reference_data_table_key').drop(op.get_bind(), checkfirst=True)
