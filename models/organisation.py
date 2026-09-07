from sqlalchemy import Enum
from sqlalchemy.orm import Mapped, mapped_column

from models.base import TimestampedBase
from models.enums import OrgKind


class Organisation(TimestampedBase):
    """§8 — Everhealth (Livestock Trading Co.), the Abattoir, and the
    External Buyer Co. The Abattoir row exists for data-isolation modeling
    only; it never gets user accounts (§2.1.1) — nobody there logs in."""

    __tablename__ = "organisations"

    name: Mapped[str] = mapped_column(unique=True)
    kind: Mapped[OrgKind] = mapped_column(Enum(OrgKind, name="org_kind"))
