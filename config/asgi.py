"""
The app on ASGI: Django for every page, and the MCP API at /mcp (mcp_api/server.py), in one
process. gunicorn runs it with uvicorn workers (docker/entrypoint.sh, `web`).

/mcp skips Django's middleware: it has its own sign-in, personal tokens (mcp_api/auth.py).
Lifespan events go to the MCP app, whose session manager needs them; Django doesn't take any.
"""

import os
from typing import cast

from django.core.asgi import get_asgi_application
from starlette.types import ASGIApp
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
# Typed as any ASGI app: Django's own annotations are narrower than ASGI's.
django_application = cast(ASGIApp, get_asgi_application())

# Only once Django is set up: the tools use its models.
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402

from mcp_api.auth import BearerTokenAuth  # noqa: E402
from mcp_api.server import server  # noqa: E402

MCP_PATH = "/mcp"


def build() -> ASGIApp:
    """The app. The MCP app's session manager runs once (lifespan): one per app built."""
    mcp_application = BearerTokenAuth(
        server.streamable_http_app(
            streamable_http_path=MCP_PATH,
            # No protocol sessions to keep: any replica answers any request.
            stateless_http=True,
            json_response=True,
            # DNS rebinding protection is for servers a browser can reach with its cookies; this
            # one only takes bearer tokens, and the hosts are Django's ALLOWED_HOSTS' business.
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
    )

    async def application(scope: Scope, receive: Receive, send: Send) -> None:
        path: str = scope.get("path", "")
        if scope["type"] == "lifespan" or path == MCP_PATH or path.startswith(MCP_PATH + "/"):
            await mcp_application(scope, receive, send)
        else:
            await django_application(scope, receive, send)

    return application


application = build()
