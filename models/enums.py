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
