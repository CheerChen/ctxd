# CLI 参考手册

**📖 [English](cli.md) · [返回首页](../README_CN.md) · [认证与配置](auth_cn.md)**

参数放在 URL 前后均可（如 `ctxd -q <url>` 和 `ctxd <url> -q` 均有效）。

## 通用参数

| 参数 | 说明 |
|------|------|
| `-o, --output <path>` | 输出到文件/目录（默认 stdout） |
| `-O, --auto-output` | 根据来源自动生成输出路径（与 `-o` 互斥） |
| `-f, --format text\|md` | 输出格式（默认 `md`） |
| `-q, --quiet` | 仅抑制进度日志——告警与完整性摘要始终输出（stderr 非 TTY 时自动启用） |
| `-v, --verbose` | 详细日志 |
| `--profile` | 打印 stage / HTTP 耗时摘要 |
| `--max-concurrency <N>` | 控制抓取并发上限（默认 `5`） |
| `--recurse-depth <N>` | 跨源递归：展开输出中出现的 supported URL（默认 `0`=关闭，最大 `2`；需手动 `1`/`2` 开启） |
| `--no-recurse` | 关闭跨源递归（等价于 `--recurse-depth 0`；保留以便显式声明） |
| `--max-chars <N>` | 限制输出字符数（stdout 默认 `100000`；文件输出默认不限，显式传入时才生效；`-1` = 不限制） |
| `--max-file-size <N>` | 单个附件下载上限，单位字节（默认 `52428800` = 50 MiB；`-1` = 不限制） |
| `--max-run-size <N>` | 单次运行附件下载总量上限，单位字节（默认 `524288000` = 500 MiB；`-1` = 不限制） |

---

## GitHub PR

