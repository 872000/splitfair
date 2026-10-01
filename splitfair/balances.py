"""Balance computation: who paid what, who owes what, net per member."""

from __future__ import annotations

from .models import Expense, Member


def compute_balances(
    members: list[Member], expenses: list[Expense]
) -> dict[str, int]:
    """Return net balance per member name in cents (paid − owed).

    Positive means the member is owed money; negative means they owe money.
    The balances always sum to zero.
    """
    net: dict[str, int] = {m.name: 0 for m in members}
    id_to_name = {m.id: m.name for m in members}
    for expense in expenses:
        net[expense.payer_name] += expense.amount_cents
        for split in expense.splits:
            net[id_to_name[split.member_id]] -= split.amount_cents
    return net


def total_spent(expenses: list[Expense]) -> int:
    return sum(e.amount_cents for e in expenses)


def paid_per_member(members: list[Member], expenses: list[Expense]) -> dict[str, int]:
    paid: dict[str, int] = {m.name: 0 for m in members}
    for expense in expenses:
        paid[expense.payer_name] += expense.amount_cents
    return paid
