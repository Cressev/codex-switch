# codex-switch

Codex CLI 多账号管理工具，支持添加、切换、删除任意数量的 ChatGPT / Codex 账号，并查询各账号额度。

当前 `omini` 分支以 macOS 正在使用的功能为基准，补齐 Linux / Windows 的自动平台检测和文件存储 fallback。

## 功能

- **多账号管理** — 添加、切换、删除、重命名账号
- **一键登录** — 添加/更新账号时自动引导浏览器登录，无需手动 `codex login`
- **余额查询** — 查询所有账号或指定账号的 5 小时 / 周 余额，可视化进度条
- **中转账号** — 支持同时切换 `auth.json` 和 `config.toml`
- **TUI** — 交互式账号切换、额度刷新、网络诊断
- **网络诊断** — 检测 DNS / TCP / TLS / Codex API / compact / WebSocket 链路
- **登录状态恢复** — 添加/更新账号后自动恢复之前的登录状态，不干扰当前使用
- **跨平台存储** — macOS 默认使用 Keychain；Linux / Windows 默认使用用户数据目录下的文件存储

## 安装

### 1. 获取代码

```bash
git clone https://github.com/Cressev/codex-switch.git
cd codex-switch
git switch omini
```

### 2. 安装到 PATH

macOS / Linux:

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/codex-switch" ~/.local/bin/codex-switch
chmod +x codex-switch
```

如果你的 shell 没有加载 `~/.local/bin`，把下面这行加入 `~/.zshrc` 或 `~/.bashrc`：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

macOS Homebrew 用户也可以软链到 `/opt/homebrew/bin`：

```bash
ln -sf "$PWD/codex-switch" /opt/homebrew/bin/codex-switch
```

Windows PowerShell:

```powershell
git clone https://github.com/Cressev/codex-switch.git
cd codex-switch
git switch omini

$target = "$env:USERPROFILE\bin"
New-Item -ItemType Directory -Force -Path $target | Out-Null
Copy-Item .\codex-switch .\codex-switch.cmd $target -Force
```

然后把 `%USERPROFILE%\bin` 加到用户 PATH。也可以不安装，直接在仓库目录运行：

```powershell
python .\codex-switch --help
```

### 3. 验证

```bash
codex-switch --help
codex-switch status
```

## 使用

```
codex-switch <命令> [参数]

命令:
  list, ls              列出已保存账号
  status                查看当前 auth.json 对应的账号
  save <name>           保存当前已登录账号到指定名称
  add <name>            登录一个新账号并保存，然后恢复当前登录
  add-relay <name> <auth> <config>  添加中转站账号
  switch, sw <name|#n>  切换到指定账号
  update [name|#n]      重新登录并更新指定账号
  remove, rm <name|#n>  删除账号
  rename <old|#n> <new> 重命名账号
  balance, bal [name|#n] 查询额度
  tui                   交互式 TUI 界面
  doctor, diag          检测 Codex 网络链路
  help                  显示帮助
```

### 常用示例

第一次使用前，先确保 Codex CLI 已经能正常登录：

```bash
codex login
```

```bash
# 保存当前已经登录的账号
codex-switch save work

# 添加账号 (自动打开浏览器登录)
codex-switch add work

# 添加中转账号，同时保存 auth.json 和 config.toml
codex-switch add-relay relay ~/relay-auth.json ~/relay-config.toml

# 列出所有账号
codex-switch list

# 按名称或序号切换账号
codex-switch sw work
codex-switch sw '#1'

# 查询所有账号余额
codex-switch balance

# 查询指定账号余额
codex-switch bal work

# 重命名 / 删除账号
codex-switch rename work main
codex-switch rm old-account

# 打开交互式界面
codex-switch tui

# 更新账号认证 (token 过期时)
codex-switch update work

# 诊断网络链路
codex-switch doctor
```

### 命令说明

- `save <name>`: 把当前 `~/.codex/auth.json` 保存为指定账号。
- `add <name>`: 临时运行 `codex login` 添加新账号，完成后恢复原来的登录状态。
- `add-relay <name> <auth> <config>`: 保存中转账号，切换时会同时写入 `auth.json` 和 `config.toml`。
- `switch <name|#n>`: 切换账号，`#n` 是 `list` 中显示的序号。
- `update [name|#n]`: 重新登录并刷新某个账号的 token。
- `balance [name|#n]`: 查询额度；中转账号会跳过余额查询。
- `tui`: 进入交互式界面，支持方向键选择、Enter 切换、`r` 刷新、`d` 诊断、`q` 退出。
- `doctor`: 检测当前命令行到 Codex 相关接口的网络链路。

## 依赖

- [Codex CLI](https://github.com/openai/codex) — `codex` 命令需已安装
- Python 3.10+
- macOS / Linux TUI 需要 Python `curses`；Windows 没有 `curses` 时可继续使用普通命令。

## 存储位置

- macOS: `~/Library/Application Support/codex-switch-mac` + Keychain
- Linux: `$XDG_DATA_HOME/codex-switch` 或 `~/.local/share/codex-switch`
- Windows: `%APPDATA%\\codex-switch`

可用环境变量覆盖：

- `CODEX_SWITCH_STATE_DIR`: 指定状态目录
- `CODEX_SWITCH_STORE=file|keychain|auto`: 指定账号快照存储方式

macOS 默认沿用 Keychain，因此已有 `mac-relay` 分支保存过的账号可以继续读取。Linux / Windows 默认使用文件存储，新保存的快照会写入上面的用户数据目录。

## 升级

如果你用软链安装，更新代码后命令会自动使用新版：

```bash
cd codex-switch
git pull
git switch omini
```

## 项目结构

```
codex-switch              # 薄入口，负责导入 package 并运行 main()
codex_switch/core.py      # 路径、索引、颜色、通用工具
codex_switch/auth.py      # auth.json 读写和 token/JWT 解析
codex_switch/accounts.py  # 账号快照保存、读取、删除
codex_switch/storage.py   # Keychain / 文件存储后端
codex_switch/usage.py     # 额度查询和格式化
codex_switch/network.py   # 代理、TLS、HTTP 基础能力
codex_switch/doctor.py    # 网络诊断命令
codex_switch/tui.py       # 交互式界面
codex_switch/commands.py  # CLI 命令编排
```

## License

MIT
