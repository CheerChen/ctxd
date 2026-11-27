# CLI Reference

**📖 [中文](cli_cn.md) · [Home](../README.md) · [Authentication](auth.md)**

Options can be placed before or after the URL (both `ctxd -q <url>` and `ctxd <url> -q` work).

## Global options

| Option | Description |
|--------|-------------|
| `-o, --output <path>` | Write to file/directory (default: stdout) |
| `-O, --auto-output` | Auto-generate output path by source (mutually exclusive with `-o`) |
| `-f, --format text\|md` | Output format (default: `md`) |
| `-q, --quiet` | Suppress progress logs only — warnings and the completeness summary always print (auto-enabled when stderr is not a TTY) |
| `-v, --verbose` | Verbose logging |
| `--profile` | Print stage / HTTP timing summary |
| `--max-concurrency <N>` | Cap parallel work across fetchers (default: `5`) |
| `--recurse-depth <N>` | Cross-source recursion: expand supported URLs found in output (default: `0`=off, max `2`; opt-in with `1`/`2`) |
| `--no-recurse` | Disable cross-source recursion (equivalent to `--recurse-depth 0`; kept for explicitness) |
| `--max-chars <N>` | Cap output characters (default: `100000` for stdout; file output unlimited unless set explicitly; `-1` = unlimited) |
| `--max-file-size <N>` | Cap per-attachment download size in bytes (default: `52428800` = 50 MiB; `-1` = unlimited) |
| `--max-run-size <N>` | Cap total attachment download size per run in bytes (default: `524288000` = 500 MiB; `-1` = unlimited) |

---

## GitHub PR

