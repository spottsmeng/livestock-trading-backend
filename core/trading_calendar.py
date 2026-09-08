"""§6.8, §13.1, non-negotiable #6 — the Buy Instruction's reconciliation and
summary blocks are scoped to the trading week (Monday-Sunday) containing the
instruction's `trade_date`, in Australia/Melbourne — confirmed with Terence
directly against the real v3 sample, which reconciles Bendigo/Ballarat/Wagga
(three different saleyard-days) under one instruction. This is the one place
in the codebase that needs a Melbourne-local trading-week calculation; kept
here rather than inlined in the service so it has one obvious owner.
"""

from datetime import date, timedelta


def trading_week_bounds(trade_date: date) -> tuple[date, date]:
    """Monday-Sunday calendar week containing `trade_date`. `trade_date` is
    already a plain `date` (no time-of-day component), so no timezone
    conversion happens here — Melbourne-local dating is enforced upstream,
    at the point `trade_date` is captured (§ "Timezone: Australia/Melbourne
    (all business deadlines and dating)")."""
    monday = trade_date - timedelta(days=trade_date.weekday())
    sunday = monday + timedelta(days=6)
    return monday, sunday
