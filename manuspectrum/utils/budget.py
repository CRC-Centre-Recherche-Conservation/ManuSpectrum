"""Per-block deadline shared by every outbound call made inside it.

``upstream_budget(seconds)`` opens a budget for the current context (request
threads and any pool task that copies the context). Outbound helpers consult
it through :func:`current_budget`: the Biblissima proxy (``_bib_request``) and
``utils.http.safe_fetch``. With no budget open they behave as if this module
did not exist.

A budget may also cap the connect timeout of each call and carry a
:class:`HostBreaker`, which remembers across requests and processes the hosts
that did not accept a connection.
"""

import contextvars
import time
from contextlib import contextmanager

from django.core.cache import cache

from manuspectrum.observability import metrics


class BudgetSpent(Exception):
    """The budget's deadline passed before this call could start."""


class UpstreamBudget:
    """Backstop deadline of one block's outbound calls, the hosts found down,
    and the first failure met."""

    def __init__(self, seconds, connect_cap=None, breaker=None):
        self.deadline = time.monotonic() + seconds
        self.down = set()
        self.error = None
        self.connect_cap = connect_cap
        self.breaker = breaker

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


class HostBreaker:
    """Origins (``host:port``) that refused or timed out a connection, skipped for ``ttl()`` seconds.

    *ttl* is a callable read at each trip, so a setting can drive it. The
    hosts are kept in the default cache under *prefix*: every thread and
    process sees a host as soon as one call trips it, and nothing is held in
    the process.
    """

    def __init__(self, prefix, ttl):
        self.prefix = prefix
        self.ttl = ttl

    def _key(self, origin):
        return f"{self.prefix}:{origin.lower()}"

    def is_down(self, origin):
        return bool(cache.get(self._key(origin)))

    def trip(self, origin):
        cache.set(self._key(origin), True, self.ttl())


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
def upstream_budget(seconds, kind="read", connect_cap=None, breaker=None):
    """Open a budget of *seconds* for every outbound call made in this block.

    Yields the :class:`UpstreamBudget`. Budgets do not nest: an inner block
    replaces the outer one for its duration. A block that ends with its
    deadline passed is counted in ``manuspectrum_upstream_budget_spent_total``
    under *kind* (``read`` for an interactive view, ``write`` for a create).
    *connect_cap* bounds the connect timeout of each call; *breaker*
    (:class:`HostBreaker`) skips the hosts it holds and records those that
    fail to connect.
    """
    budget = UpstreamBudget(seconds, connect_cap=connect_cap, breaker=breaker)
    token = budget_var.set(budget)
    try:
        yield budget
    finally:
        budget_var.reset(token)
        if budget.spent():
            metrics.UPSTREAM_BUDGET_SPENT.labels(
                kind=metrics.bounded(kind, metrics.BUDGET_KINDS)
            ).inc()
