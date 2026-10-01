"""SplitFair — roommate expense splitter with min-cash-flow settlement.

Split expenses with friends, then settle up with the *fewest* transfers
possible using a greedy min-cash-flow algorithm.
"""

__version__ = "1.0.0"
__author__ = "Parth (872000)"

from .settle import Transfer, min_cash_flow  # noqa: F401
