"""Proxy for the Windows Runner Agent's coordination calls into the local
control server (automation/control_server.js), which does 100% of the
real authentication (its own agent token, never Owner Basic Auth or any
other Ego OS secret) and all state/lease logic. This module never
re-implements any of that -- it only forwards a fixed, small set of known
operations and relays whatever control_server.js decides.

Mounted as a separate Starlette sub-application (see ego_os/main.py's
app.mount("/agent", agent_routes.app)) so it sits OUTSIDE the main FastAPI
app's global Owner-auth/CSRF dependencies on purpose: a Windows agent is a
machine credential (a random token control_server.js itself generated and
validates), not the human Owner, and Owner Basic Auth was never meant to
double as a long-lived machine credential.
"""

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

CONTROL_SERVER_URL = "http://127.0.0.1:4756"
_TIMEOUT = 10.0
_MAX_BODY_BYTES = 64 * 1024
# The exact, fixed set of operations control_server.js exposes under
# /api/agent/ -- never a wildcard proxy. An unlisted path is a 404 before
# any request ever reaches the control server.
_ALLOWED_OPERATIONS = {
    "register", "heartbeat", "claim",
    "report-state", "report-checkpoint", "report-result",
    "request-deploy",
}


async def _proxy(request):
    operation = request.path_params["operation"]
    if operation not in _ALLOWED_OPERATIONS:
        return JSONResponse({"error": "unknown agent operation"}, status_code=404)

    body = await request.body()
    if len(body) > _MAX_BODY_BYTES:
        return JSONResponse({"error": "request body too large"}, status_code=413)

    auth_header = request.headers.get("authorization", "")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{CONTROL_SERVER_URL}/api/agent/{operation}",
                content=body,
                headers={"Content-Type": "application/json", "Authorization": auth_header},
            )
    except httpx.HTTPError:
        return JSONResponse({"error": "runner coordinator unavailable"}, status_code=503)

    try:
        payload = resp.json() if resp.content else {}
    except ValueError:
        payload = {"error": "invalid response from runner coordinator"}
    return JSONResponse(payload, status_code=resp.status_code)


app = Starlette(routes=[Route("/{operation}", _proxy, methods=["POST"])])
