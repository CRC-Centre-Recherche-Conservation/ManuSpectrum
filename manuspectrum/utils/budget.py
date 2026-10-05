"""Per-block deadline shared by every outbound call made inside it.

``upstream_budget(seconds)`` opens a budget for the current context (request
threads and any pool task that copies the context). Outbound helpers consult
it through :func:`current_budget`: the Biblissima proxy (``_bib_request``) and
``utils.http.safe_fetch``. With no budget open they behave as if this module
did not exist.
"""

import contextvars
import time
from contextlib import contextmanager


class BudgetSpent(Exception):
    """The budget's deadline passed before this call could start."""


class UpstreamBudget:
    """Backstop deadline of one block's outbound calls, the hosts found down,
    and the first failure met."""

    def __init__(self, seconds):
        self.deadline = time.monotonic() + seconds
        self.down = set()
        self.error = None

    def record(self, exc, host=None):
        if self.error is None:
            self.error = exc
        if host is not None:
            self.down.add(host)

    def left(self):
        """Seconds before the deadline; zero or negative once spent."""
        return self.deadline - time.monotonic()

    def spent(self):
        return self.left() <= 0


budget_var = contextvars.ContextVar("upstream_budget", default=None)


def current_budget():
    """The budget open in this context, or ``None``."""
    return budget_var.get()


def capped_timeout(timeout, left, connect_cap=None):
    """``(connect, read)`` of *timeout* (a number or a pair), each at most
    *left*; the connect also at most *connect_cap* when one is given."""
    connect, read = timeout if isinstance(timeout, tuple) else (timeout, timeout)
    connect = min(connect, left)
    if connect_cap is not None:
        connect = min(connect, connect_cap)
    return connect, min(read, left)


@contextmanager
def upstream_budget(seconds):
    """Open a budget of *seconds* for every outbound call made in this block.

    Yields the :class:`UpstreamBudget`. Budgets do not nest: an inner block
    replaces the outer one for its duration.
    """
    budget = UpstreamBudget(seconds)
    token = budget_var.set(budget)
    try:
        yield budget
    finally:
        budget_var.reset(token)
