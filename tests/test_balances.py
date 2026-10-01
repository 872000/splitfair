"""Tests for balance computation and split-rule calculators."""

import sqlite3

import pytest

from splitfair.balances import compute_balances
from splitfair.db import (
    add_expense,
    add_member,
    connect,
    create_group,
    get_expense,
    list_expenses,
    list_members,
    split_equal,
    split_exact,
    split_shares,
)
from splitfair.models import parse_amount


@pytest.fixture()
def conn(tmp_path):
    c = connect(tmp_path / "test.db")
    yield c
    c.close()


@pytest.fixture()
def roommates(conn):
    group = create_group(conn, "Roommates")
    members = [add_member(conn, group.id, n) for n in ("Parth", "Maya", "Jordan")]
    return group, members


def _ids(members):
    return {m.name: m.id for m in members}


def test_equal_split_pennies(conn, roommates):
    group, members = roommates
    ids = _ids(members)
    # $10.00 split 3 ways -> 334, 333, 333
    splits = split_equal(1000, [ids["Parth"], ids["Maya"], ids["Jordan"]])
    assert sum(c for _, c in splits) == 1000
    assert sorted(c for _, c in splits) == [333, 333, 334]


def test_shares_split_proportional(conn):
    splits = split_shares(1000, [(1, 2.0), (2, 1.0), (3, 1.0)])
    by_id = dict(splits)
    assert sum(by_id.values()) == 1000
    assert by_id[1] == 500
    assert by_id[2] == 250
    assert by_id[3] == 250


def test_shares_split_rounding_keeps_total():
    # $10 split 1:1:1 -> leftover pennies distributed, total preserved
    splits = split_shares(1000, [(1, 1), (2, 1), (3, 1)])
    assert sum(c for _, c in splits) == 1000


def test_exact_split_must_match_total(conn, roommates):
    group, members = roommates
    ids = _ids(members)
    with pytest.raises(ValueError, match="does not match"):
        add_expense(conn, group.id, ids["Parth"], 1000, "exact",
                    [(ids["Parth"], 600), (ids["Maya"], 300)])  # 900 != 1000


def test_balances_sum_to_zero(conn, roommates):
    group, members = roommates
    ids = _ids(members)
    add_expense(conn, group.id, ids["Parth"], 9000, "equal",
                split_equal(9000, [ids["Parth"], ids["Maya"], ids["Jordan"]]),
                date="2026-09-01", category="rent", description="rent")
    add_expense(conn, group.id, ids["Maya"], 1200, "exact",
                split_exact([(ids["Maya"], 600), (ids["Jordan"], 600)]),
                date="2026-09-02", category="dining", description="lunch")
    expenses = list_expenses(conn, group.id)
    net = compute_balances(list_members(conn, group.id), expenses)
    assert sum(net.values()) == 0
    # Parth paid 9000, owes 3000 -> +6000; Maya paid 1200, owes 3600 -> -2400
    assert net["Parth"] == 6000
    assert net["Maya"] == -2400
    assert net["Jordan"] == -3600


def test_parse_amount():
    assert parse_amount("120.00") == 12000
    assert parse_amount("45") == 4500
    assert parse_amount("$1,234.56") == 123456
    assert parse_amount("9.9") == 990
    with pytest.raises(ValueError):
        parse_amount("abc")


def test_expense_roundtrip(conn, roommates):
    group, members = roommates
    ids = _ids(members)
    exp = add_expense(conn, group.id, ids["Jordan"], 5150, "shares",
                      split_shares(5150, [(ids["Parth"], 2), (ids["Jordan"], 1)]),
                      date="2026-09-05", category="groceries", description="Costco")
    fetched = get_expense(conn, exp.id)
    assert fetched.payer_name == "Jordan"
    assert fetched.amount_cents == 5150
    assert sum(s.amount_cents for s in fetched.splits) == 5150
    assert fetched.split_rule == "shares"


def test_duplicate_member_rejected(conn, roommates):
    group, _ = roommates
    with pytest.raises(ValueError, match="already in this group"):
        add_member(conn, group.id, "Parth")
