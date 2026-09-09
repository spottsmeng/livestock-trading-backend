"""Bootstrap seed for reference data (§6): one active reference_data_versions
row plus the open species/product_type registries. In a real environment
this was a one-time job done by the phase3b_reference_data_and_registries
migration — a data migration only ever runs once, so it can't be used to
restore this after a dev DB reset. This script exists for exactly that:
reseeding reference data into an already-migrated, otherwise-empty DB.

Same source file tests/conftest.py's _seed_reference_data fixture reads
(fixtures/reference-data-seed.json), same values — this just targets the
real dev DB and the real "everhealth" org instead of a per-test one.

Run with: uv run python -m scripts.seed_reference_data
"""

import asyncio
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from core.db import async_session_factory
from models.enums import OrgKind, ReferenceDataTableKey
from models.reference_data import ProductTypeRegistry, ReferenceDataEntry, ReferenceDataVersion, SpeciesRegistry
from repositories import organisations as org_repo
from repositories import reference_data as reference_data_repo

_SEED_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "reference-data-seed.json"


async def main() -> None:
    async with async_session_factory() as session:
        existing = await reference_data_repo.get_active_version(session)
        if existing is not None:
            print(f"An active reference data version already exists ({existing.id}) — nothing to do.")
            return

        everhealth = await org_repo.get_by_kind(session, OrgKind.EVERHEALTH)
        if everhealth is None:
            raise RuntimeError("No Everhealth org found — run `uv run python -m scripts.seed` first.")

        data = json.loads(_SEED_PATH.read_text())
        everhealth_data = data["everhealth"]

        version = ReferenceDataVersion(
            effective_from=datetime.combine(
                date.fromisoformat(data["effective_from"]), datetime.min.time(), tzinfo=UTC
            ),
            created_by=None,
            note="Initial seed (scripts/seed_reference_data.py)",
            is_active=True,
            activated_at=datetime.now(UTC),
            impact_previewed_at=datetime.now(UTC),
        )
        session.add(version)
        await session.flush()

        session.add(
            ReferenceDataEntry(
                version_id=version.id,
                table_key=ReferenceDataTableKey.CIF_BUFFER_PER_KG,
                key1=None,
                value=Decimal(str(everhealth_data["cif_buffer_per_kg"]["value"])),
            )
        )
        for species, factor in everhealth_data["dnbp_factor_by_species"]["values"].items():
            session.add(
                ReferenceDataEntry(
                    version_id=version.id, table_key=ReferenceDataTableKey.DNBP_FACTOR, key1=species,
                    value=Decimal(str(factor)),
                )
            )
        for species, weight in everhealth_data["standard_weight_by_species"]["values"].items():
            session.add(
                ReferenceDataEntry(
                    version_id=version.id, table_key=ReferenceDataTableKey.STANDARD_WEIGHT, key1=species,
                    value=Decimal(str(weight)),
                )
            )

        for code in data["open_registries"]["species"]["seed_rows"]:
            session.add(SpeciesRegistry(code=code, display_name=code.title(), is_active=True, created_by=None))
        for code in data["open_registries"]["product_type"]["seed_rows"]:
            session.add(ProductTypeRegistry(code=code, display_name=code, is_active=True, created_by=None))

        await session.commit()
        print(f"Seeded and activated reference data version {version.id} for {everhealth.name}.")


if __name__ == "__main__":
    asyncio.run(main())
