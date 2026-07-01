# ctxd

把工作 URL 变成适合喂给 LLM 的 Markdown。

**📖 [English Documentation](README.md)**

![ctxd 总览](assets/ctxd-overview.svg)

`ctxd` 是一个 CLI，用来把 GitHub PR、Slack thread、Confluence 页面、Jira issue 导出成干净、可复查、可落盘的 Markdown 或 text。

它适合：

- 一次性拉很多上下文
- 把结果稳定写到磁盘
- 复用同一条命令
- 减少模型内 connector 反复做 tool selection 的开销

## Agent skill（推荐）

ctxd 自带配套 skill，位于 [skills/ctxd/SKILL.md](skills/ctxd/SKILL.md)，可同时用于 **Claude Code** 和 **Codex CLI**。它会让 agent 在对话里看到受支持的 URL 时优先使用 `ctxd`，而不是退回到聊天式抓取或模型内 connector。

```bash
# Claude Code
mkdir -p ~/.claude/skills && ln -s "$(realpath skills/ctxd)" ~/.claude/skills/ctxd

# Codex CLI
mkdir -p ~/.codex/skills && ln -s "$(realpath skills/ctxd)" ~/.codex/skills/ctxd
```

这个 skill 假设下方的[必要配置](#必要配置)已经完成。如果凭证缺失，agent 会先告诉你缺哪一个 key 或登录态，再尝试抓取。

## 为什么用 ctxd

- **CLI 优先，不是聊天优先**：一条命令生成稳定 artifact，便于检查、diff、归档、继续喂给任意模型。
- **批量导出是第一公民**：PR、Slack thread、Confluence page tree、Jira issue 都是“整份上下文”导出，而不是多轮零碎抓取。
- **评论和元数据完整保留**：review、inline comments、时间戳、附件、页面元数据、自定义字段都不会丢。
- **适合 agent workflow**：`0.4.0` 起支持全源并发拉取，并带 `--profile`、`--max-concurrency`。

## 什么时候 CLI 比 connector 更合适

| 场景 | `ctxd` CLI | 模型内 connector |
|--------|--------|--------|
| 导出整棵 Confluence 页面树 | 最适合 | 往往需要很多次工具调用 |
| 拉长 Slack thread 供后续总结 | 最适合 | 往往会重复抓取和解析 |
| 把 PR review 上下文落成文件 | 最适合 | 通常没有持久 artifact |

## 快速示例

```bash
# GitHub PR -> 自动生成 markdown 文件
ctxd -O https://github.com/owner/repo/pull/123

# Slack thread -> 输出到 stdout
ctxd https://app.slack.com/client/T.../C.../thread/C...-1234567890.123456

# Confluence 页面树 + 图片 -> 导出到本地目录
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456 -r -i -O

# Jira issue -> Obsidian-ready note
ctxd https://your-site.atlassian.net/browse/PROJECT-123 --obsidian -O
```
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

## 必要配置

agent 真正能用 `ctxd` 取数，前提是认证已经配好。

配置文件：

```bash
~/.config/ctxd/config
```

常见配置项：

```bash
SLACK_TOKEN=xoxp-...
CONFLUENCE_BASE_URL=https://your-site.atlassian.net
CONFLUENCE_EMAIL=you@example.com
CONFLUENCE_API_TOKEN=your-token
```

GitHub PR 还依赖 `gh`，所以也要确保 gh 已经登录：

```bash
gh auth status
```

## 通用参数

| 参数 | 说明 |
|------|------|
| `-o, --output <path>` | 输出到文件/目录（默认 stdout） |
| `-O, --auto-output` | 根据来源自动生成输出路径（与 `-o` 互斥） |
| `-f, --format text\|md` | 输出格式（默认 `md`） |
| `-q, --quiet` | 静默模式（stderr 非 TTY 时自动启用） |
| `-v, --verbose` | 详细日志 |
| `--profile` | 打印 stage / HTTP / subprocess 耗时摘要 |
| `--max-concurrency <N>` | 控制抓取并发上限（默认 `5`） |
| `--recurse-depth <N>` | 跨源递归：展开输出中出现的 supported URL（默认 `1`，最大 `2`） |
| `--no-recurse` | 关闭跨源递归（等价于 `--recurse-depth 0`） |

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

### 使用

```bash
ctxd https://github.com/owner/repo/pull/123
ctxd https://github.com/owner/repo/pull/123 -o pr-123.md
ctxd -O https://github.com/owner/repo/pull/123
```

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

当你复制的是某条特定回复的链接时（归档 URL 带 `?thread_ts=` 且 path ts 与 thread root 不同），`ctxd` 仍然抓取整个 thread，但会高亮你指向的那条消息——header 中显示 `**Focused Message:**`，对话流中对应消息标有 `▶` 标记。

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

# 短链接（tiny link）——认证后跟随重定向解析为长 URL
ctxd https://your-site.atlassian.net/wiki/x/ABC123

# 递归导出 + 图片，落到指定目录
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456 -r -i -o ./output

# 或让 ctxd 自动选一个目录名
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456 -r -i -O
```

> **注意**：`-r` / `-i` / `--all-attachments` 需配合 `-o <dir>` 或 `-O`（Confluence 需要把页面树和图片写入磁盘）。
> **短链接**：`/wiki/x/<token>` 形式的 URL 会在认证后跟随一次重定向，改写为标准长 URL 再进行页面抓取；`-O` 自动命名时因尚未拿到真实 page id，文件名回退为 `confluence-<token>`。

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

与 Confluence 共享认证。配置方式同 Confluence（见上）。Jira 也支持 `--debug` 来保存原始 HTML。

### 使用

```bash
ctxd https://your-site.atlassian.net/browse/PROJECT-123
ctxd https://your-site.atlassian.net/browse/PROJECT-123 -o issue.md
```

---

## 跨源递归

默认情况下，`ctxd` 会扫描输出内容中出现的 supported URL（Slack / GitHub PR / Confluence / Jira），自动抓取并追加为带标签的附录。这意味着一个 Slack thread 里贴了 Jira issue 和 GitHub PR 链接时，一条命令就能把三处内容全部拉下来——不需要再手动跟进抓取。

```bash
# 默认 depth=1，自动展开链接中的 supported URL
ctxd https://app.slack.com/client/.../thread/...

# 关闭递归
ctxd <url> --no-recurse

# 更深递归（最大 2）
ctxd <url> --recurse-depth 2
```

关键行为：
- **去重**：同一次 run 中同一个 URL 不会被重复抓取。
- **上限**：每层最多展开 5 个子 URL（防止 Jira issue 互链爆炸）。
- **缺凭证跳过**：如果子 URL 缺少凭证（比如 Slack thread 里贴了 Confluence 链接但没配 Confluence token），附录中标注跳过而非报错中断。
- **Confluence 目录导出**：使用 `-o`/`-O` 导出 Confluence 页面树时递归关闭（目录树与拼接流不兼容）；需要递归请用 stdout。

---

## Performance

| 场景 | 优化前 | 优化后 | 提升 |
|------|------:|------:|------:|
| Slack thread | 9.09s | 1.61s | 82.3% |
| Confluence 单页 + 图片 | 1.88s | 1.74s | 7.4% |
| Confluence 递归 + 图片 | 27.13s | 4.04s | 85.1% |
| GitHub PR | 6.75s | 4.15s | 38.5% |

## 许可证

[MIT](LICENSE)
