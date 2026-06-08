from __future__ import annotations

from typing import Any

from .auth import get_account_id, write_auth
from .core import GREEN, RED, YELLOW, NC, SNAPSHOT_STORE, fail, now_utc, read_index, write_index, find_account, find_account_by_id
from .storage import SnapshotStoreError


def save_snapshot(name: str, auth: dict[str, Any], config_toml: str | None = None) -> str:
    account_id = get_account_id(auth) or "relay-" + name

    payload: dict[str, Any] = {"auth": auth}
    if config_toml is not None:
        payload["config_toml"] = config_toml

    try:
        SNAPSHOT_STORE.save(name, payload)
    except SnapshotStoreError as exc:
        fail(str(exc))

    index = read_index()
    existing = find_account(index, name)
    saved_at = now_utc()
    entry: dict[str, Any] = {
        "name": name,
        "account_id": account_id,
        "saved_at": saved_at,
        "type": "relay" if config_toml is not None else "official",
    }
    if existing:
        existing.update(entry)
    else:
        index["accounts"].append(entry)
        index["accounts"].sort(key=lambda item: item["name"])
    write_index(index)
    return account_id

def prompt_existing_name_resolution(name: str) -> str:
    while True:
        print(f"{YELLOW}账号名 `{name}` 已存在。{NC}")
        print("  [r] 覆盖现有账号")
        print("  [n] 重新输入名称")
        print("  [c] 取消")
        try:
            choice = input("选择 [r/n/c]: ").strip().lower()
        except EOFError:
            fail("名称已存在，且当前不是交互终端，无法继续。")
        if choice in {"r", "replace"}:
            return name
        if choice in {"n", "new"}:
            try:
                new_name = input("新的账号名: ").strip()
            except EOFError:
                fail("未读取到新的账号名。")
            if not new_name:
                print(f"{YELLOW}账号名不能为空。{NC}")
                continue
            return new_name
        if choice in {"c", "cancel"}:
            fail("已取消。")
        print(f"{YELLOW}无效输入，请输入 r、n 或 c。{NC}")

def resolve_target_name(index: dict[str, Any], requested_name: str) -> str:
    name = requested_name.strip()
    if not name:
        fail("账号名不能为空。")
    while True:
        existing = find_account(index, name)
        if not existing:
            return name
        next_name = prompt_existing_name_resolution(name)
        if next_name == name:
            return name
        name = next_name.strip()

def load_snapshot(name: str) -> dict[str, Any]:
    try:
        return SNAPSHOT_STORE.load(name)
    except SnapshotStoreError as exc:
        fail(str(exc))

def delete_snapshot(name: str) -> None:
    try:
        SNAPSHOT_STORE.delete(name)
    except SnapshotStoreError as exc:
        fail(str(exc))

def restore_previous_auth(previous_auth: dict[str, Any] | None) -> None:
    if previous_auth is None:
        return
    write_auth(previous_auth)
