"""SQLite storage layer for SplitFair."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import Expense, Group, Member, Split, today_str

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    UNIQUE (group_id, name)
);

CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    payer_id INTEGER NOT NULL REFERENCES members(id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    date TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    description TEXT NOT NULL DEFAULT '',
    split_rule TEXT NOT NULL DEFAULT 'equal'
);

CREATE TABLE IF NOT EXISTS expense_splits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_id INTEGER NOT NULL REFERENCES expenses(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id),
    amount_cents INTEGER NOT NULL CHECK (amount_cents >= 0),
    UNIQUE (expense_id, member_id)
);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def create_group(conn: sqlite3.Connection, name: str) -> Group:
    name = name.strip()
    if not name:
        raise ValueError("group name cannot be empty")
    try:
        cur = conn.execute("INSERT INTO groups (name) VALUES (?)", (name,))
    except sqlite3.IntegrityError:
        raise ValueError(f"group {name!r} already exists")
    conn.commit()
    return get_group(conn, str(cur.lastrowid))


def get_group(conn: sqlite3.Connection, ref: str) -> Group:
    """Look up a group by id or by (case-insensitive) name."""
    ref = ref.strip()
    row = None
    if ref.isdigit():
        row = conn.execute("SELECT * FROM groups WHERE id = ?", (int(ref),)).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM groups WHERE lower(name) = lower(?)", (ref,)
        ).fetchone()
    if row is None:
        raise ValueError(f"no group found for {ref!r}")
    return Group(id=row["id"], name=row["name"], created_at=row["created_at"])


def list_groups(conn: sqlite3.Connection) -> list[Group]:
    rows = conn.execute("SELECT * FROM groups ORDER BY name").fetchall()
    return [Group(id=r["id"], name=r["name"], created_at=r["created_at"]) for r in rows]


def delete_group(conn: sqlite3.Connection, group_id: int) -> None:
    conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
    conn.commit()


def add_member(conn: sqlite3.Connection, group_id: int, name: str) -> Member:
    name = name.strip()
    if not name:
        raise ValueError("member name cannot be empty")
    try:
        cur = conn.execute(
            "INSERT INTO members (group_id, name) VALUES (?, ?)", (group_id, name)
        )
    except sqlite3.IntegrityError:
        raise ValueError(f"member {name!r} is already in this group")
    conn.commit()
    return Member(id=cur.lastrowid, group_id=group_id, name=name)


def get_member(conn: sqlite3.Connection, group_id: int, ref: str) -> Member:
    ref = ref.strip()
    row = None
    if ref.isdigit():
        row = conn.execute(
            "SELECT * FROM members WHERE group_id = ? AND id = ?", (group_id, int(ref))
        ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM members WHERE group_id = ? AND lower(name) = lower(?)",
            (group_id, ref),
        ).fetchone()
    if row is None:
        raise ValueError(f"no member {ref!r} in this group")
    return Member(id=row["id"], group_id=row["group_id"], name=row["name"])


def list_members(conn: sqlite3.Connection, group_id: int) -> list[Member]:
    rows = conn.execute(
        "SELECT * FROM members WHERE group_id = ? ORDER BY name", (group_id,)
    ).fetchall()
    return [Member(id=r["id"], group_id=r["group_id"], name=r["name"]) for r in rows]


def add_expense(
    conn: sqlite3.Connection,
    group_id: int,
    payer_id: int,
    amount_cents: int,
    split_rule: str,
    splits: list[tuple[int, int]],
    date: str | None = None,
    category: str = "other",
    description: str = "",
) -> Expense:
    """Insert an expense with pre-computed per-member splits (member_id, cents)."""
    if amount_cents <= 0:
        raise ValueError("expense amount must be positive")
    if not splits:
        raise ValueError("expense must have at least one split")
    total_split = sum(c for _, c in splits)
    if total_split != amount_cents:
        raise ValueError(
            f"splits total {total_split}c does not match expense {amount_cents}c"
        )
    cur = conn.execute(
        """INSERT INTO expenses
           (group_id, payer_id, amount_cents, date, category, description, split_rule)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            group_id,
            payer_id,
            amount_cents,
            date or today_str(),
            category.strip() or "other",
            description.strip(),
            split_rule,
        ),
    )
    expense_id = cur.lastrowid
    conn.executemany(
        "INSERT INTO expense_splits (expense_id, member_id, amount_cents) VALUES (?, ?, ?)",
        [(expense_id, mid, cents) for mid, cents in splits],
    )
    conn.commit()
    return get_expense(conn, expense_id)


def get_expense(conn: sqlite3.Connection, expense_id: int) -> Expense:
    row = conn.execute(
        """SELECT e.*, m.name AS payer_name FROM expenses e
           JOIN members m ON m.id = e.payer_id WHERE e.id = ?""",
        (expense_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"no expense with id {expense_id}")
    splits = [
        Split(member_id=r["member_id"], member_name=r["member_name"], amount_cents=r["amount_cents"])
        for r in conn.execute(
            """SELECT s.member_id, s.amount_cents, m.name AS member_name
               FROM expense_splits s JOIN members m ON m.id = s.member_id
               WHERE s.expense_id = ? ORDER BY m.name""",
            (expense_id,),
        ).fetchall()
    ]
    return Expense(
        id=row["id"],
        group_id=row["group_id"],
        payer_id=row["payer_id"],
        payer_name=row["payer_name"],
        amount_cents=row["amount_cents"],
        date=row["date"],
        category=row["category"],
        description=row["description"],
        split_rule=row["split_rule"],
        splits=splits,
    )


def list_expenses(conn: sqlite3.Connection, group_id: int) -> list[Expense]:
    rows = conn.execute(
        "SELECT id FROM expenses WHERE group_id = ? ORDER BY date, id", (group_id,)
    ).fetchall()
    return [get_expense(conn, r["id"]) for r in rows]


# ---------------------------------------------------------------------------
# Split-rule calculators: turn a rule + inputs into per-member cent amounts.
# ---------------------------------------------------------------------------

def split_equal(amount_cents: int, member_ids: list[int]) -> list[tuple[int, int]]:
    """Split evenly; leftover pennies go to the first members in order."""
    if not member_ids:
        raise ValueError("equal split needs at least one member")
    per, remainder = divmod(amount_cents, len(member_ids))
    return [
        (mid, per + (1 if i < remainder else 0))
        for i, mid in enumerate(member_ids)
    ]


def split_shares(amount_cents: int, shares: list[tuple[int, float]]) -> list[tuple[int, int]]:
    """Split proportionally to weights; rounding pennies go to largest shares."""
    if not shares:
        raise ValueError("shares split needs at least one member")
    total = sum(w for _, w in shares)
    if total <= 0:
        raise ValueError("share weights must be positive")
    exact = [(mid, amount_cents * w / total) for mid, w in shares]
    floored = [(mid, int(x)) for mid, x in exact]
    assigned = sum(c for _, c in floored)
    leftover = amount_cents - assigned
    # hand leftover pennies to the largest fractional remainders
    order = sorted(
        range(len(exact)), key=lambda i: exact[i][1] - floored[i][1], reverse=True
    )
    result = [list(pair) for pair in floored]
    for i in order[:leftover]:
        result[i][1] += 1
    return [(mid, cents) for mid, cents in result]


def split_exact(amounts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Each member owes an exact amount; every amount must be non-negative."""
    if not amounts:
        raise ValueError("exact split needs at least one member")
    for _, cents in amounts:
        if cents < 0:
            raise ValueError("exact split amounts cannot be negative")
    return list(amounts)