Export PR metadata, reviews, inline comments, timeline comments, and code changes. *(Credentials: [`GITHUB_TOKEN`](auth.md#github-pr))*

```bash
ctxd https://github.com/owner/repo/pull/123
ctxd https://github.com/owner/repo/pull/123 -d full -o pr-123.md
ctxd -O https://github.com/owner/repo/pull/123
```

| Option | Description |
|--------|-------------|
| `-d, --diff-mode full\|compact\|stat` | Diff output mode (default: `compact`). `compact` lists files and hunk ranges and `stat` lists files and line counts — neither includes code, and the output says so; use `full` to review the changes |
| `--clean-body / --no-clean-body` | Strip bot-injected HTML noise from PR body (default: on) |
| `--no-bots` | Drop bot-authored reviews and comments (default: keep all bots) |

---

## Slack Thread

Export a full Slack thread with username resolution and attachments. *(Credentials: [`SLACK_TOKEN`](auth.md#slack-thread))*

```bash
# Client URL format
ctxd https://app.slack.com/client/T.../C.../thread/C...-1234567890.123456

# Archive URL format
ctxd 'https://your-workspace.slack.com/archives/C.../p...?thread_ts=...'
```

When you copy a link to a specific reply (archive URL with `?thread_ts=` where the path `ts` differs from the thread root), `ctxd` fetches the entire thread and highlights the focused message — a `**Focused Message:**` line in the header and a `▶` marker on that message in the conversation flow.

| Option | Description |
|--------|-------------|
| `--download-files` | Download attachments next to the output as `attachments/IMG_{file_id}.{ext}` (e.g. `IMG_F0AAAAAAA1.png`); requires `-o`/`-O` and the `files:read` scope on the Slack token |
| `--raw` | Keep original Slack mrkdwn markup |
| `--since <ts>` | Export only the replies posted after message `<ts>` (e.g. `1735881234.123456`) |

### Incremental follow-up (`--since`)

Every export records `**Last Message ts:**` in its header and run summary. When a thread gets new replies, pass that cursor back instead of re-reading the whole thread:

```bash
ctxd '<thread-url>' --since 1735881234.123456
```

- Prints a short header (thread URL, `since`, new message count, updated `Last Message ts`) and the new replies only; if nothing is new, prints `No new replies since <ts>.` and exits `0`.
- With `-O`, writes `slack-<channel>-<thread>.since-<ts>.md` so it never overwrites the full export.
- Edits or deletions on messages before `<ts>` are not visible in this mode — run a full export when those matter.

Each attachment line keeps its Slack permalink and, when downloaded, appends `— saved: attachments/IMG_<id>.<ext>`. The run summary reports how many files were downloaded or skipped.

---

## Confluence

Export Confluence pages to Markdown. Defaults to a single page on stdout; pass `-r` / `-i` / `--all-attachments` with `-o` or `-O` for local files and page trees. *(Credentials: [Atlassian API token](auth.md#confluence--jira))*

```bash
# Single page to stdout
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456

# Tiny link (short URL) — resolved via authenticated redirect
ctxd https://your-site.atlassian.net/wiki/x/ABC123

# Recursive page tree with images -> directory
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456 -r -i -o ./output
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456 -r -i -O

# Single page to one file; downloads go to sibling page_attachments/
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456 --all-attachments -o page.md
```

| Option | Description |
|--------|-------------|
| `-r, --recursive / --no-recursive` | Include every descendant page, at any depth (default: off). The run summary states the tree size: `page tree: N descendant page(s), max depth D` |
| `-i, --include-images / --no-include-images` | Download referenced images (default: off) |
| `--all-attachments` | Download every attachment — images to `images/`, other files (PDF, spreadsheets, …) to `attachments/` (default: off) |
| `--debug` | Save raw HTML for debugging |
| `--only comments` | Export only the comments, under a short header; see [Comments only](#comments-only---only-comments) |

### Output layout & attachments

- **Single file (`-o page.md` without `-r`)**: any path with a file suffix writes one Markdown file, with downloads placed in a sibling `page_attachments/` (same layout as Jira). Passing `-r` with a file-like `-o` is rejected.
- **Directory (`-o <dir>`, `-O`, or any `-r` run)**: writes `<dir>/<id>_<title>/README.md` per page with `images/` and `attachments/` beside it. For `/wiki/x/<token>` tiny links, `-O` names the directory `confluence-<token>`.
- **Undownloaded attachments are never hidden**: images not downloaded link to the stable REST download URL (usable with `curl -u "$CONFLUENCE_EMAIL:$CONFLUENCE_API_TOKEN" -L <url>`, no expiring token), and every page ends with an `Attachments` section listing filename, MIME type, and size.

---

## Jira

Export full Jira issue content (description, comments, custom fields, attachments). *(Credentials: [Atlassian API token](auth.md#confluence--jira))*

```bash
ctxd https://your-site.atlassian.net/browse/PROJECT-123
ctxd https://your-site.atlassian.net/browse/PROJECT-123 -o issue.md
ctxd https://your-site.atlassian.net/browse/PROJECT-123 -i -O
ctxd https://your-site.atlassian.net/browse/PROJECT-123 --all-attachments -O
```

| Option | Description |
|--------|-------------|
| `-i, --include-images / --no-include-images` | Download images referenced from the issue body (default: off) |
| `--all-attachments` | Download every attachment on the issue (default: off) |
| `--debug` | Save raw HTML for debugging |
| `--only comments` | Export only the comments, under a short header; see [Comments only](#comments-only---only-comments) |

- **Custom fields**: rich-text custom fields render as Markdown; serializable plain fields (strings, numbers, booleans, simple lists/dicts) are included too. Unsupported nested objects are omitted with a stderr warning and a summary note — never dropped silently.
- **Attachments**: `-i` and `--all-attachments` require `-o <file>` or `-O`. Downloaded files land in `<output-stem>_attachments/<attachment-id>-<filename>`, and links in the description, comments, and custom fields are rewritten to local relative paths. Even when nothing is downloaded, every export ends with an `Attachments` inventory.

### Service desk requests

A request raised through a Jira Service Management portal is readable even when you are only its customer. The platform API answers a customer with 404 (no Browse permission), indistinguishable from a missing issue, so `ctxd` decides by project: on a 404 it retries through the service desk customer API only when the URL is a portal link (`/servicedesk/customer/portal/<id>/<KEY>`) or the project is one of the service desks visible to you. That list is fetched once and cached for a day in `~/.cache/ctxd/` (`$XDG_CACHE_HOME` respected), so a genuine 404 in an ordinary project costs no extra request. Agents of the service desk still get the full platform-API export, internal comments included.

The customer view has less than the agent view, and the output says so: assignee, priority, labels, components and the update time show `(not visible in portal)`, comments are the public ones only, and the run summary notes that the request was read through the customer API. Request form fields other than summary and description are exported under their portal labels.

---

## Comments only (`--only comments`)

For Confluence pages and Jira issues (service desk requests included), when the body is already in context and only the discussion is needed — a reply on a ticket you are following, review comments on a page you wrote. Not for a first read: comments rarely make sense without the body.

```bash
ctxd https://your-site.atlassian.net/browse/PROJECT-123 --only comments
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456 --only comments
```

- **Not requested at all**: the Jira description, custom fields, links, subtasks and attachments; the Confluence page body and attachments.
- **Header**: Jira shows status, assignee, `Updated` and the latest comment time; Confluence shows the version, `Last Modified` and the latest comment time. When the issue or page changed after its latest comment, the output says so: the body or status may differ from what you read before, so re-run without `--only comments`.
- **Comments**: all of them, with replies. A Jira comment edited after posting shows `(edited <time>)`. Confluence inline comments quote the text they annotate but carry no `(Line N)`, since those numbers point into the body.
- **Output**: always one file, also for Confluence: `-O` writes `jira-<KEY>.comments.md` / `confluence-<id>.comments.md`, never overwriting the full export. With no comments, it prints the header and `No comments.`
- **Rejected combinations**: Slack and GitHub PR URLs, and `-r`, `-i`, `--all-attachments`.

---

## Cross-source recursion

By default, cross-source recursion is **off** (`--recurse-depth 0`). Opt in with `--recurse-depth 1` or `2` to have `ctxd` scan the rendered output for supported URLs (Slack, GitHub PR, Confluence, Jira) and fetch them too, appending the results as a labelled appendix.

```bash
# Enable recursion (depth=1, auto-expands linked supported URLs)
ctxd '<url>' --recurse-depth 1

# Deeper recursion (max 2)
ctxd '<url>' --recurse-depth 2
```

Key behaviours:
- **Deduplication**: the same URL is never fetched twice within one run.
- **Cap**: at most 5 child URLs are expanded per level (prevents Jira issue-link explosions).
- **Graceful skip**: if a child URL lacks credentials, the appendix notes the skip instead of failing the run.
- **Confluence directory export**: recursion is disabled when using `-o`/`-O` with Confluence directory exports; use stdout for recursion.

---

## Completeness summary, manifest & limits

### Completeness summary and `manifest.json`

Every run prints a one-line completeness summary to stderr (always visible, including under `-q`):

```text
ctxd summary: source=jira | fetched=1 | rendered=1 | artifacts=1
```

Non-zero `skipped`, `failed`, or `truncated` counts and free-form notes (omitted custom fields, failed downloads) appear alongside it. When writing to disk, a machine-readable manifest with the same fields is written next to the output:

| Output mode | Manifest path |
|-------------|---------------|
| Single file (`-o issue.md` / `-O`) | `issue.md.manifest.json` |
| Directory (Confluence tree) | `<dir>/manifest.json` |

### Output integrity and size limits

- **Atomic writes**: text and binary files are written via temp file + rename to avoid half-written artifacts on interrupt.
- **`--max-chars`**: truncates at a newline boundary, closes open code fences, and appends a truncation notice. Applies to stdout by default (`100000`); pass explicitly to cap file output as well.
- **Attachment size caps**: streamed downloads enforce per-file (`--max-file-size`, 50 MiB) and per-run (`--max-run-size`, 500 MiB) budgets shared across the recursion tree. Exceeded downloads warn and count as `failed`.
