#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import platform
import shutil
import stat
import sys
from pathlib import Path


APP_NAME = "codex-switch"


def is_windows() -> bool:
    return sys.platform.startswith("win")


def default_target_dir() -> Path:
    if is_windows():
        return Path.home() / "bin"
    return Path.home() / ".local" / "bin"


def path_entries() -> list[Path]:
    entries: list[Path] = []
    for raw in os.environ.get("PATH", "").split(os.pathsep):
        if raw:
            entries.append(Path(raw).expanduser())
    return entries


def path_contains(directory: Path) -> bool:
    try:
        target = directory.expanduser().resolve()
    except OSError:
        target = directory.expanduser()
    for entry in path_entries():
        try:
            if entry.resolve() == target:
                return True
        except OSError:
            if entry == target:
                return True
    return False


def ask_yes_no(prompt: str, *, default: bool) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{prompt} [{suffix}]: ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("请输入 y 或 n。")


def ensure_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_unix(source_dir: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / APP_NAME
    ensure_executable(source)
    link = target_dir / APP_NAME
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(source)
    return link


def install_windows(source_dir: Path, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    launcher = target_dir / f"{APP_NAME}.cmd"
    source = source_dir / APP_NAME
    launcher.write_text(f'@echo off\r\npython "{source}" %*\r\n')
    return launcher


def verify_install(command_name: str) -> bool:
    return shutil.which(command_name) is not None


def print_path_hint(target_dir: Path) -> None:
    if is_windows():
        print("")
        print("PATH 尚未包含安装目录。请把下面目录加入用户 PATH 后重新打开终端：")
        print(f"  {target_dir}")
        print("")
        print("PowerShell 可执行：")
        print(
            "  [Environment]::SetEnvironmentVariable("
            '"Path", $env:Path + ";'
            f"{target_dir}"
            '", "User")'
        )
        return

    shell_name = Path(os.environ.get("SHELL", "")).name
    profile = "~/.zshrc" if shell_name == "zsh" else "~/.bashrc"
    print("")
    print("PATH 尚未包含安装目录。请把下面这行加入你的 shell 配置后重新打开终端：")
    print(f'  export PATH="{target_dir}:$PATH"')
    print("")
    print(f"常见位置: {profile}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install codex-switch into a PATH directory.")
    parser.add_argument(
        "--target",
        type=Path,
        default=default_target_dir(),
        help="安装启动器的目录，默认 macOS/Linux 为 ~/.local/bin，Windows 为 ~/bin。",
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="跳过确认，直接安装。",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_dir = Path(__file__).resolve().parent
    target_dir = args.target.expanduser().resolve()

    source = source_dir / APP_NAME
    package_dir = source_dir / "codex_switch"
    if not source.exists() or not package_dir.exists():
        print("安装失败：请在 codex-switch 源码目录中运行 install.py。", file=sys.stderr)
        return 1

    system = platform.system() or sys.platform
    print(f"{APP_NAME} 安装向导")
    print(f"系统:   {system}")
    print(f"源码:   {source_dir}")
    print(f"目标:   {target_dir}")
    print(f"Python: {sys.version.split()[0]}")

    if sys.version_info < (3, 9):
        print("安装失败：需要 Python 3.9 或更高版本。", file=sys.stderr)
        return 1

    if not args.yes and not ask_yes_no("继续安装?", default=True):
        print("已取消。")
        return 0

    if is_windows():
        launcher = install_windows(source_dir, target_dir)
        command_name = f"{APP_NAME}.cmd"
    else:
        launcher = install_unix(source_dir, target_dir)
        command_name = APP_NAME

    print("")
    print("安装完成。")
    print(f"启动器: {launcher}")

    if path_contains(target_dir):
        found = verify_install(command_name)
        print(f"PATH:   已包含目标目录{'，命令可用' if found else ''}")
        print("")
        print("现在可以运行：")
        print(f"  {APP_NAME} --help")
        print(f"  {APP_NAME} status")
    else:
        print_path_hint(target_dir)
        print("")
        print("当前终端也可以直接运行：")
        if is_windows():
            print(f"  {launcher} --help")
        else:
            print(f"  {launcher} --help")

    if shutil.which("codex") is None:
        print("")
        print("提示：未在 PATH 中找到 Codex CLI。安装 Codex CLI 后，先运行 `codex login`。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
