"""Read application metrics in tests (single-process registry)."""

from contextlib import contextmanager
from types import SimpleNamespace

from prometheus_client import REGISTRY


def sample(name, **labels):
    """The current value of sample *name* with *labels*; 0.0 when it does not exist yet."""
    return REGISTRY.get_sample_value(name, labels) or 0.0


@contextmanager
def delta(name, **labels):
    """How much sample *name* moved during the block: ``with delta(...) as d: ...; d.value``."""
    result = SimpleNamespace(value=None)
    before = sample(name, **labels)
    yield result
    result.value = sample(name, **labels) - before
