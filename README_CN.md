# ctxd

统一的上下文导出工具，服务于 LLM 工作流。

**📖 [English Documentation](README.md)**

## 支持的数据源

| 来源 | URL 模式 |
|------|----------|
| GitHub PR | `https://github.com/<owner>/<repo>/pull/<number>` |
| Slack Thread | `https://*.slack.com/archives/...` 或 `.../client/.../thread/...` |
| Confluence | `https://*.atlassian.net/wiki/...` |
| Jira | `https://*.atlassian.net/browse/<KEY>` |

## 安装

### Homebrew（推荐）

```bash
brew tap cheerchen/tap
brew install ctxd
```

### 从源码

```bash
cd ctxd
uv sync --group dev
```

## Shell 别名

```bash
# zsh / bash
eval "$(ctxd init zsh)"

# fish
ctxd init fish | source
```

配置后可用 `ctx` 代替 `ctxd`。

## 通用参数

| 参数 | 说明 |
|------|------|
| `-o, --output <path>` | 输出到文件/目录（默认 stdout） |
| `-O, --auto-output` | 根据来源自动生成输出路径（与 `-o` 互斥） |
| `-f, --format text\|md` | 输出格式（默认 `md`） |
| `-q, --quiet` | 静默模式（stderr 非 TTY 时自动启用） |
| `-v, --verbose` | 详细日志 |

参数可以放在 URL 前后（如 `ctxd -q <url>` 和 `ctxd <url> -q` 均可）。

---

## GitHub PR

导出 PR 的元数据、评审、行内评论、时间线评论和代码变更。

### 前置条件

安装并登录 [GitHub CLI](https://cli.github.com/)：

```bash
brew install gh
gh auth login
```

Diff 生成走 GitHub API（`gh pr diff` 与 `/pulls/{n}/files`），可在任意工作目录下运行——不需要本地 clone 目标仓库。

### 使用

```bash
ctxd https://github.com/owner/repo/pull/123
ctxd https://github.com/owner/repo/pull/123 -o pr-123.md
ctxd -O https://github.com/owner/repo/pull/123
```

### 输出结构

生成的 Markdown 包含以下顶级小节：

- `## Reviews` — 每条评审含 `@author`、`**STATE**`（APPROVED / CHANGES_REQUESTED / COMMENTED / DISMISSED）、提交时间戳和正文。空正文评审（如裸 approve）也会保留。
- `## Inline Review Comments` — 行内代码评论按文件分组，渲染为 `@user [SIDE] L{start}-{end} (timestamp):`，带 LEFT/RIGHT 侧和多行范围。
- `## Timeline Comments` — PR 对话区的 issue-level 评论。
- `## Git Diff` — 代码 diff（模式由 `-d` 控制）。

所有评审和评论都带来自 GitHub API 的 ISO-8601 时间戳（含时区）。**默认保留 bot 作者的内容** —— 传 `--no-bots` 可过滤掉 `pr-agent`、`devin-ai-integration`、`coderabbitai` 等 bot 的评审/评论。

### 专属参数

| 参数 | 说明 |
|------|------|
| `-d, --diff-mode full\|compact\|stat` | Diff 输出模式（默认 `compact`） |
| `--clean-body / --no-clean-body` | 清理 PR body 中的 bot HTML 噪音（默认开启） |
| `--no-bots` | 过滤 bot 作者的评审和评论（默认全部保留） |

---

## Slack Thread

导出完整 Slack 对话线程，包括用户名解析和附件。

### 前置条件

需要一个 Slack User Token（`xoxp-...`），具备以下权限：
- `channels:history`, `groups:history`, `im:history`, `mpim:history`
- `users:read`
- `files:read`（如需下载附件）

获取方式：[api.slack.com/apps](https://api.slack.com/apps) → 你的 App → OAuth & Permissions → User Token。

配置 Token（二选一）：

```bash
# 方式一：环境变量
export SLACK_TOKEN="xoxp-..."

# 方式二：配置文件
mkdir -p ~/.config/ctxd
echo 'SLACK_TOKEN=xoxp-...' >> ~/.config/ctxd/config
```

### 使用

```bash
# 新版 URL 格式
ctxd https://app.slack.com/client/T.../C.../thread/C...-1234567890.123456

# 归档 URL 格式
ctxd https://your-workspace.slack.com/archives/C.../p...?thread_ts=...
```

### 专属参数

| 参数 | 说明 |
|------|------|
| `--download-files` | 下载附件到 `./attachments` |
| `--raw` | 保留原始 Slack mrkdwn 标记 |

---

## Confluence

将 Confluence 页面导出为 Markdown。**默认输出单页到 stdout**；传 `-r` / `-i` 并配合 `-o <dir>`（或 `-O`）即可做递归导出和图片下载。

### 前置条件

需要 Atlassian API Token。获取方式：[id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens)。

三项值均必填。二选一：

```bash
# 方式一：环境变量
export CONFLUENCE_BASE_URL="https://your-site.atlassian.net"
export CONFLUENCE_EMAIL="you@example.com"
export CONFLUENCE_API_TOKEN="your-token"

# 方式二：配置文件（推荐长期使用）
mkdir -p ~/.config/ctxd
cat >> ~/.config/ctxd/config <<'EOF'
CONFLUENCE_BASE_URL=https://your-site.atlassian.net
CONFLUENCE_EMAIL=you@example.com
CONFLUENCE_API_TOKEN=your-token
EOF
chmod 600 ~/.config/ctxd/config
```

环境变量优先级高于配置文件，方便 CI 和临时覆盖。如果配置文件被 group/others 可读，ctxd 会在 stderr 打印一条一次性警告，并附上 `chmod 600` 修复命令。

### 使用

```bash
# 默认：单页输出到 stdout
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456

# 递归导出 + 图片，落到指定目录
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456 -r -i -o ./output

# 或让 ctxd 自动选一个目录名
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456 -r -i -O
```

> **注意**：`-r` / `-i` / `--all-attachments` 需配合 `-o <dir>` 或 `-O`（Confluence 需要把页面树和图片写入磁盘）。

### 专属参数

| 参数 | 说明 |
|------|------|
| `-r, --recursive / --no-recursive` | 包含子页面（默认关闭） |
| `-i, --include-images / --no-include-images` | 下载正文引用的图片（默认关闭） |
| `--all-attachments` | 下载所有附件（默认仅下载正文引用的图片） |
| `--debug` | 保存原始 HTML 用于排查 |

---

## Jira

导出 Jira Issue 的完整内容（描述、评论、自定义字段）。

### 前置条件

与 Confluence 共享认证 —— 可通过环境变量**或** `~/.config/ctxd/config` 配置（完整的配置文件写法及 `chmod 600` 说明见上面的 [Confluence 章节](#confluence)）：

```bash
export CONFLUENCE_BASE_URL="https://your-site.atlassian.net"
export CONFLUENCE_EMAIL="you@example.com"
export CONFLUENCE_API_TOKEN="your-token"
```

### 使用

```bash
ctxd https://your-site.atlassian.net/browse/PROJECT-123
ctxd https://your-site.atlassian.net/browse/PROJECT-123 -o issue.md
```

### 专属参数

| 参数 | 说明 |
|------|------|
| `--debug` | 保存原始 HTML（`.debug.html`）用于排查转换问题 |

## 许可证

[MIT](LICENSE)
