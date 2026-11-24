"""Database connections for code that runs outside Django's request cycle (the MCP server)."""

import functools
from collections.abc import Callable
from typing import Any

from django.db import connections


def closing_connections[T](fn: Callable[..., T]) -> Callable[..., T]:
    """Run fn and close this thread's database connections, as Django does after a request.

    Outside Django's request cycle nothing else would: the MCP server runs this code in worker
    threads, and each would keep its own connections open.
    """

    @functools.wraps(fn)
    def wrapped(*args: Any, **kwargs: Any) -> T:
        try:
            return fn(*args, **kwargs)
        finally:
            connections.close_all()

    return wrapped
