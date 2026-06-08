from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .accounts import delete_snapshot, load_snapshot, resolve_target_name, restore_previous_auth, save_snapshot
from .auth import get_access_token, get_account_id, get_current_account_id, get_email, get_plan_expiry, get_plan_type, load_auth, run_codex_login, write_auth
from .core import BLUE, CONFIG_FILE, CYAN, DIM, GREEN, NC, RED, YELLOW, backup_official_config, ensure_state_dir, fail, find_account, find_account_by_id, get_current_name, read_index, resolve_name, restore_official_config, set_current_name, sorted_accounts, write_index
from .doctor import cmd_doctor
from .tui import cmd_tui
from .usage import fetch_usage, fmt_pct, format_duration, format_timestamp, make_bar, parse_window


def cmd_help() -> None:
    print(f"{BLUE}codex-switch (cross-platform){NC}")
    print("")
    print("用法: codex-switch <命令> [参数]")
    print("")
    print("命令:")
    print("  list, ls              列出已保存账号")
    print("  status                查看当前 auth.json 对应的账号")
    print("  save <name>           保存当前已登录账号到指定名称")
    print("  add <name>            登录一个新账号并保存，然后恢复当前登录")
    print("  add-relay <name> <auth> <config>  添加中转站账号（提供 auth.json 和 config.toml 路径）")
    print("  switch, sw <name|n|#n>  切换到指定账号")
    print("  update [name|n|#n]      重新登录并更新指定账号")
    print("  remove, rm <name|n|#n>  删除账号")
    print("  rename <old|n|#n> <new> 重命名账号")
    print("  balance, bal [name|n|#n] 查询额度")
    print("  tui                   交互式 TUI 界面（动态额度、切换、刷新）")
    print("  doctor, diag          检测 Codex / compact / usage 网络链路")
    print("  help                  显示帮助")
    print("")
    print("  n 或 #n 表示 ls 中的序号，如 1、2、#1、#2；Linux shell 中 #1 需要加引号")
    print("")
    print("示例:")
    print("  codex-switch save work")
    print("  codex-switch add work")
    print("  codex-switch add-relay my-relay ~/relay-auth.json ~/relay-config.toml")
    print("  codex-switch switch 2")
    print("  codex-switch balance 1 3")
    print("  codex-switch rm 1 2 3")
    print("  codex-switch doctor")

def cmd_list() -> None:
    index = read_index()
    accounts = sorted_accounts(index)
    if not accounts:
        print(f"{YELLOW}还没有保存任何账号。{NC}")
        print("先运行 `codex-switch save <name>` 或 `codex-switch add <name>`。")
        return

    current_id = get_current_account_id()
    current_name = get_current_name()
    print(f"{BLUE}已保存账号{NC}")
    print("")
    for i, account in enumerate(accounts, start=1):
        marker = f"{GREEN}*{NC}" if (account.get("account_id") == current_id) or (not current_id and account.get("name") == current_name) else " "
        email = ""
        plan = ""
        expiry = ""
        account_type = account.get("type", "official")
        try:
            snap = load_snapshot(str(account.get("name")))
            auth_data = snap["auth"]
            email = get_email(auth_data)
            plan = get_plan_type(auth_data)
            expiry = get_plan_expiry(auth_data)
        except SystemExit:
            auth_data = {}
        type_label = f"{DIM}[中转]{NC} " if account_type == "relay" else ""
        print(f"{marker} {DIM}{i}.{NC} {type_label}{YELLOW}{account.get('name')}{NC}")
        if plan:
            label = f"{plan}" + (f"  至 {expiry}" if expiry else "")
            print(f"    plan:       {label}")
        if email:
            print(f"    email:      {email}")
        print(f"    account_id: {account.get('account_id')}")
        print(f"    saved_at:   {account.get('saved_at')}")
        print("")

