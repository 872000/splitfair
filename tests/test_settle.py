"""Tests for the min-cash-flow settlement algorithm."""

import random

from splitfair.settle import Transfer, apply_transfers, min_cash_flow


def test_simple_two_person():
    transfers = min_cash_flow({"A": 5000, "B": -5000})
    assert transfers == [Transfer("B", "A", 5000)]


def test_already_settled():
    assert min_cash_flow({"A": 0, "B": 0, "C": 0}) == []


def test_chain_collapses_to_fewer_transfers():
    # A owes B owes C owes A style chains should collapse, not chain.
    net = {"A": 3000, "B": 1000, "C": -4000}
    transfers = min_cash_flow(net)
    assert len(transfers) == 2  # C->A 3000, C->B 1000 (not 3 hops)
    assert apply_transfers(net, transfers) == {"A": 0, "B": 0, "C": 0}


def test_never_more_than_n_minus_1_transfers():
    rng = random.Random(42)
    for _ in range(200):
        n = rng.randint(2, 8)
        vals = [rng.randint(-10000, 10000) for _ in range(n - 1)]
        vals.append(-sum(vals))  # force zero-sum
        net = {f"P{i}": v for i, v in enumerate(vals)}
        transfers = min_cash_flow(net)
        assert len(transfers) <= n - 1
        remaining = apply_transfers(net, transfers)
        assert all(v == 0 for v in remaining.values())


def test_greedy_matches_biggest_first():
    net = {"Rich": 9000, "Mid": 1000, "Poor1": -5000, "Poor2": -5000}
    transfers = min_cash_flow(net)
    # biggest debtor pairs with biggest creditor first
    assert transfers[0] == Transfer("Poor1", "Rich", 5000)
    assert apply_transfers(net, transfers) == {k: 0 for k in net}


def test_transfer_amounts_positive():
    net = {"A": 123, "B": -123}
    for t in min_cash_flow(net):
        assert t.amount_cents > 0


def test_single_creditor_many_debtors():
    net = {"A": 6000, "B": -2000, "C": -2000, "D": -2000}
    transfers = min_cash_flow(net)
    assert len(transfers) == 3
    assert all(t.to_member == "A" for t in transfers)


def test_rejects_unbalanced_net():
    import pytest

    with pytest.raises(ValueError, match="sum to zero"):
        min_cash_flow({"A": 5000, "B": -4999})


def test_transfer_rejects_nonpositive_amounts():
    import pytest

    with pytest.raises(ValueError, match="positive"):
        Transfer("A", "B", 0)
    with pytest.raises(ValueError, match="positive"):
        Transfer("A", "B", -250)
