from __future__ import annotations

import threading
import time
import shutil
from typing import Any

from .accounts import load_snapshot
from .auth import get_access_token, get_account_id, get_current_account_id, get_current_name, get_plan_expiry, get_plan_type, load_auth, write_auth
from .core import CONFIG_FILE, YELLOW, backup_official_config, fail, find_account, read_index, restore_official_config, set_current_name, sorted_accounts
from .doctor import classify_diagnostics, get_route_summary, list_proxy_processes, run_doctor_attempt
from .models import DiagnosticStep
from .network import get_proxy_info
from .usage import fetch_usage, format_duration, format_timestamp, parse_window

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


def _tui_fetch_one(name: str, state: dict, lock: threading.Lock) -> None:
    token = None
    plan = ""
    expiry = ""
    account_type = "official"
    try:
        snap = load_snapshot(name)
        auth_data = snap["auth"]
        token = get_access_token(auth_data)
        plan = get_plan_type(auth_data)
        expiry = get_plan_expiry(auth_data)
        acct = find_account(read_index(), name)
        if acct:
            account_type = acct.get("type", "official")
    except SystemExit:
        pass
    if account_type == "relay":
        with lock:
            state["balances"][name] = {"plan": plan, "expiry": expiry, "primary": None, "secondary": None, "error": None, "relay": True}
            state["loading"].discard(name)
            state["dirty"] = True
        return
    result: dict[str, Any] = {"plan": plan, "expiry": expiry, "primary": None, "secondary": None, "error": None, "relay": False}
    if token:
        usage = fetch_usage(token)
        if usage.payload is not None:
            rl = usage.payload.get("rate_limit", {})
            if isinstance(rl, dict):
                result["primary"] = parse_window(rl.get("primary_window"))
                result["secondary"] = parse_window(rl.get("secondary_window"))
            api_plan = usage.payload.get("plan_type")
            if api_plan and isinstance(api_plan, str):
                result["plan"] = api_plan
        else:
            result["error"] = usage.error_message or "未知错误"
    else:
        result["error"] = "无有效 token"
    with lock:
        state["balances"][name] = result
        state["loading"].discard(name)
        state["dirty"] = True

def _tui_fetch_all(accounts: list[dict[str, Any]], state: dict, lock: threading.Lock) -> None:
    for account in accounts:
        name = str(account["name"])
        with lock:
            state["loading"].add(name)
            state["dirty"] = True
        threading.Thread(target=_tui_fetch_one, args=(name, state, lock), daemon=True).start()

def _tui_bar(remaining_pct: int | None, width: int = 20) -> str:
    if remaining_pct is None:
        return SP * width
    filled = min(max(round(remaining_pct / 100 * width), 0), width)
    return "█" * filled + "░" * (width - filled)

def _tui_color_pct(pct: int | None) -> int:
    if pct is None:
        return 0
    if pct <= 20:
        return 1
    if pct <= 50:
        return 2
    return 3

