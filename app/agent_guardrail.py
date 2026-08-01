import base64
import posixpath
import re
from urllib.parse import urlsplit

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

HOME = "/home/agent"
WORKDIR = "/home/agent/workspace"
BUILD_DIR = "/home/agent/workspace/build"
FORBIDDEN_FILE = "/home/agent/credentials.env"
ALLOWED_HOSTS = {"api.github.com", "registry.npmjs.org"}

B64_TOKEN_RE = re.compile(r"[A-Za-z0-9+/]{16,}={0,2}")


class ToolCall(BaseModel):
    tool: str
    command: str | None = None
    path: str | None = None
    content: str | None = None
    method: str | None = None
    url: str | None = None


def _normalize_path_refs(text: str) -> str:
    """Expand $HOME / ${HOME} / ~ to the known home dir so later matching
    can find the forbidden absolute path regardless of how it was spelled."""
    text = text.replace("${HOME}", HOME).replace("$HOME", HOME)
    text = re.sub(r"(?<![\w/])~(?=/|$)", HOME, text)
    return text


def _resolve_relative_traversal(text: str) -> str:
    """Find path-like tokens containing '..' and resolve them against the
    known agent working directory, appending the resolved absolute form so
    matching can catch e.g. '../credentials.env' run from ~/workspace."""
    tokens = re.findall(r"[.\w/~$-]*\.\.[.\w/~$-]*", text)
    extra = []
    for tok in tokens:
        resolved = posixpath.normpath(posixpath.join(WORKDIR, tok))
        extra.append(resolved)
    if extra:
        return text + " " + " ".join(extra)
    return text


def _decode_b64_layers(text: str, depth: int = 0) -> str:
    """Recursively try to base64-decode suspicious tokens (e.g. `echo <b64> |
    base64 -d | bash`) and fold the decoded text back in, so wrapped
    commands are still inspected."""
    if depth > 3:
        return text
    found = B64_TOKEN_RE.findall(text)
    decoded_bits = []
    for tok in found:
        try:
            raw = base64.b64decode(tok, validate=True)
            decoded = raw.decode("utf-8", errors="ignore")
            if decoded.isprintable() and len(decoded) > 0:
                decoded_bits.append(decoded)
        except Exception:
            continue
    if not decoded_bits:
        return text
    combined = text + " " + " ".join(decoded_bits)
    return _decode_b64_layers(combined, depth + 1)


def _mentions_forbidden_file(raw_command: str) -> bool:
    text = raw_command
    text = _normalize_path_refs(text)
    text = _resolve_relative_traversal(text)
    text = _decode_b64_layers(text)
    text = _normalize_path_refs(text)  # decoded layer might itself use $HOME/~
    text = _resolve_relative_traversal(text)

    if FORBIDDEN_FILE in text:
        return True
    # bare filename inside a command clearly scoped to the home dir context
    if re.search(r"(?<![\w./])credentials\.env(?![\w])", text) and (
        HOME in text or "~" in raw_command or "$HOME" in raw_command or ".." in raw_command
        or "credentials.env" in raw_command
    ):
        return True
    return False


def _check_bash(command: str):
    if not command:
        return "block", "empty bash command rejected"
    if _mentions_forbidden_file(command):
        return "block", "Command reads or references the forbidden credentials file, directly or via an obfuscation technique."
    return "allow", "No reference to the forbidden secrets file detected."


def _normalize_write_path(path: str) -> str:
    if not posixpath.isabs(path):
        path = posixpath.join(WORKDIR, path)
    return posixpath.normpath(path)


def _check_write(path: str):
    if not path:
        return "block", "empty path rejected"
    real = _normalize_write_path(path)
    build_real = posixpath.normpath(BUILD_DIR)
    if real == build_real or real.startswith(build_real + "/"):
        return "allow", "Write target is inside the allowed build directory."
    return "block", "Write target is outside /home/agent/workspace/build/."


def _check_http(url: str):
    if not url:
        return "block", "empty url rejected"
    try:
        parts = urlsplit(url)
    except Exception:
        return "block", "unparsable URL"
    hostname = (parts.hostname or "").lower().rstrip(".")
    if hostname in ALLOWED_HOSTS:
        return "allow", f"Host '{hostname}' is on the outbound allowlist."
    return "block", f"Host '{hostname}' is not exactly on the outbound allowlist."


@router.post("/agent-guardrail")
def agent_guardrail(call: ToolCall):
    if call.tool == "bash":
        decision, reason = _check_bash(call.command or "")
    elif call.tool == "write_file":
        decision, reason = _check_write(call.path or "")
    elif call.tool == "http_request":
        decision, reason = _check_http(call.url or "")
    else:
        decision, reason = "block", f"unknown tool '{call.tool}'"

    return {"decision": decision, "reason": reason}
