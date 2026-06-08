from __future__ import annotations

import base64
import json
import subprocess
from pathlib import Path
from typing import Any

from .core import AUTH_FILE, CODEX_DIR, CYAN, YELLOW, command_exists, fail, get_current_name, read_index, find_account


def load_auth(path: Path = AUTH_FILE) -> dict[str, Any]:
    if not path.exists():
        fail(f"未找到认证文件: {path}\n请先运行 `codex login`。")
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        fail(f"读取认证文件失败: {exc}")

def write_auth(auth: dict[str, Any], path: Path = AUTH_FILE) -> None:
    CODEX_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(auth, ensure_ascii=False, indent=2) + "\n")

def get_account_id(auth: dict[str, Any]) -> str:
    return str(auth.get("tokens", {}).get("account_id") or "")

def get_access_token(auth: dict[str, Any]) -> str | None:
    token = auth.get("tokens", {}).get("access_token")
    if isinstance(token, str) and token:
        return token
    return None

def decode_jwt_payload(token: str) -> dict[str, Any]:
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8")
        obj = json.loads(decoded)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}

def get_current_account_id() -> str:
    if not AUTH_FILE.exists():
        return ""
    try:
        aid = get_account_id(load_auth())
        if aid:
            return aid
    except SystemExit:
        pass
    name = get_current_name()
    if name:
        acct = find_account(read_index(), name)
        if acct:
            return str(acct.get("account_id", ""))
    return ""

def get_last_refresh(auth: dict[str, Any]) -> str:
    value = auth.get("last_refresh")
    return value if isinstance(value, str) else ""

def derive_default_name(auth: dict[str, Any]) -> str:
    id_token = auth.get("tokens", {}).get("id_token")
    if isinstance(id_token, str) and id_token:
        email = decode_jwt_payload(id_token).get("email")
        if isinstance(email, str) and "@" in email:
            return email.split("@", 1)[0]
    access_token = auth.get("tokens", {}).get("access_token")
    if isinstance(access_token, str) and access_token:
        profile = decode_jwt_payload(access_token).get("https://api.openai.com/profile", {})
        if isinstance(profile, dict):
            email = profile.get("email")
            if isinstance(email, str) and "@" in email:
                return email.split("@", 1)[0]
    return get_account_id(auth)[:8] or "current"

def get_email(auth: dict[str, Any]) -> str:
    id_token = auth.get("tokens", {}).get("id_token")
    if isinstance(id_token, str) and id_token:
        email = decode_jwt_payload(id_token).get("email")
        if isinstance(email, str) and "@" in email:
            return email
    access_token = auth.get("tokens", {}).get("access_token")
    if isinstance(access_token, str) and access_token:
        profile = decode_jwt_payload(access_token).get("https://api.openai.com/profile", {})
        if isinstance(profile, dict):
            email = profile.get("email")
            if isinstance(email, str) and "@" in email:
                return email
    return ""

def get_plan_type(auth: dict[str, Any]) -> str:
    access_token = auth.get("tokens", {}).get("access_token")
    if isinstance(access_token, str) and access_token:
        openai_auth = decode_jwt_payload(access_token).get("https://api.openai.com/auth", {})
        if isinstance(openai_auth, dict):
            plan = openai_auth.get("chatgpt_plan_type")
            if isinstance(plan, str) and plan:
                return plan
    return ""

def get_plan_expiry(auth: dict[str, Any]) -> str:
    id_token = auth.get("tokens", {}).get("id_token")
    if isinstance(id_token, str) and id_token:
        openai_auth = decode_jwt_payload(id_token).get("https://api.openai.com/auth", {})
        if isinstance(openai_auth, dict):
            until = openai_auth.get("chatgpt_subscription_active_until")
            if isinstance(until, str) and until:
                return until[:10]
    return ""

def is_valid_auth(auth: dict[str, Any]) -> bool:
    return bool(get_account_id(auth) and get_access_token(auth))

def auth_changed(previous_auth: dict[str, Any] | None, current_auth: dict[str, Any]) -> bool:
    if previous_auth is None:
        return is_valid_auth(current_auth)
    return (
        get_account_id(previous_auth) != get_account_id(current_auth)
        or get_last_refresh(previous_auth) != get_last_refresh(current_auth)
    )

def run_codex_login() -> dict[str, Any]:
    if not command_exists("codex"):
        fail("未找到 `codex` 命令。请先确认 Codex CLI 已安装。")
    print(f"{CYAN}将启动 `codex login`，请在浏览器里完成登录。{NC}")
    previous_auth = load_auth() if AUTH_FILE.exists() else None
    result = subprocess.run(["codex", "login"])
    current_auth = load_auth() if AUTH_FILE.exists() else {}

    if result.returncode == 0:
        if not is_valid_auth(current_auth):
            fail("`codex login` 已完成，但认证文件不完整。")
        return current_auth

    # Codex CLI 的浏览器登录偶发会在 token exchange 阶段报错，但 auth.json 已更新。
    if current_auth and is_valid_auth(current_auth) and auth_changed(previous_auth, current_auth):
        print(f"{YELLOW}检测到 `codex login` 返回了错误，但认证文件已经更新，继续使用新登录状态。{NC}")
        return current_auth

    fail(
        "`codex login` 没有完成，而且认证文件也没有更新。\n"
        "如果你刚才看到的是 `token exchange failed`、`tls handshake eof`、"
        "或 `error sending request for url (https://chatgpt.com/...)`，"
        "根因通常是当前命令行到 chatgpt.com 的网络/TLS 不稳定，不是账号保存逻辑本身。\n"
        "可先单独运行 `codex login`，成功后再执行 `codex-switch save <name>`。"
    )
