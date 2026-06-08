from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import get_default_state_dir, get_snapshot_store, seed_index_from_legacy

SCRIPT_DIR = Path(__file__).resolve().parent.parent
CODEX_DIR = Path.home() / ".codex"
AUTH_FILE = CODEX_DIR / "auth.json"
CONFIG_FILE = CODEX_DIR / "config.toml"
STATE_DIR = get_default_state_dir()
INDEX_FILE = STATE_DIR / "index.json"
OFFICIAL_CONFIG_BACKUP = STATE_DIR / "config-official.toml"
CURRENT_FILE = STATE_DIR / "current"
KEYCHAIN_SERVICE = "codex-switch-mac"
USER_AGENT = "codex-switch/0.3"
SNAPSHOT_STORE = get_snapshot_store(STATE_DIR, CODEX_DIR, KEYCHAIN_SERVICE)
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
CODEX_HOST = "chatgpt.com"
CODEX_PORT = 443
CODEX_CLIENT_VERSION = "0.123.0"
MODELS_PATH = f"/backend-api/codex/models?client_version={CODEX_CLIENT_VERSION}"
RESPONSES_WS_PATH = "/backend-api/codex/responses"
RESPONSES_COMPACT_PATH = "/backend-api/codex/responses/compact"
HTTP_TIMEOUT = 10.0
DOCTOR_TIMEOUT = 8.0

RED = "\033[0;31m"
GREEN = "\033[0;32m"
YELLOW = "\033[1;33m"
BLUE = "\033[0;34m"
CYAN = "\033[0;36m"
DIM = "\033[2m"
NC = "\033[0m"


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not INDEX_FILE.exists():
        if seed_index_from_legacy(INDEX_FILE, CODEX_DIR):
            return
        INDEX_FILE.write_text(json.dumps({"accounts": []}, ensure_ascii=False, indent=2) + "\n")

def read_index() -> dict[str, Any]:
    ensure_state_dir()
    try:
        return json.loads(INDEX_FILE.read_text())
    except Exception:
        return {"accounts": []}

def write_index(index: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n")

def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

def fail(message: str, exit_code: int = 1) -> None:
    print(f"{RED}{message}{NC}", file=sys.stderr)
    raise SystemExit(exit_code)

def command_exists(name: str) -> bool:
    return shutil.which(name) is not None

def backup_official_config() -> None:
    if CONFIG_FILE.exists() and not OFFICIAL_CONFIG_BACKUP.exists():
        ensure_state_dir()
        OFFICIAL_CONFIG_BACKUP.write_text(CONFIG_FILE.read_text())

def restore_official_config() -> None:
    if OFFICIAL_CONFIG_BACKUP.exists():
        CONFIG_FILE.write_text(OFFICIAL_CONFIG_BACKUP.read_text())

def get_current_name() -> str:
    if CURRENT_FILE.exists():
        name = CURRENT_FILE.read_text().strip()
        if name:
            return name
    return ""

def set_current_name(name: str) -> None:
    ensure_state_dir()
    CURRENT_FILE.write_text(name + "\n")

def sorted_accounts(index: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(index.get("accounts", []), key=lambda a: str(a.get("name", "")).lower())

def resolve_name(index: dict[str, Any], arg: str) -> str:
    seq = arg[1:] if arg.startswith("#") else arg
    if seq.isdigit():
        pos = int(seq) - 1
        accounts = sorted_accounts(index)
        if pos < 0 or pos >= len(accounts):
            fail(f"序号 {seq} 超出范围（共 {len(accounts)} 个账号）。")
        return str(accounts[pos]["name"])
    return arg

def find_account(index: dict[str, Any], name: str) -> dict[str, Any] | None:
    for account in index.get("accounts", []):
        if account.get("name") == name:
            return account
    return None

def find_account_by_id(index: dict[str, Any], account_id: str) -> dict[str, Any] | None:
    for account in index.get("accounts", []):
        if account.get("account_id") == account_id:
            return account
    return None