def cmd_status() -> None:
    auth = load_auth()
    account_id = get_account_id(auth) or "未知"
    auth_mode = auth.get("auth_mode") or "未知"
    email = get_email(auth) or "未知"
    index = read_index()
    known = find_account_by_id(index, account_id)

    print(f"{BLUE}当前认证状态{NC}")
    if known:
        print(f"name:       {YELLOW}{known.get('name')}{NC}")
    print(f"email:      {email}")
    print(f"account_id: {account_id}")
    print(f"auth_mode:  {auth_mode}")
    if known:
        print("saved:      yes")
    else:
        print(f"saved:      {YELLOW}no{NC}")

def cmd_save(name: str) -> None:
    if not name:
        fail("用法: codex-switch save <name>")
    auth = load_auth()
    account_id = get_account_id(auth)
    index = read_index()

    existing_by_id = find_account_by_id(index, account_id) if account_id else None
    if existing_by_id:
        old_name = str(existing_by_id.get("name"))
        if old_name == name:
            save_snapshot(name, auth)
            print(f"{GREEN}已更新账号 `{name}`。{NC}")
        else:
            existing_by_name = find_account(index, name)
            if existing_by_name:
                fail(f"名称 `{name}` 已被占用，请换一个名字。")
            save_snapshot(name, auth)
            delete_snapshot(old_name)
            index = read_index()
            index["accounts"] = [a for a in index.get("accounts", []) if a.get("name") != old_name]
            write_index(index)
            print(f"{GREEN}已重命名 `{old_name}` -> `{name}`。{NC}")
        print(f"account_id: {account_id}")
        return

    existing_by_name = find_account(index, name)
    if existing_by_name:
        name = resolve_target_name(index, name)
    save_snapshot(name, auth)
    print(f"{GREEN}已保存账号 `{name}`。{NC}")
    print(f"account_id: {account_id}")

def cmd_add(name: str) -> None:
    if not name:
        fail("用法: codex-switch add <name>")
    index = read_index()
    name = resolve_target_name(index, name)
    previous_auth = load_auth() if AUTH_FILE.exists() else None
    try:
        new_auth = run_codex_login()
        account_id = save_snapshot(name, new_auth)
    finally:
        restore_previous_auth(previous_auth)
    print(f"{GREEN}已添加账号 `{name}`。{NC}")
    print(f"account_id: {account_id}")
    if previous_auth is not None:
        print("当前登录状态已恢复。")

def cmd_add_relay(name: str, auth_path: str, config_path: str) -> None:
    if not name:
        fail("用法: codex-switch add-relay <name> <auth.json路径> <config.toml路径>")
    auth_p = Path(auth_path).expanduser().resolve()
    config_p = Path(config_path).expanduser().resolve()
    if not auth_p.exists():
        fail(f"auth 文件不存在: {auth_p}")
    if not config_p.exists():
        fail(f"config 文件不存在: {config_p}")
    try:
        auth = json.loads(auth_p.read_text())
    except Exception as exc:
        fail(f"读取 auth 文件失败: {exc}")
    if not isinstance(auth, dict):
        fail("auth 文件格式错误：顶层应为 JSON 对象。")
    config_toml = config_p.read_text()
    index = read_index()
    name = resolve_target_name(index, name)
    account_id = save_snapshot(name, auth, config_toml)
    print(f"{GREEN}已添加中转账号 `{name}`。{NC}")
    print(f"account_id: {account_id}")

def cmd_switch(name: str) -> None:
    if not name:
        fail("用法: codex-switch switch <name|#n>")
    name = resolve_name(read_index(), name)
    snap = load_snapshot(name)
    auth = snap["auth"]
    config_toml = snap.get("config_toml")
    account = find_account(read_index(), name)
    if not account:
        fail(f"账号 `{name}` 不在索引中。")
    account_type = account.get("type", "official")

    if account_type == "relay":
        if config_toml:
            backup_official_config()
            CONFIG_FILE.write_text(config_toml)
        write_auth(auth)
    else:
        write_auth(auth)
        restore_official_config()

    set_current_name(name)
    print(f"{GREEN}已切换到 `{name}`。{NC}")
    print(f"account_id: {get_account_id(auth)}")

