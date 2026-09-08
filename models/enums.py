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