导出 PR 的元数据、评审、行内评论、时间线评论和代码变更。*（凭证配置见 [`GITHUB_TOKEN`](auth_cn.md#github-pr)）*

```bash
ctxd https://github.com/owner/repo/pull/123
ctxd https://github.com/owner/repo/pull/123 -d full -o pr-123.md
ctxd -O https://github.com/owner/repo/pull/123
```

| 参数 | 说明 |
|------|------|
| `-d, --diff-mode full\|compact\|stat` | Diff 输出模式（默认 `compact`）。`compact` 列出文件与 hunk 行号范围，`stat` 列出文件与增删行数——两者都不含代码，输出中会注明；要审查改动内容请用 `full` |
| `--clean-body / --no-clean-body` | 清理 PR body 中的 bot HTML 噪音（默认开启） |
| `--no-bots` | 过滤 bot 作者的评审和评论（默认全部保留） |

---

## Slack Thread

导出完整 Slack 对话线程，包括用户名解析和附件。*（凭证配置见 [`SLACK_TOKEN`](auth_cn.md#slack-thread)）*

```bash
# 新版客户端 URL
ctxd https://app.slack.com/client/T.../C.../thread/C...-1234567890.123456

# 归档 URL
ctxd 'https://your-workspace.slack.com/archives/C.../p...?thread_ts=...'
```

如果复制的是某条特定回复的链接（归档 URL 带 `?thread_ts=` 且 path `ts` 与 thread root 不同），`ctxd` 仍抓取整个 thread，并在 header 标注 `**Focused Message:**`、在对话流对应消息旁标出 `▶`。

| 参数 | 说明 |
|------|------|
| `--download-files` | 下载附件到输出文件旁的 `attachments/`，文件名格式为 `IMG_{file_id}.{ext}`（如 `IMG_F0AAAAAAA1.png`）；需要 `-o`/`-O`，且 Slack token 含 `files:read` scope |
| `--raw` | 保留原始 Slack mrkdwn 标记 |
| `--since <ts>` | 只导出消息 `<ts>`（如 `1735881234.123456`）之后的回复 |

### 增量跟进新回复（`--since`）

每次导出的 header 和运行摘要都带有 `**Last Message ts:**`。当 thread 有新回复时，把该游标传回即可只拉增量：

```bash
ctxd '<thread-url>' --since 1735881234.123456
```

- 仅输出精简 header（thread URL、`since`、新消息数、新的 `Last Message ts`）和新增回复；无新回复时输出 `No new replies since <ts>.` 并以 `0` 退出。
- 配合 `-O` 时文件名为 `slack-<channel>-<thread>.since-<ts>.md`，不会覆盖全量导出。
- `<ts>` 之前消息的编辑或删除在此模式下不可见，需要时请重新全量导出。

每条附件行保留 Slack permalink；已下载的附件末尾追加 `— saved: attachments/IMG_<id>.<ext>`。运行摘要会报告下载或跳过了几个文件。

---

## Confluence

将 Confluence 页面导出为 Markdown。默认输出单页到 stdout；传 `-r` / `-i` / `--all-attachments` 并配合 `-o` 或 `-O` 落盘。*（凭证配置见 [Atlassian API Token](auth_cn.md#confluence-与-jira)）*

```bash
# 单页输出到 stdout
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456

# 短链接（tiny link）——认证后跟随重定向解析为标准长 URL
ctxd https://your-site.atlassian.net/wiki/x/ABC123

# 递归导出页面树 + 图片 -> 目录
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456 -r -i -o ./output
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456 -r -i -O

# 单页写成一个文件；附件放在同级的 page_attachments/
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456 --all-attachments -o page.md
```

| 参数 | 说明 |
|------|------|
| `-r, --recursive / --no-recursive` | 包含任意深度的全部子孙页面（默认关闭）。运行摘要会给出页面树规模：`page tree: N descendant page(s), max depth D` |
| `-i, --include-images / --no-include-images` | 下载正文引用的图片（默认关闭） |
| `--all-attachments` | 下载全部附件：图片放 `images/`，其他文件（PDF、表格等）放 `attachments/`（默认关闭） |
| `--debug` | 保存原始 HTML 用于排查 |

### 输出目录结构与附件行为

- **单文件模式（不带 `-r` 且 `-o page.md` 带文件后缀）**：只写这一个 Markdown 文件，下载内容放在同级的 `page_attachments/`（与 Jira 一致）。`-r` 配合文件形式的 `-o` 会直接报错。
- **目录模式（`-o <dir>`、`-O` 或任何 `-r` 导出）**：每页写为 `<dir>/<id>_<title>/README.md`，同级存放 `images/` 与 `attachments/`。短链接 `/wiki/x/<token>` 配合 `-O` 时目录名为 `confluence-<token>`。
- **未下载的附件不会丢失**：未下载的图片指向稳定的 REST 下载地址（可用 `curl -u "$CONFLUENCE_EMAIL:$CONFLUENCE_API_TOKEN" -L <url>` 拉取，不含过期 token），且每页末尾都有 `Attachments` 清单列出文件名、MIME 类型与体积。

---

## Jira

导出 Jira Issue 的完整内容（描述、评论、自定义字段、附件）。*（凭证配置见 [Atlassian API Token](auth_cn.md#confluence-与-jira)）*

```bash
ctxd https://your-site.atlassian.net/browse/PROJECT-123
ctxd https://your-site.atlassian.net/browse/PROJECT-123 -o issue.md
ctxd https://your-site.atlassian.net/browse/PROJECT-123 -i -O
ctxd https://your-site.atlassian.net/browse/PROJECT-123 --all-attachments -O
```

| 参数 | 说明 |
|------|------|
| `-i, --include-images / --no-include-images` | 下载正文引用的图片（默认关闭） |
| `--all-attachments` | 下载 Issue 上的全部附件（默认关闭） |
| `--debug` | 保存原始 HTML 用于排查 |

- **自定义字段**：富文本自定义字段转为 Markdown；可序列化的普通字段（字符串、数字、布尔、简单列表/字典）一并导出。无法序列化的嵌套对象会省略，并在 stderr 告警、记入摘要 notes，绝不静默丢弃。
- **附件落盘**：`-i` 与 `--all-attachments` 需配合 `-o <文件>` 或 `-O`。下载目录为 `<输出文件名>_attachments/<附件 id>-<原文件名>`，描述、评论与自定义字段中的链接会改写为本地相对路径；即使未下载文件，末尾也始终附有 `Attachments` 清单。

### Service desk 请求

通过 Jira Service Management 门户提交的请求，即使你只是它的客户（customer）也能导出。平台 API 对客户返回 404（没有 Browse 权限），与 issue 不存在无法区分，所以 `ctxd` 按项目判断：只有 URL 是门户链接（`/servicedesk/customer/portal/<id>/<KEY>`），或者项目属于你可见的 service desk 时，404 才改走 service desk 客户 API 重试。可见的 service desk 列表只取一次，在 `~/.cache/ctxd/`（遵循 `$XDG_CACHE_HOME`）缓存一天，所以普通项目里真正的 404 不会多发请求。该 service desk 的 agent 仍走平台 API 完整导出，包含内部评论。

客户视图的信息比 agent 视图少，输出会明确标出：assignee、priority、labels、components 和更新时间显示为 `(not visible in portal)`，评论只有公开评论，运行摘要会注明是通过客户 API 读取的。summary 和 description 以外的请求表单字段按门户上的标签名导出。

---

## 跨源递归

默认情况下，跨源递归**关闭**（`--recurse-depth 0`）。传 `--recurse-depth 1` 或 `2` 开启后，`ctxd` 会扫描输出内容中出现的 supported URL（Slack / GitHub PR / Confluence / Jira），自动抓取并追加为带标签的附录。

```bash
# 开启递归（depth=1，自动展开正文提到的 supported URL）
ctxd '<url>' --recurse-depth 1

# 更深递归（最大 2）
ctxd '<url>' --recurse-depth 2
```

关键行为：
- **去重**：同一次运行中同一个 URL 不会重复抓取。
- **每层上限**：每层最多展开 5 个子 URL（防止 Jira issue 互链爆炸）。
- **缺凭证跳过**：子 URL 若未配凭证会在附录注明跳过，不会中断主抓取。
- **Confluence 目录导出**：使用 `-o`/`-O` 导出 Confluence 目录树时递归关闭；需要跨源递归请输出到 stdout。

---

## 完整性摘要、manifest 与输出上限

### 完整性摘要与 `manifest.json`

每次运行都会向 stderr 打印一行完整性摘要（始终可见，含 `-q`）：

```text
ctxd summary: source=jira | fetched=1 | rendered=1 | artifacts=1
```

`skipped` / `failed` / `truncated` 非零时会一并列出，省略字段或下载失败等说明附在下方 notes 中。落盘时，输出旁会生成同结构的机器可读 manifest：

| 输出模式 | Manifest 路径 |
|----------|---------------|
| 单文件（`-o issue.md` / `-O`） | `issue.md.manifest.json` |
| 目录（Confluence 页面树） | `<dir>/manifest.json` |

### 输出完整性与体积上限

- **原子写入**：文本与二进制均经临时文件 + rename 落盘，中断时不会留下半截文件。
- **`--max-chars`**：在换行边界截断，自动闭合未结束的代码围栏并附加截断说明。默认仅限制 stdout（`100000`）；显式传入时才限制文件输出。
- **附件体积上限**：流式下载按单文件（`--max-file-size`，默认 50 MiB）与单次运行总量（`--max-run-size`，默认 500 MiB）计费，预算在递归树内共享。超限会告警并计入 `failed`。