def cmd_remove(names: list[str]) -> None:
    if not names:
        fail(
            "用法: codex-switch remove <name|n|#n> [name|n|#n ...]\n"
            "提示：Linux shell 会把未加引号的 #1 当作注释。请使用 `codex-switch rm 1`，"
            "或写成 `codex-switch rm '#1'`。"
        )
    index = read_index()
    resolved = [resolve_name(index, n) for n in names]
    for name in resolved:
        if not find_account(index, name):
            fail(f"账号 `{name}` 不存在。")
    for name in resolved:
        delete_snapshot(name)
        index["accounts"] = [item for item in index.get("accounts", []) if item.get("name") != name]
        print(f"{GREEN}已删除账号 `{name}`。{NC}")
    write_index(index)

def cmd_rename(old_name: str, new_name: str) -> None:
    if not old_name or not new_name:
        fail("用法: codex-switch rename <old|#n> <new>")
    index = read_index()
    old_name = resolve_name(index, old_name)
    account = find_account(index, old_name)
    if not account:
        fail(f"账号 `{old_name}` 不存在。")
    if find_account(index, new_name):
        fail(f"账号 `{new_name}` 已存在。")
    snap = load_snapshot(old_name)
    save_snapshot(new_name, snap["auth"], snap.get("config_toml"))
    delete_snapshot(old_name)
    index = read_index()
    index["accounts"] = [item for item in index.get("accounts", []) if item.get("name") != old_name]
    write_index(index)
    print(f"{GREEN}已重命名 `{old_name}` -> `{new_name}`。{NC}")

def cmd_update(name: str | None) -> None:
    index = read_index()
    if not name:
        current_id = get_current_account_id()
        current = find_account_by_id(index, current_id)
        if not current:
            fail("当前账号不在已保存列表中。请显式传入账号名。")
        name = str(current["name"])
    else:
        name = resolve_name(index, name)

    if not find_account(index, name):
        fail(f"账号 `{name}` 不存在。")

    previous_auth = load_auth() if AUTH_FILE.exists() else None
    try:
        write_auth(load_snapshot(name)["auth"])
        updated_auth = run_codex_login()
        account_id = save_snapshot(name, updated_auth)
    finally:
        restore_previous_auth(previous_auth)
    print(f"{GREEN}已更新账号 `{name}`。{NC}")
    print(f"account_id: {account_id}")
    if previous_auth is not None:
        print("当前登录状态已恢复。")

def print_usage_for_auth(name: str, auth: dict[str, Any], *, is_current: bool = False, seq: int | None = None) -> None:
    token = get_access_token(auth)
    plan = get_plan_type(auth)
    expiry = get_plan_expiry(auth)
    marker = f"{GREEN}*{NC}" if is_current else " "
    prefix = f"{DIM}{seq}.{NC} " if seq else ""
    if not token:
        print(f"\n{marker} {prefix}{CYAN}▸ {name}{NC}")
        print(f"  {RED}无有效 access_token，可能需要重新登录。{NC}")
        return

    result = fetch_usage(token)
    if result.payload is None:
        print(f"\n{marker} {prefix}{CYAN}▸ {name} ({plan}){NC}")
        if result.error_kind == "auth":
            print(f"  {RED}查询失败：当前登录已失效，需要重新登录。{NC}")
        elif result.error_kind in {"network_tls", "network", "timeout"}:
            print(f"  {YELLOW}查询失败：{result.error_message}{NC}")
            print(f"  {DIM}这更像是当前命令行到 chatgpt.com 的网络问题，不一定是账号失效。{NC}")
        else:
            print(f"  {RED}查询失败：{result.error_message or '未知错误'}{NC}")
        return

    payload = result.payload
    api_plan = payload.get("plan_type")
    if api_plan and isinstance(api_plan, str):
        plan = api_plan
    rate_limit = payload.get("rate_limit")
    rate_limit = rate_limit if isinstance(rate_limit, dict) else {}
    primary = parse_window(rate_limit.get("primary_window"))
    secondary = parse_window(rate_limit.get("secondary_window"))

    label = f"{name} ({plan}" + (f"  至 {expiry}" if expiry else "") + ")" if plan else name
    print(f"\n{marker} {prefix}{CYAN}▸ {label}{NC}")

    def color_for(used_percent: int | None) -> str:
        if used_percent is None:
            return NC
        if used_percent >= 80:
            return RED
        if used_percent >= 50:
            return YELLOW
        return GREEN

    if secondary.used_percent is None and primary.used_percent is not None:
        print(
            f"  main  {color_for(primary.used_percent)}{make_bar(primary.remaining_percent)} "
            f"{fmt_pct(primary.remaining_percent)}剩余{NC}  重置: "
            f"{format_duration(primary.reset_after_seconds)} ({format_timestamp(primary.reset_at)})"
        )
        return

    print(
        f"  5h    {color_for(primary.used_percent)}{make_bar(primary.remaining_percent)} "
        f"{fmt_pct(primary.remaining_percent)}剩余{NC}  重置: "
        f"{format_duration(primary.reset_after_seconds)} ({format_timestamp(primary.reset_at)})"
    )
    print(
        f"  week  {color_for(secondary.used_percent)}{make_bar(secondary.remaining_percent)} "
        f"{fmt_pct(secondary.remaining_percent)}剩余{NC}  重置: "
        f"{format_duration(secondary.reset_after_seconds)} ({format_timestamp(secondary.reset_at)})"
    )

