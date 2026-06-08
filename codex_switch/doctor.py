from __future__ import annotations

import base64
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

from .auth import get_access_token, load_auth
from .core import AUTH_FILE, BLUE, CODEX_HOST, CODEX_PORT, DOCTOR_TIMEOUT, GREEN, MODELS_PATH, NC, RED, RESPONSES_COMPACT_PATH, RESPONSES_WS_PATH, USER_AGENT, YELLOW, command_exists
from .models import DiagnosticStep
from .network import build_proxy_opener, build_ssl_context, connect_to_codex, detect_cloudflare_challenge, get_proxy_info, summarize_body


def timed_step(name: str, fn) -> DiagnosticStep:
    start = time.perf_counter()
    try:
        payload = fn()
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return DiagnosticStep(
            name=name,
            ok=False,
            latency_ms=round(latency_ms, 1),
            reason=type(exc).__name__,
            detail=str(exc),
        )

    latency_ms = (time.perf_counter() - start) * 1000.0
    payload.setdefault("name", name)
    payload.setdefault("ok", True)
    payload.setdefault("latency_ms", round(latency_ms, 1))
    return DiagnosticStep(**payload)

def diagnostic_dns() -> DiagnosticStep:
    def run() -> dict[str, Any]:
        infos = socket.getaddrinfo(CODEX_HOST, CODEX_PORT, type=socket.SOCK_STREAM)
        ips = sorted({info[4][0] for info in infos})
        return {
            "detail": ", ".join(ips[:4]),
            "remote_ip": ips[0] if ips else None,
        }

    return timed_step("dns", run)

def diagnostic_tcp() -> DiagnosticStep:
    def run() -> dict[str, Any]:
        sock, transport = connect_to_codex(DOCTOR_TIMEOUT)
        try:
            return {"remote_ip": sock.getpeername()[0], "detail": transport}
        finally:
            sock.close()

    return timed_step("tcp", run)

def diagnostic_tls() -> DiagnosticStep:
    context = build_ssl_context()

    def run() -> dict[str, Any]:
        raw_sock, transport = connect_to_codex(DOCTOR_TIMEOUT)
        try:
            with context.wrap_socket(raw_sock, server_hostname=CODEX_HOST) as tls_sock:
                cert = tls_sock.getpeercert()
                subject = dict(item[0] for item in cert.get("subject", [])) if cert else {}
                return {
                    "remote_ip": tls_sock.getpeername()[0],
                    "detail": f"tls={tls_sock.version()} subject={subject.get('commonName', '?')} via {transport}",
                }
        except Exception:
            raw_sock.close()
            raise

    return timed_step("tls", run)

