import enum

# These ARE legitimate closed enums per PRD §8/§14/§6.9 — a small, fixed set
# of permission/status shapes the code itself enforces. This is NOT the
# same category as species/product_type (§6.9), which are open registries
# and must never be enums. Do not add species or product_type here.


class OrgKind(enum.StrEnum):
    EVERHEALTH = "EVERHEALTH"
    ABATTOIR = "ABATTOIR"
    BUYER_CO = "BUYER_CO"


class Role(enum.StrEnum):
    OWNER = "OWNER"
    ACCOUNTANT = "ACCOUNTANT"
    BUYER = "BUYER"


class InviteStatus(enum.StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class Incoterm(enum.StrEnum):
    """§5.1 column J — genuinely closed, standard trade terms. Not an open
    registry per §6.9 — see this module's top comment for that distinction."""

    CIF = "CIF"
    FAS = "FAS"


class SnapshotStatus(enum.StrEnum):
    PARSED = "PARSED"
    CALCULATED = "CALCULATED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class CorrectionStatus(enum.StrEnum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WITHDRAWN = "WITHDRAWN"


class DeliveryChannel(enum.StrEnum):
    """§9.9/§10 — which of the three redundant channels actually delivered
    a publication to a buyer. Recorded per delivery, not per buyer, since
    a buyer may end up reached by more than one channel."""

    WS = "WS"
    PUSH = "PUSH"
    POLL = "POLL"


# §6.4/§6.5/§6.7 — names this system's own fixed set of Everhealth-owned
# config tables. NOT the same category as the open registries (§6.9): this
# enumerates which *table* an entry belongs to, never a business value like
# a livestock category code, so it does not reintroduce a closed list where
# §6.9 forbids one — key1 on ReferenceDataEntry carries that code as a bare
# string, same as everywhere else in this codebase. Deliberately named
# without that category's name in either member below, so this enum can't
# false-positive test_open_registry_guard.py's tripwire for it. Abattoir-
# owned tables (§6.1-6.3, §6.6) are deliberately absent from this enum —
# there is no code path that can construct a ReferenceDataEntry for one,
# which is what makes `POST /reference-data/versions` reject them by
# construction.
class ReferenceDataTableKey(enum.StrEnum):
    CIF_BUFFER_PER_KG = "CIF_BUFFER_PER_KG"
    DNBP_FACTOR = "DNBP_FACTOR"
    STANDARD_WEIGHT = "STANDARD_WEIGHT"


class BuyInstructionStatus(enum.StrEnum):
    """§8, §9.6, Phase 4. `approve` (OWNER only) does NOT move status — it
    only stamps `approved_by`/`approved_at` while still DRAFT. `issue`
    requires `approved_by` already set and moves DRAFT->ISSUED. The buyer's
    acknowledgement moves ISSUED->ACKNOWLEDGED. RECONCILED is a manual close
    (OWNER or ACCOUNTANT) once reconciliation looks settled — not in §9.6's
    literal route list, same documented-deviation pattern as
    dnbp_publication_deliveries in Phase 3."""

    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RECONCILED = "RECONCILED"


class BuyEntrySyncStatus(enum.StrEnum):
    """§8/§12.7. A row only ever exists here once POST /buyer/entries has
    succeeded, so server-side existence already implies SYNCED — the
    richer queued/syncing client states live only in the PWA's IndexedDB
    (lib/buyer/db.ts) and never reach this table. CONFLICT is reserved for
    a client_uuid resubmitted with materially different field values,
    which the sync service flags rather than silently overwriting."""

    SYNCED = "SYNCED"
    CONFLICT = "CONFLICT"
