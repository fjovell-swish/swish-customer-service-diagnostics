"""
The MCP endpoint's authentication: `Authorization: Bearer <personal token>` (mcp_api/models.py).

/mcp doesn't go through Django's middleware (config/asgi.py), and in deployed environments it
bypasses the auth proxy: this is its only sign-in. The user is put in the ASGI scope, where the
tools read it (mcp_api/server.py).
"""

import functools
from collections.abc import Callable
from http import HTTPStatus
from typing import Any

import anyio.to_thread
from django.contrib.auth.models import User
from django.db import connections
from starlette.responses import JSONResponse
from starlette.types import ASGIApp
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

from mcp_api.models import PersonalToken

BEARER = "bearer "


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


def bearer_token(scope: Scope) -> str:
    for name, value in scope["headers"]:
        if name == b"authorization":
            header: str = value.decode("latin-1")
            if header.lower().startswith(BEARER):
                return header.split(" ", 1)[1].strip()
    return ""


class BearerTokenAuth:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = bearer_token(scope)
        user: User | None = None
        if token:
            user = await anyio.to_thread.run_sync(
                closing_connections(PersonalToken.authenticate), token
            )
        if user is None:
            response = JSONResponse(
                {
                    "error": "invalid_token",
                    "error_description": "Send a personal token, created at /tokens/, as"
                    " `Authorization: Bearer <token>`.",
                },
                status_code=HTTPStatus.UNAUTHORIZED,
                headers={"WWW-Authenticate": 'Bearer realm="swish-diagnostics"'},
            )
            await response(scope, receive, send)
            return
        scope["user"] = user
        await self.app(scope, receive, send)
