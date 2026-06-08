from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class WindowSummary:
    used_percent: int | None
    limit_window_seconds: int | None
    reset_after_seconds: int | None
    reset_at: int | None

    @property
    def remaining_percent(self) -> int | None:
        if self.used_percent is None:
            return None
        return max(0, 100 - self.used_percent)


@dataclass
class UsageFetchResult:
    payload: dict[str, Any] | None
    error_kind: str | None = None
    error_message: str | None = None


@dataclass
class DiagnosticStep:
    name: str
    ok: bool
    latency_ms: float | None = None
    status: int | None = None
    reason: str | None = None
    detail: str | None = None
    remote_ip: str | None = None


@dataclass
class ProxyInfo:
    source: str
    raw: str
    scheme: str
    host: str
    port: int

    def display(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{self.source}={self.scheme}://{host}:{self.port}"

    def url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{self.scheme}://{host}:{self.port}"
