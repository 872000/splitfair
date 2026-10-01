"""End-to-end CLI tests: group -> members -> expenses -> settle."""

import sqlite3

import pytest

from splitfair.cli import main
from splitfair.db import connect, get_group, list_expenses, list_members
from splitfair.report import render_settlement_png, render_text_report


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "cli.db")


def run(db_path, *argv, capsys=None):
    code = main(["--db", db_path, *argv])
    assert code == 0
    if capsys is not None:
        return capsys.readouterr().out
    return ""


def test_full_cli_flow(db_path, capsys):
    run(db_path, "group", "create", "Cabin Trip")
    run(db_path, "member", "add", "Cabin Trip", "--name", "Parth")
    run(db_path, "member", "add", "Cabin Trip", "--name", "Maya")
    run(db_path, "expense", "add", "Cabin Trip", "--payer", "Parth",
        "--amount", "200.00", "--category", "rent", "--description", "cabin")
    out = run(db_path, "balances", "Cabin Trip", capsys=capsys)
    assert "Parth" in out and "Maya" in out
    out = run(db_path, "settle", "Cabin Trip", "--out", str(db_path) + ".txt", capsys=capsys)
    assert "Maya → Parth" in out
    assert "$100.00" in out


def test_expense_split_variants(db_path, capsys):
    run(db_path, "group", "create", "G")
    for name in ("A", "B", "C"):
        run(db_path, "member", "add", "G", "--name", name)
    run(db_path, "expense", "add", "G", "--payer", "A", "--amount", "90.00",
        "--split", "equal")
    run(db_path, "expense", "add", "G", "--payer", "B", "--amount", "100.00",
        "--split", "shares", "--shares", "A:1,B:3")
    run(db_path, "expense", "add", "G", "--payer", "C", "--amount", "60.00",
        "--split", "exact", "--amounts", "A:20.00,C:40.00")
    conn = connect(db_path)
    expenses = list_expenses(conn, get_group(conn, "G").id)
    assert len(expenses) == 3
    assert all(sum(s.amount_cents for s in e.splits) == e.amount_cents for e in expenses)
    out = run(db_path, "settle", "G", "--out", str(db_path) + ".txt", capsys=capsys)
    assert "SETTLEMENT PLAN" in out


def test_demo_seeds_and_settles(db_path, tmp_path, capsys):
    png = tmp_path / "demo.png"
    out = run(db_path, "demo", "--out", str(tmp_path / "demo.txt"),
              "--png", str(png), capsys=capsys)
    assert "Maple House" in out
    assert "SETTLEMENT PLAN" in out
    assert png.exists() and png.stat().st_size > 0
    conn = connect(db_path)
    group = get_group(conn, "Maple House")
    assert len(list_members(conn, group.id)) == 4
    assert len(list_expenses(conn, group.id)) == 8
    # demo is idempotent: running twice keeps exactly one demo group
    run(db_path, "demo", "--out", str(tmp_path / "demo.txt"))
    conn2 = connect(db_path)
    assert len(list_expenses(conn2, get_group(conn2, "Maple House").id)) == 8


def test_report_renders_png(tmp_path):
    from splitfair.balances import compute_balances  # noqa
    net = {"Parth": 6000, "Maya": -2500, "Jordan": -3500}
    from splitfair.settle import min_cash_flow
    transfers = min_cash_flow(net)
    png = render_settlement_png("Test Group", net, transfers, tmp_path / "r.png")
    assert png.exists()


def test_text_report_contents():
    from splitfair.models import Expense, Group, Member, Split
    group = Group(id=1, name="G", created_at="2026-10-01")
    members = [Member(1, 1, "A"), Member(2, 1, "B")]
    expenses = [Expense(1, 1, 1, "A", 10000, "2026-10-01", "rent", "", "equal",
                        [Split(1, "A", 5000), Split(2, "B", 5000)])]
    net = {"A": 5000, "B": -5000}
    from splitfair.settle import min_cash_flow
    text = render_text_report(group, members, expenses, net, min_cash_flow(net))
    assert "SPLITFAIR SETTLEMENT REPORT" in text
    assert "B → A: $50.00" in text


def test_unknown_group_errors(db_path, capsys):
    code = main(["--db", db_path, "balances", "Nope"])
    assert code == 1
