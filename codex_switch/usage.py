from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any

from .core import HTTP_TIMEOUT, USAGE_URL, USER_AGENT
from .models import UsageFetchResult, WindowSummary
from .network import build_proxy_opener, get_proxy_info


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None

def parse_window(payload: Any) -> WindowSummary:
    data = payload if isinstance(payload, dict) else {}
    return WindowSummary(
        used_percent=_as_int(data.get("used_percent")),
        limit_window_seconds=_as_int(data.get("limit_window_seconds")),
        reset_after_seconds=_as_int(data.get("reset_after_seconds")),
        reset_at=_as_int(data.get("reset_at")),
    )

def fmt_pct(pct: int | None) -> str:
    return "??%" if pct is None else f"{pct}%"

def make_bar(remaining_pct: int | None, width: int = 20) -> str:
    if remaining_pct is None:
        return "[" + "·" * width + "]"
    filled = round(remaining_pct / 100 * width)
    filled = min(max(filled, 0), width)
    return "[" + "█" * filled + "░" * (width - filled) + "]"

def format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "-"
    seconds = max(0, seconds)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs and not parts:
        parts.append(f"{secs}s")
    return " ".join(parts) if parts else "0m"

def format_timestamp(ts: int | None) -> str:
    if ts is None:
        return "-"
    return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")

def fetch_usage(token: str) -> UsageFetchResult:
    last_error: Exception | None = None
    proxy = get_proxy_info()
    opener = build_proxy_opener(proxy)
    for attempt in range(2):
        req = urllib.request.Request(
            USAGE_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with opener.open(req, timeout=HTTP_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if isinstance(payload, dict):
                return UsageFetchResult(payload=payload)
            return UsageFetchResult(
                payload=None,
                error_kind="invalid_response",
                error_message="返回数据不是预期的 JSON 对象。",
            )
        except urllib.error.HTTPError as exc:
            # 401/403 基本可视为登录无效，其他错误先重试一次。
            if exc.code in (401, 403):
                return UsageFetchResult(
                    payload=None,
                    error_kind="auth",
                    error_message=f"HTTP {exc.code}，当前 access token 很可能已失效。",
                )
            last_error = exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
        if attempt == 0:
            time.sleep(0.6)
    if isinstance(last_error, urllib.error.URLError):
        reason = str(last_error.reason)
        if "SSLEOFError" in reason or "EOF occurred in violation of protocol" in reason:
            return UsageFetchResult(
                payload=None,
                error_kind="network_tls",
                error_message="命令行到 chatgpt.com 的 TLS 握手失败。",
            )
        return UsageFetchResult(
            payload=None,
            error_kind="network",
            error_message=f"网络请求失败: {reason}",
        )
    if isinstance(last_error, TimeoutError):
        return UsageFetchResult(
            payload=None,
            error_kind="timeout",
            error_message="请求 chatgpt.com 超时。",
        )
    if isinstance(last_error, json.JSONDecodeError):
        return UsageFetchResult(
            payload=None,
            error_kind="invalid_response",
            error_message="响应不是有效 JSON。",
        )
    if last_error is not None:
        return UsageFetchResult(
            payload=None,
            error_kind="unknown",
            error_message=str(last_error),
        )
    return UsageFetchResult(payload=None, error_kind="unknown", error_message="未知错误。")
