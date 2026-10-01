"""SplitFair command-line interface."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

from . import __version__
from .balances import compute_balances
from .db import (
    add_expense,
    add_member,
    connect,
    create_group,
    delete_group,
    get_group,
    get_member,
    list_expenses,
    list_groups,
    list_members,
    split_equal,
    split_exact,
    split_shares,
)
from .models import fmt_money, parse_amount
from .report import render_settlement_png, render_text_report, save_text_report
from .settle import min_cash_flow

DEFAULT_DB = Path.home() / ".splitfair" / "splitfair.db"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _db(args) -> sqlite3.Connection:
    return connect(args.db)


def _group_and_members(conn, ref):
    group = get_group(conn, ref)
    members = list_members(conn, group.id)
    return group, members


def _parse_name_amount_pairs(text: str) -> list[tuple[str, str]]:
    """Parse 'Parth:2,Maya:1' or 'Parth:40.00,Maya:80.00' into (name, value) pairs."""
    pairs = []
    for chunk in text.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise ValueError(f"expected 'name:value', got {chunk!r}")
        name, _, value = chunk.partition(":")
        name, value = name.strip(), value.strip()
        if not name or not value:
            raise ValueError(f"expected 'name:value', got {chunk!r}")
        pairs.append((name, value))
    if not pairs:
        raise ValueError("no name:value pairs provided")
    return pairs


# ---------------------------------------------------------------------------
# subcommands
# ---------------------------------------------------------------------------

def cmd_group_create(args) -> int:
    conn = _db(args)
    group = create_group(conn, args.name)
    print(f"Created group #{group.id}: {group.name}")
    return 0


def cmd_group_list(args) -> int:
    conn = _db(args)
    groups = list_groups(conn)
    if not groups:
        print("No groups yet. Create one with: splitfair group create \"Roommates\"")
        return 0
    for g in groups:
        n = len(list_members(conn, g.id))
        print(f"#{g.id}  {g.name}  ({n} member(s))")
    return 0


def cmd_member_add(args) -> int:
    conn = _db(args)
    group, _ = _group_and_members(conn, args.group)
    member = add_member(conn, group.id, args.name)
    print(f"Added {member.name} to group '{group.name}'")
    return 0


def cmd_expense_add(args) -> int:
    conn = _db(args)
    group, members = _group_and_members(conn, args.group)
    if not members:
        print("error: add members to the group first", file=sys.stderr)
        return 1
    by_name = {m.name.lower(): m for m in members}

    def resolve(name: str):
        member = by_name.get(name.strip().lower())
        if member is None:
            print(f"error: {name!r} is not a member of '{group.name}'", file=sys.stderr)
            sys.exit(1)
        return member

    payer = resolve(args.payer)
    try:
        amount_cents = parse_amount(args.amount)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    if amount_cents <= 0:
        print("error: amount must be positive", file=sys.stderr)
        return 1

    rule = args.split
    try:
        if rule == "equal":
            who = [resolve(n) for n in args.members.split(",")] if args.members else members
            splits = split_equal(amount_cents, [m.id for m in who])
        elif rule == "shares":
            if not args.shares:
                print("error: --shares is required for split=shares (e.g. --shares Parth:2,Maya:1)",
                      file=sys.stderr)
                return 1
            pairs = _parse_name_amount_pairs(args.shares)
            shares = [(resolve(n).id, float(w)) for n, w in pairs]
            splits = split_shares(amount_cents, shares)
        elif rule == "exact":
            if not args.amounts:
                print("error: --amounts is required for split=exact (e.g. --amounts Parth:40.00,Maya:80.00)",
                      file=sys.stderr)
                return 1
            pairs = _parse_name_amount_pairs(args.amounts)
            amounts = [(resolve(n).id, parse_amount(v)) for n, v in pairs]
            splits = split_exact(amounts)
        else:
            print(f"error: unknown split rule {rule!r}", file=sys.stderr)
            return 1
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    expense = add_expense(
        conn,
        group.id,
        payer.id,
        amount_cents,
        rule,
        splits,
        date=args.date or date.today().isoformat(),
        category=args.category,
        description=args.description,
    )
    print(f"Added expense #{expense.id}: {payer.name} paid {fmt_money(amount_cents)} "
          f"({rule} split, {args.category})")
    return 0


def cmd_balances(args) -> int:
    conn = _db(args)
    group, members = _group_and_members(conn, args.group)
    expenses = list_expenses(conn, group.id)
    net = compute_balances(members, expenses)
    print(f"Balances for '{group.name}':")
    for m in members:
        bal = net[m.name]
        if bal > 0:
            state = f"is owed {fmt_money(bal)}"
        elif bal < 0:
            state = f"owes {fmt_money(-bal)}"
        else:
            state = "settled up"
        print(f"  {m.name:<14} {fmt_money(bal):>10}   {state}")
    return 0


def cmd_settle(args) -> int:
    conn = _db(args)
    group, members = _group_and_members(conn, args.group)
    expenses = list_expenses(conn, group.id)
    net = compute_balances(members, expenses)
    transfers = min_cash_flow(net)

    text = render_text_report(group, members, expenses, net, transfers)
    print(text)

    out = save_text_report(text, args.out)
    print(f"Report saved to {out}")
    if args.png:
        png = render_settlement_png(group.name, net, transfers, args.png)
        print(f"Chart saved to {png}")
    return 0


DEMO_GROUP = "Maple House"


def seed_demo(conn) -> tuple:
    """Seed a realistic roommate scenario. Returns (group, members, expenses)."""
    # start fresh so `demo` is idempotent
    try:
        old = get_group(conn, DEMO_GROUP)
        delete_group(conn, old.id)
    except ValueError:
        pass

    group = create_group(conn, DEMO_GROUP)
    names = ["Parth", "Maya", "Jordan", "Priya"]
    members = [add_member(conn, group.id, n) for n in names]
    by_name = {m.name: m for m in members}
    all_ids = [m.id for m in members]

    demo_expenses = [
        # (payer, amount, date, category, description, rule, rule_args)
        ("Parth", "2400.00", "2026-10-01", "rent", "October rent", "equal", None),
        ("Maya", "186.40", "2026-09-27", "groceries", "Costco run", "equal", None),
        ("Jordan", "132.18", "2026-09-25", "utilities", "Hydro bill", "equal", None),
        ("Priya", "89.99", "2026-09-20", "utilities", "Internet", "equal", None),
        ("Parth", "64.50", "2026-09-28", "dining", "Pizza night (Parth ate double)",
         "shares", {"Parth": 2, "Maya": 1, "Jordan": 1, "Priya": 1}),
        ("Maya", "42.75", "2026-09-22", "household", "Cleaning supplies", "equal", None),
        ("Jordan", "240.00", "2026-09-18", "entertainment", "Concert tickets (Jordan + Priya)",
         "exact", {"Jordan": "120.00", "Priya": "120.00"}),
        ("Priya", "23.60", "2026-09-30", "dining", "Coffee run (Priya + Maya)",
         "shares", {"Priya": 1, "Maya": 1}),
    ]

    expenses = []
    for payer, amount, day, category, desc, rule, rule_args in demo_expenses:
        amount_cents = parse_amount(amount)
        if rule == "equal":
            splits = split_equal(amount_cents, all_ids)
        elif rule == "shares":
            splits = split_shares(
                amount_cents, [(by_name[n].id, w) for n, w in rule_args.items()]
            )
        elif rule == "exact":
            splits = split_exact(
                [(by_name[n].id, parse_amount(v)) for n, v in rule_args.items()]
            )
        expenses.append(
            add_expense(conn, group.id, by_name[payer].id, amount_cents, rule,
                        splits, date=day, category=category, description=desc)
        )
    return group, members, expenses


def cmd_demo(args) -> int:
    conn = _db(args)
    group, members, expenses = seed_demo(conn)
    net = compute_balances(members, expenses)
    transfers = min_cash_flow(net)
    text = render_text_report(group, members, expenses, net, transfers)
    print(text)
    out = save_text_report(text, args.out)
    print(f"Report saved to {out}")
    if args.png:
        png = render_settlement_png(group.name, net, transfers, args.png)
        print(f"Chart saved to {png}")
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="splitfair",
        description="Split expenses with friends and settle up with the fewest transfers.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument("--db", default=str(DEFAULT_DB), help="path to the SQLite database")

    sub = p.add_subparsers(dest="command", required=True)

    g = sub.add_parser("group", help="manage groups")
    gsub = g.add_subparsers(dest="group_cmd", required=True)
    gc = gsub.add_parser("create", help="create a group")
    gc.add_argument("name", help="group name")
    gc.set_defaults(func=cmd_group_create)
    gl = gsub.add_parser("list", help="list groups")
    gl.set_defaults(func=cmd_group_list)

    m = sub.add_parser("member", help="manage members")
    msub = m.add_subparsers(dest="member_cmd", required=True)
    ma = msub.add_parser("add", help="add a member to a group")
    ma.add_argument("group", help="group id or name")
    ma.add_argument("--name", required=True, help="member name")
    ma.set_defaults(func=cmd_member_add)

    e = sub.add_parser("expense", help="manage expenses")
    esub = e.add_subparsers(dest="expense_cmd", required=True)
    ea = esub.add_parser("add", help="add an expense")
    ea.add_argument("group", help="group id or name")
    ea.add_argument("--payer", required=True, help="who paid")
    ea.add_argument("--amount", required=True, help="amount, e.g. 120.00")
    ea.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    ea.add_argument("--category", default="other", help="e.g. groceries, rent, utilities")
    ea.add_argument("--description", default="", help="what it was for")
    ea.add_argument("--split", choices=["equal", "shares", "exact"], default="equal")
    ea.add_argument("--members", default=None, help="comma-separated members for equal split")
    ea.add_argument("--shares", default=None, help="e.g. 'Parth:2,Maya:1'")
    ea.add_argument("--amounts", default=None, help="e.g. 'Parth:40.00,Maya:80.00'")
    ea.set_defaults(func=cmd_expense_add)

    b = sub.add_parser("balances", help="show net balance per member")
    b.add_argument("group", help="group id or name")
    b.set_defaults(func=cmd_balances)

    s = sub.add_parser("settle", help="compute the fewest transfers to settle up")
    s.add_argument("group", help="group id or name")
    s.add_argument("--out", default="settlement-report.txt", help="where to save the report")
    s.add_argument("--png", default=None, help="also render a PNG chart here")
    s.set_defaults(func=cmd_settle)

    d = sub.add_parser("demo", help="seed a realistic roommate scenario and settle it")
    d.add_argument("--out", default="settlement-report.txt", help="where to save the report")
    d.add_argument("--png", default=None, help="also render a PNG chart here")
    d.set_defaults(func=cmd_demo)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