def make_https_headers(token: str | None) -> dict[str, str]:
    headers = {
        "Host": CODEX_HOST,
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

def diagnostic_https(
    name: str,
    path: str,
    token: str | None,
    *,
    method: str = "GET",
    body: bytes | None = None,
    ok_statuses: set[int] | None = None,
) -> DiagnosticStep:
    def run() -> dict[str, Any]:
        proxy = get_proxy_info()
        headers = make_https_headers(token)
        if body is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            f"https://{CODEX_HOST}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            resp = build_proxy_opener(proxy).open(req, timeout=DOCTOR_TIMEOUT)
        except urllib.error.HTTPError as exc:
            resp = exc
        with resp:
            data = resp.read(1024).decode("utf-8", errors="replace")
            challenge = detect_cloudflare_challenge(data)
            statuses = ok_statuses or set()
            status = resp.status
            ok = (status in statuses if statuses else 200 <= status < 500) and not challenge
            detail = summarize_body(data)
            if proxy is not None:
                detail = f"via {proxy.display()} | {detail}"
            return {
                "ok": ok,
                "status": status,
                "reason": "cloudflare_challenge" if challenge else resp.reason,
                "detail": detail,
            }

    return timed_step(name, run)

def diagnostic_websocket(token: str | None) -> DiagnosticStep:
    context = build_ssl_context()

    def run() -> dict[str, Any]:
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        lines = [
            f"GET {RESPONSES_WS_PATH} HTTP/1.1",
            f"Host: {CODEX_HOST}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            "Sec-WebSocket-Version: 13",
            f"Sec-WebSocket-Key: {key}",
            "Origin: https://chatgpt.com",
            f"User-Agent: {USER_AGENT}",
        ]
        if token:
            lines.append(f"Authorization: Bearer {token}")
        lines.append("")
        lines.append("")
        request = "\r\n".join(lines).encode("ascii")

        raw_sock, transport = connect_to_codex(DOCTOR_TIMEOUT)
        try:
            with context.wrap_socket(raw_sock, server_hostname=CODEX_HOST) as tls_sock:
                tls_sock.settimeout(DOCTOR_TIMEOUT)
                tls_sock.sendall(request)
                raw = tls_sock.recv(4096).decode("utf-8", errors="replace")
                first_line = raw.splitlines()[0] if raw else ""
                status = None
                reason = None
                if first_line.startswith("HTTP/1.1 "):
                    parts = first_line.split(" ", 2)
                    if len(parts) >= 3:
                        status = int(parts[1])
                        reason = parts[2]
                challenge = detect_cloudflare_challenge(raw)
                detail = summarize_body(raw)
                detail = f"via {transport} | {detail}"
                return {
                    "ok": bool(status) and status in {101, 400, 401, 403} and not challenge,
                    "status": status,
                    "reason": "cloudflare_challenge" if challenge else reason,
                    "detail": detail,
                    "remote_ip": tls_sock.getpeername()[0],
                }
        except Exception:
            raw_sock.close()
            raise

    return timed_step("ws /backend-api/codex/responses", run)

def get_route_summary(ip: str | None) -> str | None:
    if not ip:
        return None
    if sys.platform.startswith("win"):
        return None
    if sys.platform != "darwin" and command_exists("ip"):
        try:
            result = subprocess.run(
                ["ip", "route", "get", ip],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError:
            return None
        parts = result.stdout.split()
        interface = None
        gateway = None
        if "dev" in parts and parts.index("dev") + 1 < len(parts):
            interface = parts[parts.index("dev") + 1]
        if "via" in parts and parts.index("via") + 1 < len(parts):
            gateway = parts[parts.index("via") + 1]
        if not interface:
            return None
        summary = interface
        if gateway:
            summary += f" via {gateway}"
        return summary
    try:
        result = subprocess.run(
            ["route", "-n", "get", ip],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    fields: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip()
    interface = fields.get("interface")
    gateway = fields.get("gateway")
    if not interface:
        return None
    summary = interface
    if gateway:
        summary += f" via {gateway}"
    return summary

def list_proxy_processes() -> list[str]:
    try:
        result = subprocess.run(
            ["pgrep", "-lf", "clash|verge|mihomo|surge|v2ray|xray|sing-box|tailscale|warp"],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return lines[:6]

def classify_diagnostics(steps: list[DiagnosticStep]) -> tuple[str, list[str], int]:
    flags: list[str] = []
    failures = [step for step in steps if not step.ok]
    if not failures:
        return "healthy", flags, 0

    if any(step.name in {"dns", "tcp", "tls"} for step in failures):
        flags.append("transport_failures")
    if any(step.name.startswith("ws ") for step in failures):
        flags.append("responses_ws_failed")
    if any(step.name.endswith("/compact") for step in failures):
        flags.append("compact_endpoint_failed")
    if any(step.reason == "cloudflare_challenge" for step in steps):
        flags.append("cloudflare_challenge")
    if any(
        (step.reason and ("SSL" in step.reason or "Timeout" in step.reason))
        or (step.detail and ("EOF occurred in violation of protocol" in step.detail or "timed out" in step.detail))
        for step in failures
    ):
        return "unhealthy", sorted(set(flags)), 2

    if any(step.status in {401, 403} for step in failures):
        flags.append("auth_or_policy_response")
    return "warning", sorted(set(flags)), 1

def color_for_overall(overall: str) -> str:
    if overall == "healthy":
        return GREEN
    if overall == "warning":
        return YELLOW
    return RED

def format_step(step: DiagnosticStep) -> str:
    status = f"status={step.status}" if step.status is not None else ""
    latency = f"{step.latency_ms}ms" if step.latency_ms is not None else "-"
    reason = step.reason or ""
    detail = step.detail or ""
    pieces = [piece for piece in [status, reason, detail] if piece]
    suffix = " | ".join(pieces)
    marker = f"{GREEN}ok{NC}" if step.ok else f"{RED}fail{NC}"
    if suffix:
        return f"  {marker:<13} {step.name:<38} {latency:<10} {suffix}"
    return f"  {marker:<13} {step.name:<38} {latency}"

def run_doctor_attempt(token: str | None) -> list[DiagnosticStep]:
    return [
        diagnostic_dns(),
        diagnostic_tcp(),
        diagnostic_tls(),
        diagnostic_https(
            f"https {MODELS_PATH}",
            MODELS_PATH,
            token,
            ok_statuses={200, 401, 403},
        ),
        diagnostic_https(
            f"https {RESPONSES_COMPACT_PATH}",
            RESPONSES_COMPACT_PATH,
            token,
            method="POST",
            body=b"{}",
            ok_statuses={200, 400, 401, 403, 405, 422},
        ),
        diagnostic_https(
            "https /backend-api/wham/usage",
            "/backend-api/wham/usage",
            token,
            ok_statuses={200, 401, 403},
        ),
        diagnostic_websocket(token),
    ]


REFRESH_OPTIONS = [60, 120, 300, 600, 1800]
REFRESH_LABELS = ["1min", "2min", "5min", "10min", "30min"]

TL = "┌"
TR = "┐"
BL = "└"
BR = "┘"
HZ = "─"
VT = "│"
LJ = "├"
RJ = "┤"
SP = "·"

def cmd_doctor() -> int:
    token = None
    if AUTH_FILE.exists():
        try:
            token = get_access_token(load_auth())
        except SystemExit:
            token = None

    attempts: list[list[DiagnosticStep]] = []
    for attempt_idx in range(2):
        attempts.append(run_doctor_attempt(token))
        if attempt_idx == 0:
            time.sleep(0.4)

    all_steps = [step for attempt in attempts for step in attempt]
    overall, flags, exit_code = classify_diagnostics(all_steps)
    route_summary = get_route_summary(next((step.remote_ip for step in all_steps if step.remote_ip), None))
    proxy_processes = list_proxy_processes()
    proxy_info = get_proxy_info()
    codex_path = shutil.which("codex")

    print(f"{BLUE}Codex 网络检测{NC}")
    print(f"status:      {color_for_overall(overall)}{overall}{NC}")
    print(f"attempts:    {len(attempts)}")
    print(f"auth_token:  {'yes' if token else 'no'}")
    if codex_path:
        print(f"codex:       {codex_path}")
    if proxy_info:
        print(f"doctor_proxy:{proxy_info.display()}")
    if route_summary:
        print(f"route:       {route_summary}")
    if proxy_processes:
        print(f"proxy:       {proxy_processes[0]}")
        for line in proxy_processes[1:]:
            print(f"             {line}")
    if flags:
        print(f"flags:       {', '.join(flags)}")
    print("")
    for index, attempt in enumerate(attempts, start=1):
        print(f"[attempt {index}]")
        for step in attempt:
            print(format_step(step))
        if index != len(attempts):
            print("")

    return exit_code
