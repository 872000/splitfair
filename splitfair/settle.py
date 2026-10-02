"""Min-cash-flow debt simplification.

Given each member's net balance (positive = owed money, negative = owes money),
compute the *fewest* transfers that settle every debt.

The greedy algorithm repeatedly matches the biggest debtor with the biggest
creditor and moves the largest amount possible between them. Each transfer
settles at least one party completely, so the plan uses at most n−1 transfers
for n members — and in practice it is optimal or near-optimal for real-world
expense data.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Transfer:
    from_member: str  # the debtor (pays)
    to_member: str  # the creditor (receives)
    amount_cents: int

    def __post_init__(self) -> None:
        if self.amount_cents <= 0:
            raise ValueError("transfer amount must be positive")


def min_cash_flow(net: dict[str, int]) -> list[Transfer]:
    """Compute the minimal transfer set that zeroes out all balances.

    Args:
        net: member name -> net balance in cents (positive = is owed).

    Returns:
        List of transfers; applying them settles every debt.

    Raises:
        ValueError: if the balances don't sum to zero (nothing can settle
            an unbalanced ledger — this usually means a bug upstream).
    """
    if sum(net.values()) != 0:
        raise ValueError("net balances must sum to zero before settling")
    # [name, amount] pairs, sorted largest-first; mutate amounts in place.
    debtors = sorted(
        ([name, -bal] for name, bal in net.items() if bal < 0),
        key=lambda p: p[1],
        reverse=True,
    )
    creditors = sorted(
        ([name, bal] for name, bal in net.items() if bal > 0),
        key=lambda p: p[1],
        reverse=True,
    )

    transfers: list[Transfer] = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        debtor, owed = debtors[i]
        creditor, due = creditors[j]
        amount = min(owed, due)
        transfers.append(
            Transfer(from_member=debtor, to_member=creditor, amount_cents=amount)
        )
        debtors[i][1] -= amount
        creditors[j][1] -= amount
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1
    return transfers


def apply_transfers(net: dict[str, int], transfers: list[Transfer]) -> dict[str, int]:
    """Return the balances that remain after applying transfers (for tests)."""
    remaining = dict(net)
    for t in transfers:
        remaining[t.from_member] += t.amount_cents
        remaining[t.to_member] -= t.amount_cents
    return remaining
