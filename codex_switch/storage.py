from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


class SnapshotStoreError(RuntimeError):
    """Raised when an account snapshot cannot be read or written."""


def get_codex_dir() -> Path:
    return Path.home() / ".codex"


def get_default_state_dir() -> Path:
    override = os.environ.get("CODEX_SWITCH_STATE_DIR")
    if override:
        return Path(override).expanduser()

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "codex-switch-mac"
    if sys.platform.startswith("win"):
        root = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(root) / "codex-switch"

    data_home = os.environ.get("XDG_DATA_HOME")
    if data_home:
        return Path(data_home).expanduser() / "codex-switch"
    return Path.home() / ".local" / "share" / "codex-switch"


def normalize_legacy_index(index: dict[str, Any]) -> dict[str, Any]:
    accounts = []
    for account in index.get("accounts", []):
        if not isinstance(account, dict) or not account.get("name"):
            continue
        accounts.append(
            {
                "name": str(account.get("name")),
                "account_id": str(account.get("account_id") or ""),
                "saved_at": str(account.get("saved_at") or account.get("last_added") or ""),
                "type": str(account.get("type") or "official"),
            }
        )
    accounts.sort(key=lambda item: item["name"].lower())
    return {"accounts": accounts}


def seed_index_from_legacy(index_file: Path, codex_dir: Path) -> bool:
    legacy_index = codex_dir / "accounts" / "index.json"
    if index_file.exists() or not legacy_index.exists():
        return False
    try:
        index = json.loads(legacy_index.read_text())
    except Exception:
        return False
    index_file.parent.mkdir(parents=True, exist_ok=True)
    index_file.write_text(json.dumps(normalize_legacy_index(index), ensure_ascii=False, indent=2) + "\n")
    return True


class FileSnapshotStore:
    def __init__(self, state_dir: Path, codex_dir: Path) -> None:
        self.accounts_dir = state_dir / "accounts"
        self.legacy_accounts_dir = codex_dir / "accounts"

    def _path(self, name: str) -> Path:
        return self.accounts_dir / f"{name}.json"

    def _legacy_path(self, name: str) -> Path:
        return self.legacy_accounts_dir / f"{name}.json"

    def save(self, name: str, payload: dict[str, Any]) -> None:
        self.accounts_dir.mkdir(parents=True, exist_ok=True)
        path = self._path(name)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(path)

    def load(self, name: str) -> dict[str, Any]:
        path = self._path(name)
        if not path.exists():
            path = self._legacy_path(name)
        if not path.exists():
            raise SnapshotStoreError(f"没有找到账号 `{name}` 的快照。")
        try:
            obj = json.loads(path.read_text())
        except Exception as exc:
            raise SnapshotStoreError(f"读取账号 `{name}` 快照失败: {exc}") from exc
        if isinstance(obj, dict) and "auth" in obj:
            return obj
        if isinstance(obj, dict):
            return {"auth": obj, "config_toml": None}
        raise SnapshotStoreError(f"账号 `{name}` 快照格式错误。")

    def delete(self, name: str) -> None:
        removed = False
        for path in (self._path(name), self._legacy_path(name)):
            if path.exists():
                path.unlink()
                removed = True
        if not removed:
            raise SnapshotStoreError(f"没有找到账号 `{name}` 的快照。")


class MacKeychainStore:
    def __init__(self, service: str) -> None:
        self.service = service

    def save(self, name: str, payload: dict[str, Any]) -> None:
        encoded = base64.b64encode(
            json.dumps(payload, ensure_ascii=False).encode("utf-8")
        ).decode("ascii")
        try:
            subprocess.run(
                [
                    "security",
                    "add-generic-password",
                    "-U",
                    "-a",
                    name,
                    "-s",
                    self.service,
                    "-l",
                    f"Codex Switch ({name})",
                    "-w",
                    encoded,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise SnapshotStoreError(_format_subprocess_error(exc)) from exc

    def load(self, name: str) -> dict[str, Any]:
        try:
            result = subprocess.run(
                [
                    "security",
                    "find-generic-password",
                    "-a",
                    name,
                    "-s",
                    self.service,
                    "-w",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise SnapshotStoreError(f"Keychain 中没有找到账号 `{name}`。") from exc
        try:
            decoded = base64.b64decode(result.stdout.strip().encode("ascii"))
            obj = json.loads(decoded.decode("utf-8"))
        except Exception as exc:
            raise SnapshotStoreError(f"读取 Keychain 快照失败: {exc}") from exc
        if isinstance(obj, dict) and "auth" in obj:
            return obj
        if isinstance(obj, dict):
            return {"auth": obj, "config_toml": None}
        raise SnapshotStoreError("Keychain 快照格式错误。")

    def delete(self, name: str) -> None:
        try:
            subprocess.run(
                [
                    "security",
                    "delete-generic-password",
                    "-a",
                    name,
                    "-s",
                    self.service,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            raise SnapshotStoreError(_format_subprocess_error(exc)) from exc


def _format_subprocess_error(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr.strip() if exc.stderr else str(exc)
        return stderr
    return str(exc)


def get_snapshot_store(state_dir: Path, codex_dir: Path, keychain_service: str) -> Any:
    mode = os.environ.get("CODEX_SWITCH_STORE", "auto").strip().lower()
    if mode not in {"auto", "keychain", "file"}:
        raise SnapshotStoreError("CODEX_SWITCH_STORE 只能是 auto、keychain 或 file。")
    if mode == "file":
        return FileSnapshotStore(state_dir, codex_dir)
    if sys.platform == "darwin" and shutil.which("security"):
        return MacKeychainStore(keychain_service)
    if mode == "keychain":
        raise SnapshotStoreError("当前系统不可用 macOS Keychain。")
    return FileSnapshotStore(state_dir, codex_dir)
