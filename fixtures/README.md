# fixtures/

Golden test vectors, seed data, and the two real source workbooks, vendored
into this repo (Phase 5) because this repo is the only consumer of all five
files:

| File | Read by |
|------|---------|
| `engine-test-vectors.json` | `tests/engine/helpers.py` — the §17.3 golden-vector suite for `domain/engine/` |
| `bidcheck-test-vectors.json` | `tests/test_bidcheck_golden_vectors.py` — the same discipline applied to `domain/buyer/bidcheck.py` (referenced only in a doc comment on the frontend's TS mirror, `frontend/lib/buyer/bidcheck.ts` — that side has no automated test runner reading this file) |
| `reference-data-seed.json` | `core/reference_data.py` (the default seed path), `tests/conftest.py` (per-test reference-data fixture), and the `4011983f89e6_phase3b_reference_data_and_registries` Alembic migration (seeds the first `reference_data_versions` row) |
| `Active Purchase Orders 07-08-2026 (WORKING).xlsx` | `tests/pipeline_helpers.py`, `tests/test_snapshot_ingestion_e2e.py`, `tests/ingestion/helpers.py` — the normative engine source (§5, Appendix B) |
| `Active Purchase Orders 12-08-2026.xlsx` | `tests/ingestion/helpers.py` — the layout-drift regression fixture (§7.1, Appendix B) |

**Why vendored, not left in the shared parent folder:** these files
previously lived one level above `backend/`, alongside `frontend/` — outside
both git repos, per [[separate-repos-not-monorepo]]. That's fine for local
dev (both repos sit under one folder on disk) but breaks in CI, where
`actions/checkout` only ever brings in the one repo it's told to check
out — there is no parent folder, so a path reaching above the repo root
resolves to nothing. This silently broke `alembic upgrade head` (and every
fixtures-dependent test) in a clean CI checkout since Phase 1; see
`git log` around Phase 5 for the fix.

**Keeping this in sync:** the two JSON files hold values extracted from the
real source workbooks (§5.4, §6) and the workbooks themselves are the real
submitted files (Appendix B) — none of these are expected to change often.
If they ever do, edit the copies here directly — this is now the canonical
location, not a mirror of an external copy.

**Related fix, same root cause:** `tests/engine/conftest.py` and
`tests/ingestion/conftest.py` were *also* silently opening a real Postgres
connection despite existing specifically to prove their directories need
none (§17.1) — a second, unrelated bug this same investigation turned up.
See those files' own docstrings.
