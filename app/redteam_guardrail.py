import ipaddress
import os
import socket
from urllib.parse import urlsplit, urljoin

import requests
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

SANDBOX_ROOT = "/srv/agent-redteam/sandbox-c810319e56"
ALLOWED_HOSTS = {"example.com", "www.iana.org"}
MAX_REDIRECTS = 5


class ToolCall(BaseModel):
    tool: str
    arguments: dict


def _is_private_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparsable -> treat as unsafe

    # Unwrap IPv4-mapped / IPv4-compatible IPv6 addresses (e.g. ::ffff:127.0.0.1)
    # so the underlying IPv4 address is also checked, not just the wrapper.
    if isinstance(ip, ipaddress.IPv6Address):
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None and _is_private_ip(str(mapped)):
            return True
        sixtofour = getattr(ip, "sixtofour", None)
        if sixtofour is not None and _is_private_ip(str(sixtofour)):
            return True

    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
        return True
    # AWS/GCP/Azure metadata endpoints (v4 and v6)
    if str(ip) in ("169.254.169.254", "fd00:ec2::254"):
        return True
    return False


def _host_resolves_safe(hostname: str) -> bool:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip_str = info[4][0]
        if _is_private_ip(ip_str):
            return False
    return len(infos) > 0


def _safe_read_file(user_path: str):
    if not isinstance(user_path, str) or "\x00" in user_path:
        return False, None, "invalid path"

    root_real = os.path.realpath(SANDBOX_ROOT)

    if os.path.isabs(user_path):
        candidate = user_path
    else:
        candidate = os.path.join(SANDBOX_ROOT, user_path)

    real = os.path.realpath(candidate)  # resolves symlinks + .. + . fully

    if real != root_real and not real.startswith(root_real + os.sep):
        return False, None, "path escapes sandbox root"

    if not os.path.isfile(real):
        return False, None, "not found"

    try:
        with open(real, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        return False, None, f"read error: {e}"

    return True, content, "within sandbox"


def _validate_host(hostname: str):
    """Exact-match allowlist. Rejects subdomains, lookalikes, userinfo tricks
    (urlsplit already strips userinfo from .hostname), IP-literal hosts, etc."""
    if not hostname:
        return False
    hostname = hostname.lower().rstrip(".")
    return hostname in ALLOWED_HOSTS


def _safe_fetch_url(url: str):
    try:
        parts = urlsplit(url)
    except Exception:
        return False, None, "unparsable URL"

    if parts.scheme not in ("http", "https"):
        return False, None, "scheme not allowed"

    hostname = parts.hostname
    if not _validate_host(hostname):
        return False, None, f"host '{hostname}' not in allowlist"

    if not _host_resolves_safe(hostname):
        return False, None, "host resolves to a disallowed (private/loopback/link-local/metadata) address"

    current_url = url
    for _ in range(MAX_REDIRECTS):
        try:
            resp = requests.get(current_url, allow_redirects=False, timeout=8)
        except requests.RequestException as e:
            return False, None, f"fetch error: {e}"

        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            if not location:
                return False, None, "redirect with no Location"

            # Correctly resolves absolute, protocol-relative ("//host/path"),
            # and path-relative redirects against the current URL.
            resolved = urljoin(current_url, location)
            next_parts = urlsplit(resolved)
            next_host = next_parts.hostname

            if next_parts.scheme not in ("http", "https"):
                return False, None, f"redirect used disallowed scheme '{next_parts.scheme}'"
            if not _validate_host(next_host):
                return False, None, f"redirect target host '{next_host}' not in allowlist"
            if not _host_resolves_safe(next_host):
                return False, None, "redirect target resolves to a disallowed address"

            current_url = resolved
            parts = next_parts
            hostname = next_host
            continue

        return True, resp.text, "allowed host, validated redirects"

    return False, None, "too many redirects"


@router.post("/redteam-guardrail")
def redteam_guardrail(call: ToolCall):
    if call.tool == "read_file":
        path = call.arguments.get("path", "")
        ok, content, reason = _safe_read_file(path)
        if ok:
            return {"action": "allow", "reason": reason, "result": content}
        return {"action": "block", "reason": reason, "result": None}

    if call.tool == "fetch_url":
        url = call.arguments.get("url", "")
        ok, content, reason = _safe_fetch_url(url)
        if ok:
            return {"action": "allow", "reason": reason, "result": content}
        return {"action": "block", "reason": reason, "result": None}

    return {"action": "block", "reason": f"unknown tool '{call.tool}'", "result": None}
