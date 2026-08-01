import hashlib
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

router = APIRouter()

# --- CHANGE THIS to your registered exam email ---
REGISTERED_EMAIL = "24f3000075@ds.study.iitm.ac.in"


def _solve(challenge: str) -> str:
    email = REGISTERED_EMAIL.strip().lower()
    digest = hashlib.sha256(f"{challenge}:{email}".encode("utf-8")).hexdigest()
    return digest[:16]


TOOLS = [
    {
        "name": "solve_challenge",
        "description": "Solves the exam header challenge using the server's registered email.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    }
]


def _rpc_result(id_, result):
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _rpc_error(id_, code, message):
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


@router.post("/mcp")
async def mcp_endpoint(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_rpc_error(None, -32700, "Parse error"), status_code=400)

    messages = body if isinstance(body, list) else [body]
    responses = []

    for msg in messages:
        method = msg.get("method")
        msg_id = msg.get("id")
        is_notification = "id" not in msg

        if method == "initialize":
            session_id = str(uuid.uuid4())
            result = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "solve-challenge-server", "version": "1.0.0"},
            }
            resp = JSONResponse(_rpc_result(msg_id, result))
            resp.headers["Mcp-Session-Id"] = session_id
            return resp

        elif method == "notifications/initialized":
            # Notification only, no response body expected.
            return Response(status_code=202)

        elif method == "tools/list":
            responses.append(_rpc_result(msg_id, {"tools": TOOLS}))

        elif method == "tools/call":
            params = msg.get("params", {})
            name = params.get("name")
            if name != "solve_challenge":
                responses.append(_rpc_error(msg_id, -32602, f"Unknown tool '{name}'"))
                continue

            challenge = request.headers.get("X-Exam-Challenge", "")
            text = _solve(challenge)
            result = {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            }
            responses.append(_rpc_result(msg_id, result))

        elif method == "ping":
            responses.append(_rpc_result(msg_id, {}))

        else:
            if not is_notification:
                responses.append(_rpc_error(msg_id, -32601, f"Method not found: {method}"))

    if not responses:
        return Response(status_code=202)
    if len(responses) == 1 and not isinstance(body, list):
        return JSONResponse(responses[0])
    return JSONResponse(responses)


@router.get("/mcp")
async def mcp_get():
    # Some clients probe GET for an SSE stream; we don't need server-initiated
    # pushes for this tool, so return 405 to signal "use POST".
    return Response(status_code=405)
