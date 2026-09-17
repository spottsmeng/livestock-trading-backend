"""Wipe all uploaded-spreadsheet / business-transaction data from the dev
DB, leaving accounts and configuration untouched — scripting the same
cleanup previously done by hand via `docker exec ... psql -c "TRUNCATE ..."`
so it's not retyped (and potentially mistyped) each time.

Wipes: every order snapshot/line/working/issue/acknowledgment/removal,
reference-data drift records, correction requests, DNBP publications
(+ lines + deliveries), buy instructions (+ lines + fills), buy entries,
and the audit log.

Keeps: organisations, users, reference_data_versions/entries and the open
registries — nothing about who can log in or how the DNBP engine is
configured is touched.

Run with:      uv run python -m scripts.wipe_business_data
Non-interactive (skips the confirmation prompt): add --yes
"""

import argparse
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.db import async_session_factory

# Order doesn't matter — CASCADE handles the FKs between these tables (and
# any other table referencing one of them) in a single statement.
_WIPE_TABLES = [
    "order_snapshots",
    "order_lines",
    "order_workings",
    "validation_issues",
    "order_issue_acknowledgments",
    "order_line_removals",
    "reference_data_drift",
    "correction_requests",
    "dnbp_publications",
    "dnbp_publication_lines",
    "dnbp_publication_deliveries",
    "buy_instructions",
    "buy_instruction_lines",
    "buy_instruction_line_fills",
    "buy_entries",
    "market_observations",
    "audit_log",
]

_KEPT_TABLES = [
    "organisations",
    "users",
    "reference_data_versions",
    "reference_data_entries",
    "species_registry",
    "product_type_registry",
]


async def _counts(session: AsyncSession, tables: list[str]) -> dict[str, int]:
    counts = {}
    for table in tables:
        # Table names come only from the fixed lists above, never from
        # user input, so building the statement by name is safe here.
        result = await session.execute(text(f"SELECT COUNT(*) FROM {table}"))
        counts[table] = result.scalar_one()
    return counts


def _print_counts(title: str, counts: dict[str, int]) -> None:
    print(f"\n{title}")
    for table, count in counts.items():
        print(f"  {table:<30} {count}")


async def main(*, skip_confirm: bool) -> None:
    async with async_session_factory() as session:
        before = await _counts(session, _WIPE_TABLES)
        kept = await _counts(session, _KEPT_TABLES)

        # Host/db only — never print the credentials half of the URL.
        target = settings.database_url.rsplit("@", 1)[-1]
        print(f"Target database: {target}")
        _print_counts("Will be wiped:", before)
        _print_counts("Left untouched:", kept)

        if not any(before.values()):
            print("\nNothing to wipe — every business-data table is already empty.")
            return

        if not skip_confirm:
            answer = input("\nType 'yes' to truncate the tables above: ").strip().lower()
            if answer != "yes":
                print("Aborted — nothing was changed.")
                return

        await session.execute(text(f"TRUNCATE TABLE {', '.join(_WIPE_TABLES)} CASCADE"))
        await session.commit()

        after = await _counts(session, _WIPE_TABLES)
        _print_counts("Now:", after)
        print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", "-y", action="store_true", help="Skip the interactive confirmation prompt.")
    args = parser.parse_args()
    asyncio.run(main(skip_confirm=args.yes))
