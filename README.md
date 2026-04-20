# codex-switch

Codex CLI 多账号管理工具，支持添加、切换、删除任意数量的 ChatGPT Plus 账号，并查询各账号余额。

## 功能

- **多账号管理** — 添加、切换、删除、重命名账号
- **一键登录** — 添加/更新账号时自动引导浏览器登录，无需手动 `codex login`
- **余额查询** — 查询所有账号或指定账号的 5 小时 / 周 余额，可视化进度条
- **登录状态恢复** — 添加/更新账号后自动恢复之前的登录状态，不干扰当前使用

## 安装

```bash
# 克隆仓库
git clone https://github.com/Cressev/codex-switch.git
cd codex-switch

# 复制到 PATH 中的目录
cp codex-switch codex-balance-helper ~/.local/bin/
chmod +x ~/.local/bin/codex-switch ~/.local/bin/codex-balance-helper
```

> 也可以复制到 `/usr/local/bin/` 等其他已在 PATH 中的目录。

## 使用

```
codex-switch <命令> [参数]

命令:
  list, ls            列出所有已保存的账号
  switch, sw <name>   切换到指定账号
  add <name>          添加新账号 (自动引导登录)
  remove, rm <name>   删除账号
  rename <old> <new>  重命名账号
  update [name]       重新登录并更新账号认证 (不指定则更新当前)
  status              查看当前使用的账号
  balance, bal [name] 查询账号余额 (不指定则查询全部)
  help                显示帮助信息
```

### 常用示例

```bash
# 添加账号 (自动打开浏览器登录)
codex-switch add work

# 列出所有账号
codex-switch list

# 切换账号
codex-switch sw work

# 查询所有账号余额
codex-switch balance

# 查询指定账号余额
codex-switch bal work

# 更新账号认证 (token 过期时)
codex-switch update work
```

## 依赖

- [Codex CLI](https://github.com/openai/codex) — `codex` 命令需已安装
- [jq](https://stedolan.github.io/jq/) — JSON 解析
- Python 3 — 余额查询脚本

## 项目结构

```
codex-switch          # 主工具 (Bash)
codex-balance-helper  # 余额查询辅助脚本 (Python)
```

## License

MIT
