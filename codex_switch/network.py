from __future__ import annotations

import json
import os
import re
import shutil
import socket
import ssl
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .core import CODEX_HOST, CODEX_PORT, USER_AGENT
from .models import ProxyInfo


def build_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = True
    return context

def parse_proxy_info(source: str, raw: str) -> ProxyInfo | None:
    proxy_url = raw if "://" in raw else f"http://{raw}"
    parsed = urllib.parse.urlsplit(proxy_url)
    if not parsed.hostname:
        return None
    scheme = parsed.scheme.lower() or "http"
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80
    return ProxyInfo(source=source, raw=raw, scheme=scheme, host=parsed.hostname, port=port)

def proxy_port_is_open(proxy: ProxyInfo) -> bool:
    try:
        with socket.create_connection((proxy.host, proxy.port), timeout=0.4):
            return True
    except OSError:
        return False

def get_codex_wrapper_proxy() -> ProxyInfo | None:
    codex_path = shutil.which("codex")
    if not codex_path:
        return None
    path = Path(codex_path)
    try:
        text = path.read_text()
    except Exception:
        return None
    if len(text) > 20000 or "exec" not in text:
        return None

    assignments: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.+?)\s*$", line)
        if not match:
            continue
        key, value = match.groups()
        value = value.strip().strip("'\"")
        if value.startswith("$"):
            value = assignments.get(value[1:], value)
        assignments[key] = value

    raw = (
        assignments.get("HTTPS_PROXY")
        or assignments.get("https_proxy")
        or assignments.get("ALL_PROXY")
        or assignments.get("all_proxy")
        or assignments.get("CLASH_PROXY")
    )
    if not raw or raw.startswith("$"):
        return None
    proxy = parse_proxy_info("codex_wrapper", raw)
    if proxy and proxy_port_is_open(proxy):
        return proxy
    return None

def get_proxy_info() -> ProxyInfo | None:
    for source in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        raw = os.environ.get(source)
        if not raw:
            continue
        proxy = parse_proxy_info(source, raw)
        if proxy:
            return proxy
    return get_codex_wrapper_proxy()

def build_proxy_opener(proxy: ProxyInfo | None) -> urllib.request.OpenerDirector:
    if proxy is None:
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(
        urllib.request.ProxyHandler(
            {
                "http": proxy.url(),
                "https": proxy.url(),
            }
        )
    )

def read_http_headers(sock: socket.socket, *, limit: int = 8192) -> str:
    chunks: list[bytes] = []
    total = 0
    while total < limit:
        chunk = sock.recv(1024)
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if b"\r\n\r\n" in b"".join(chunks):
            break
    return b"".join(chunks).decode("utf-8", errors="replace")

def connect_to_codex(timeout: float) -> tuple[socket.socket, str]:
    proxy = get_proxy_info()
    if proxy is None:
        return socket.create_connection((CODEX_HOST, CODEX_PORT), timeout=timeout), "direct"

    if proxy.scheme not in {"http", "https"}:
        raise OSError(f"unsupported proxy scheme for doctor: {proxy.scheme}")

    raw_sock = socket.create_connection((proxy.host, proxy.port), timeout=timeout)
    raw_sock.settimeout(timeout)
    sock: socket.socket = raw_sock
    if proxy.scheme == "https":
        sock = build_ssl_context().wrap_socket(raw_sock, server_hostname=proxy.host)
        sock.settimeout(timeout)

    authority = f"{CODEX_HOST}:{CODEX_PORT}"
    request = (
        f"CONNECT {authority} HTTP/1.1\r\n"
        f"Host: {authority}\r\n"
        f"User-Agent: {USER_AGENT}\r\n"
        "Proxy-Connection: Keep-Alive\r\n"
        "\r\n"
    ).encode("ascii")
    try:
        sock.sendall(request)
        raw_headers = read_http_headers(sock)
        first_line = raw_headers.splitlines()[0] if raw_headers else ""
        if " 200 " not in first_line:
            raise OSError(f"proxy CONNECT failed: {first_line or 'empty response'}")
        return sock, proxy.display()
    except Exception:
        sock.close()
        raise

def detect_cloudflare_challenge(text: str) -> bool:
    lowered = text.lower()
    markers = (
        "enable javascript and cookies to continue",
        "challenge-error-text",
        "/cdn-cgi/challenge-platform/",
        "__cf_chl_",
    )
    return any(marker in lowered for marker in markers)

def redact_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key in {"email", "user_id", "account_id"}:
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_json_value(item)
        return redacted
    if isinstance(value, list):
        return [redact_json_value(item) for item in value]
    return value

def summarize_body(text: str, limit: int = 180) -> str:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        compact = " ".join(text.split())
    else:
        compact = json.dumps(redact_json_value(parsed), ensure_ascii=False, separators=(",", ":"))
    return compact[:limit]
