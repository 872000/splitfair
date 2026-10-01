"""Domain models and money helpers for SplitFair.

All money is stored and computed in integer cents to avoid floating-point
rounding errors. Conversion to/from display strings happens at the edges.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Group:
    id: int
    name: str
    created_at: str


@dataclass
class Member:
    id: int
    group_id: int
    name: str


@dataclass
class Split:
    """One member's share of an expense, in cents."""

    member_id: int
    member_name: str
    amount_cents: int


@dataclass
class Expense:
    id: int
    group_id: int
    payer_id: int
    payer_name: str
    amount_cents: int
    date: str
    category: str
    description: str
    split_rule: str  # "equal" | "shares" | "exact"
    splits: list[Split] = field(default_factory=list)


def parse_amount(text: str) -> int:
    """Parse a dollar string like '120.00' or '45' into integer cents."""
    text = text.strip().replace("$", "").replace(",", "")
    if not text:
        raise ValueError("amount is empty")
    negative = text.startswith("-")
    if negative:
        text = text[1:]
    if "." in text:
        dollars, _, cents = text.partition(".")
        cents = (cents + "00")[:2]
    else:
        dollars, cents = text, "00"
    if not dollars.isdigit() or not cents.isdigit():
        raise ValueError(f"invalid amount: {text!r}")
    total = int(dollars) * 100 + int(cents)
    return -total if negative else total


def fmt_money(cents: int) -> str:
    """Format integer cents as a dollar string, e.g. -$1,234.56."""
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}${cents // 100:,}.{cents % 100:02d}"


def today_str() -> str:
    return date.today().isoformat()
