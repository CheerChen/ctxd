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
| `-o auto` | 根据来源自动生成输出路径 |
| `-f, --format text\|md` | 输出格式（默认 `md`） |
| `-q, --quiet` | 静默模式 |
| `-v, --verbose` | 详细日志 |

参数可以放在 URL 前后（如 `ctxd -q <url>` 和 `ctxd <url> -q` 均可）。

---

## GitHub PR

导出 PR 的元数据、评论、代码变更。

### 前置条件

安装并登录 [GitHub CLI](https://cli.github.com/)：

```bash
brew install gh
gh auth login
```

### 使用

```bash
ctxd https://github.com/owner/repo/pull/123
ctxd https://github.com/owner/repo/pull/123 -o pr-123.md
ctxd -o auto https://github.com/owner/repo/pull/123
```

### 专属参数

| 参数 | 说明 |
|------|------|
| `-d, --diff-mode full\|compact\|stat` | Diff 输出模式（默认 `compact`） |
| `--clean-body / --no-clean-body` | 清理 PR body 中的 bot HTML 噪音（默认开启） |

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

递归导出 Confluence 页面为 Markdown，含图片下载。

### 前置条件

需要 Atlassian API Token。获取方式：[id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens)。

配置（三个环境变量均必填）：

```bash
export CONFLUENCE_BASE_URL="https://your-site.atlassian.net"
export CONFLUENCE_EMAIL="you@example.com"
export CONFLUENCE_API_TOKEN="your-token"
```

或写入配置文件 `~/.config/ctxd/config`。

### 使用

```bash
# 导出到目录（递归 + 图片，默认行为）
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456 -o ./output

# 仅输出到 stdout（需禁用递归和图片）
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456 --no-recursive --no-include-images
```

> **注意**：递归导出或图片下载必须指定 `-o <dir>`，不支持 stdout。

### 专属参数

| 参数 | 说明 |
|------|------|
| `-r, --recursive / --no-recursive` | 包含子页面（默认开启） |
| `-i, --include-images / --no-include-images` | 下载图片（默认开启） |
| `--all-attachments` | 下载所有附件（默认仅下载正文引用的图片） |
| `--debug` | 保存原始 HTML 用于排查 |

---

## Jira

导出 Jira Issue 的完整内容（描述、评论、自定义字段）。

### 前置条件

与 Confluence 共享认证，使用相同的三个环境变量：

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