def cmd_balance(names: list[str] | None) -> None:
    index = read_index()
    current_id = get_current_account_id()
    if names:
        resolved = [resolve_name(index, n) for n in names]
        for name in resolved:
            account = find_account(index, name)
            if not account:
                fail(f"账号 `{name}` 不存在。")
            if account.get("type") == "relay":
                marker = f"{GREEN}*{NC}" if account.get("account_id") == current_id else " "
                print(f"\n{marker} {CYAN}▸ {name} {DIM}[中转]{NC}")
                print(f"  {DIM}中转站账号，不支持余额查询{NC}")
                continue
            print_usage_for_auth(
                name,
                load_snapshot(name)["auth"],
                is_current=account.get("account_id") == current_id,
            )
        return

    accounts = sorted_accounts(index)
    if not accounts:
        print(f"{YELLOW}还没有保存任何账号。{NC}")
        return
    for i, account in enumerate(accounts, start=1):
        name = str(account["name"])
        if account.get("type") == "relay":
            marker = f"{GREEN}*{NC}" if account.get("account_id") == current_id else " "
            prefix = f"{DIM}{i}.{NC} "
            print(f"\n{marker} {prefix}{CYAN}▸ {name} {DIM}[中转]{NC}")
            print(f"  {DIM}中转站账号，不支持余额查询{NC}")
            continue
        print_usage_for_auth(
            name,
            load_snapshot(name)["auth"],
            is_current=account.get("account_id") == current_id,
            seq=i,
        )

def main(argv: list[str]) -> int:
    ensure_state_dir()
    command = argv[1] if len(argv) > 1 else "help"
    arg1 = argv[2] if len(argv) > 2 else ""
    arg2 = argv[3] if len(argv) > 3 else ""
    arg3 = argv[4] if len(argv) > 4 else ""

    try:
        if command in {"help", "-h", "--help"}:
            cmd_help()
        elif command in {"list", "ls"}:
            cmd_list()
        elif command == "status":
            cmd_status()
        elif command == "save":
            cmd_save(arg1)
        elif command == "add":
            cmd_add(arg1)
        elif command == "add-relay":
            cmd_add_relay(arg1, arg2, arg3)
        elif command in {"switch", "sw"}:
            cmd_switch(arg1)
        elif command == "update":
            cmd_update(arg1 or None)
        elif command in {"remove", "rm"}:
            cmd_remove(argv[2:])
        elif command == "rename":
            cmd_rename(arg1, arg2)
        elif command in {"balance", "bal"}:
            cmd_balance(argv[2:] or None)
        elif command in {"doctor", "diag"}:
            return cmd_doctor()
        elif command == "tui":
            cmd_tui()
        else:
            fail(f"未知命令: {command}")
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else str(exc)
        fail(f"命令执行失败: {stderr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