def cmd_tui() -> None:
    try:
        import curses as _curses
    except ImportError:
        fail("当前 Python 环境没有 curses，无法启动 TUI。请使用 `list`、`switch`、`balance` 等命令。")
    import time as _time

    index = read_index()
    accounts = sorted_accounts(index)
    if not accounts:
        print(f"{YELLOW}还没有保存任何账号。{NC}")
        return

    current_id = get_current_account_id()
    current_name = get_current_name()
    lock = threading.Lock()
    state: dict[str, Any] = {
        "selected": 0,
        "ri": 2,
        "countdown": REFRESH_OPTIONS[2],
        "balances": {},
        "loading": set(),
        "dirty": True,
        "running": True,
        "current_id": current_id,
        "current_name": current_name,
        "msg": "",
        "msg_t": 0.0,
    }

    _tui_fetch_all(accounts, state, lock)

    def _dw(s: str) -> int:
        import unicodedata as _ud
        w = 0
        for ch in s:
            eaw = _ud.east_asian_width(ch)
            w += 2 if eaw in ("W", "F") else 1
        return w

    def _pad_left(text: str, width: int, fill: str = " ") -> str:
        d = _dw(text)
        return text + fill * max(0, width - d)

    def _pad_right(text: str, width: int, fill: str = " ") -> str:
        d = _dw(text)
        return fill * max(0, width - d) + text

    def _pad_center(text: str, width: int, fill: str = " ") -> str:
        d = _dw(text)
        gap = max(0, width - d)
        left = gap // 2
        return fill * left + text + fill * (gap - left)

    def _safe_add(stdscr: Any, row: int, col: int, text: str, attr: int = 0) -> None:
        h, w = stdscr.getmaxyx()
        if row < 0 or row >= h or col >= w:
            return
        max_cols = w - col
        if max_cols <= 0:
            return
        if _dw(text) <= max_cols:
            truncated = text
        else:
            truncated = ""
            tw = 0
            for ch in text:
                cw = 2 if ch in ("█", "░", "●") or _dw(ch) > 1 else 1
                if tw + cw > max_cols:
                    break
                truncated += ch
                tw += cw
        try:
            stdscr.addstr(row, col, truncated, attr)
        except _curses.error:
            pass

    def _draw(stdscr: Any) -> None:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        with lock:
            sel = state["selected"]
            ri = state["ri"]
            cd = state["countdown"]
            bals = dict(state["balances"])
            loading = set(state["loading"])
            cid = state["current_id"]
            current_name = state.get("current_name", "")
            msg = state["msg"]
            mt = state["msg_t"]
            state["dirty"] = False

        il = REFRESH_LABELS[ri]
        cm, cs = divmod(cd, 60)
        inner = w - 2

        left = " codex-switch "
        right = f" 刷新间隔 {il} │ 下次刷新 {cm}:{cs:02d} "
        fill_n = max(0, inner - _dw(left) - _dw(right))
        header = left + HZ * fill_n + right
        _safe_add(stdscr, 0, 0, TL + _pad_center(header, inner, HZ) + TR, _curses.A_BOLD)

        row = 1
        for i, account in enumerate(accounts):
            if row + 4 >= h - 1:
                break
            name = str(account["name"])
            is_cur = account.get("account_id") == cid or (not cid and account.get("name") == current_name)
            is_sel = i == sel
            is_load = name in loading
            is_relay = account.get("type") == "relay"
            bal = bals.get(name, {})
            plan = bal.get("plan", "")
            expiry = bal.get("expiry", "")

            tag = " ●" if is_cur else "  "
            num = f"{i+1}."
            relay_tag = " [中转]" if is_relay else ""
            plan_s = f"  {plan}" + (f"  至 {expiry}" if expiry else "") if plan and not is_relay else ""
            name_part = f"{num} {name}{relay_tag}{plan_s}"
            is_first = i == 0
            is_last = i == len(accounts) - 1
            lc = LJ if not is_first else VT
            rc = RJ if not is_first else VT

            if is_sel:
                line = f"{tag} {name_part}"
                _safe_add(stdscr, row, 0, lc, _curses.A_BOLD)
                line_w = _dw(line)
                col_end = 2 + line_w + 1
                _safe_add(stdscr, row, 1, f" {line} ", _curses.A_REVERSE)
                if col_end < w - 1:
                    _safe_add(stdscr, row, col_end, " " * (w - 1 - col_end), _curses.A_REVERSE)
                _safe_add(stdscr, row, w - 1, rc, _curses.A_BOLD)
            else:
                attr_name = _curses.A_BOLD if is_cur else 0
                line = f"{tag} {name_part}"
                _safe_add(stdscr, row, 0, VT)
                _safe_add(stdscr, row, 2, line, attr_name)
                _safe_add(stdscr, row, w - 1, VT)
            row += 1

            if is_load:
                loading_text = f"  {SP * 3} loading"
                _safe_add(stdscr, row, 0, VT)
                _safe_add(stdscr, row, 2, loading_text)
                _safe_add(stdscr, row, w - 1, VT)
            elif is_relay:
                relay_text = "  ◈ 中转站 · 不支持余额查询"
                _safe_add(stdscr, row, 0, VT)
                _safe_add(stdscr, row, 2, relay_text, _curses.A_DIM)
                _safe_add(stdscr, row, w - 1, VT)
            elif bal.get("error"):
                err_text = f"  ✗ {bal['error']}"
                _safe_add(stdscr, row, 0, VT)
                _safe_add(stdscr, row, 2, err_text, _curses.color_pair(1))
                _safe_add(stdscr, row, w - 1, VT)
            elif bal.get("primary"):
                pri = bal["primary"]
                sec = bal.get("secondary")
                rp = pri.remaining_percent
                bw = min(20, max(5, inner - 52))
                bar = _tui_bar(rp, bw)
                pct_s = f"{rp:>3}%" if rp is not None else " ??%"
                reset_s = format_duration(pri.reset_after_seconds)
                reset_at_s = format_timestamp(pri.reset_at)
                line_pri = f"  5h  {pct_s} {bar}  ↻ {reset_s} ({reset_at_s})"
                cp = _tui_color_pct(rp)
                attr = _curses.color_pair(cp) if cp else 0
                _safe_add(stdscr, row, 0, VT)
                _safe_add(stdscr, row, 2, line_pri, attr)
                _safe_add(stdscr, row, w - 1, VT)
                row += 1
                if sec and sec.used_percent is not None and row + 1 < h - 1:
                    rp2 = sec.remaining_percent
                    bar2 = _tui_bar(rp2, bw)
                    pct_s2 = f"{rp2:>3}%" if rp2 is not None else " ??%"
                    reset_s2 = format_duration(sec.reset_after_seconds)
                    reset_at_s2 = format_timestamp(sec.reset_at)
                    line_sec = f"  wk  {pct_s2} {bar2}  ↻ {reset_s2} ({reset_at_s2})"
                    cp2 = _tui_color_pct(rp2)
                    attr2 = _curses.color_pair(cp2) if cp2 else 0
                    _safe_add(stdscr, row, 0, VT)
                    _safe_add(stdscr, row, 2, line_sec, attr2)
                    _safe_add(stdscr, row, w - 1, VT)
                else:
                    row -= 1
            else:
                _safe_add(stdscr, row, 0, VT)
                _safe_add(stdscr, row, 2, "  ─")
                _safe_add(stdscr, row, w - 1, VT)

            row += 1

            lc2 = LJ if not is_last else BL
            rc2 = RJ if not is_last else BR
            _safe_add(stdscr, row, 0, lc2 + HZ * inner + rc2)
            row += 1

        now = _time.time()
        if msg and now - mt < 3:
            bot = f" {msg}"
        else:
            bot = " ↑↓ 选择 │ Enter 切换账号 │ r 刷新额度 │ d 网络检测 │ +/- 调整刷新间隔 │ q 退出 "
        _safe_add(stdscr, h - 1, 0, " " + bot[:inner].center(inner), _curses.A_DIM)
        stdscr.refresh()

    def _run_doctor_panel(stdscr: Any) -> None:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        inner = w - 2

        token = None
        try:
            token = get_access_token(load_auth())
        except SystemExit:
            pass

        _safe_add(stdscr, 0, 0, TL + _pad_center(" Codex 网络检测中... ", inner, HZ) + TR, _curses.A_BOLD)
        _safe_add(stdscr, 1, 0, VT + " " * inner + VT)
        _safe_add(stdscr, 2, 0, BL + HZ * inner + BR)
        stdscr.refresh()

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

        lines: list[tuple[str, int]] = []

        ov_color = {1: _curses.A_BOLD | _curses.color_pair(3), 2: _curses.A_BOLD | _curses.color_pair(2), 3: _curses.A_BOLD | _curses.color_pair(1)}
        ov_cp = {1: 3, 2: 2, 3: 1}
        ov_idx = 1 if overall == "healthy" else (2 if overall == "warning" else 3)
        lines.append((f"  status: {overall}", _curses.color_pair(ov_cp[ov_idx]) | _curses.A_BOLD))
        lines.append((f"  auth_token: {'yes' if token else 'no'}", 0))
        if codex_path:
            lines.append((f"  codex: {codex_path}", 0))
        if proxy_info:
            lines.append((f"  proxy: {proxy_info.display()}", 0))
        if route_summary:
            lines.append((f"  route: {route_summary}", 0))
        if proxy_processes:
            lines.append((f"  proxy_proc: {proxy_processes[0]}", 0))
            for pp in proxy_processes[1:]:
                lines.append((f"              {pp}", 0))
        if flags:
            lines.append((f"  flags: {', '.join(flags)}", 0))
        lines.append(("", 0))

        for ai, attempt in enumerate(attempts, start=1):
            lines.append((f"  [attempt {ai}]", _curses.A_BOLD))
            for step in attempt:
                marker = "ok" if step.ok else "fail"
                m_attr = _curses.color_pair(3) if step.ok else _curses.color_pair(1)
                lat = f"{step.latency_ms:.0f}ms" if step.latency_ms is not None else "-"
                suffix_parts = []
                if step.status is not None:
                    suffix_parts.append(f"status={step.status}")
                if step.reason:
                    suffix_parts.append(step.reason)
                if step.detail:
                    suffix_parts.append(step.detail)
                suffix = " | ".join(suffix_parts)
                if suffix:
                    line = f"    {marker:<5} {step.name:<36} {lat:<8} {suffix}"
                else:
                    line = f"    {marker:<5} {step.name:<36} {lat}"
                lines.append((line, m_attr))
            if ai != len(attempts):
                lines.append(("", 0))

        box_h = min(len(lines) + 2, h - 2)
        stdscr.erase()
        _safe_add(stdscr, 0, 0, TL + _pad_center(f" Codex 网络检测 ({overall}) ", inner, HZ) + TR, _curses.A_BOLD)

        for idx in range(box_h - 2):
            r = idx + 1
            _safe_add(stdscr, r, 0, VT)
            if idx < len(lines):
                text, attr = lines[idx]
                _safe_add(stdscr, r, 1, f" {text}", attr)
            _safe_add(stdscr, r, w - 1, VT)

        _safe_add(stdscr, box_h - 1, 0, BL + HZ * inner + BR)
        _safe_add(stdscr, h - 1, 0, " 按任意键返回 ".center(w), _curses.A_DIM)
        stdscr.refresh()

        stdscr.nodelay(False)
        try:
            stdscr.getch()
        except Exception:
            pass
        stdscr.nodelay(True)
        stdscr.timeout(1000)
        with lock:
            state["dirty"] = True

    def _main(stdscr: Any) -> None:
        _curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(1000)
        try:
            _curses.init_pair(1, _curses.COLOR_RED, 0)
            _curses.init_pair(2, _curses.COLOR_YELLOW, 0)
            _curses.init_pair(3, _curses.COLOR_GREEN, 0)
        except Exception:
            pass
        last = _time.time()
        while state["running"]:
            _draw(stdscr)
            try:
                ch = stdscr.getch()
            except Exception:
                ch = -1
            if ch in (ord("q"), ord("Q")):
                state["running"] = False
                break
            elif ch in (_curses.KEY_UP, ord("k"), ord("K")):
                with lock:
                    state["selected"] = max(0, state["selected"] - 1)
                    state["dirty"] = True
            elif ch in (_curses.KEY_DOWN, ord("j"), ord("J")):
                with lock:
                    state["selected"] = min(len(accounts) - 1, state["selected"] + 1)
                    state["dirty"] = True
            elif ch in (ord("\n"), ord("\r")):
                name = str(accounts[state["selected"]]["name"])
                acct = find_account(read_index(), name)
                try:
                    snap = load_snapshot(name)
                    auth_data = snap["auth"]
                    config_toml = snap.get("config_toml")
                    if acct and acct.get("type") == "relay":
                        if config_toml:
                            backup_official_config()
                            CONFIG_FILE.write_text(config_toml)
                        write_auth(auth_data)
                    else:
                        write_auth(auth_data)
                        restore_official_config()
                    state["current_id"] = get_account_id(auth_data) or (acct.get("account_id", "") if acct else "")
                    state["current_name"] = name
                    set_current_name(name)
                    state["msg"] = f"✓ 已切换到 {name}"
                    state["msg_t"] = _time.time()
                except SystemExit:
                    state["msg"] = "✗ 切换失败"
                    state["msg_t"] = _time.time()
                with lock:
                    state["dirty"] = True
            elif ch in (ord("r"), ord("R")):
                with lock:
                    state["countdown"] = REFRESH_OPTIONS[state["ri"]]
                    state["dirty"] = True
                _tui_fetch_all(accounts, state, lock)
                state["msg"] = "⟳ 刷新中..."
                state["msg_t"] = _time.time()
            elif ch in (ord("d"), ord("D")):
                _run_doctor_panel(stdscr)
            elif ch in (ord("+"), ord("=")):
                with lock:
                    state["ri"] = min(len(REFRESH_OPTIONS) - 1, state["ri"] + 1)
                    state["countdown"] = REFRESH_OPTIONS[state["ri"]]
                    state["dirty"] = True
            elif ch in (ord("-"), ord("_")):
                with lock:
                    state["ri"] = max(0, state["ri"] - 1)
                    state["countdown"] = REFRESH_OPTIONS[state["ri"]]
                    state["dirty"] = True
            now = _time.time()
            elapsed = now - last
            last = now
            with lock:
                state["countdown"] = max(0, state["countdown"] - int(elapsed))
                if state["countdown"] <= 0:
                    state["countdown"] = REFRESH_OPTIONS[state["ri"]]
                    state["dirty"] = True
                    need_fetch = True
                else:
                    need_fetch = False
            if need_fetch:
                _tui_fetch_all(accounts, state, lock)
            if state["dirty"]:
                _draw(stdscr)

    try:
        _curses.wrapper(_main)
    except KeyboardInterrupt:
        pass
