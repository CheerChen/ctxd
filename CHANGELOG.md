# Changelog

## [0.4.1]

### Added
* **Confluence tiny-link support** : `ctxd` now accepts Confluence short URLs of the form `https://<site>.atlassian.net/wiki/x/<token>` (the "tiny link" produced by *Copy link → Short link* in the Confluence UI). The dumper follows the authenticated 302 chain once (`/wiki/x/<token>` → `/wiki/pages/tinyurl.action?urlIdentifier=<token>` → final long URL) right after `validate_auth`, then replaces `self.url` with the resolved long URL so every downstream call (`fetch`, `_dump_obsidian`, metadata block) sees the standard `/wiki/spaces/<KEY>/pages/<id>/<title>` form. New pure helpers `is_short_link(url)` and `parse_short_link(url)` in `ctxd.confluence.url_parser` keep the recognition logic testable without network. `parse_confluence_url` deliberately still raises `ValueError` for short links — resolution is the dumper's job, not the parser's. `default_filename` falls back to `confluence-<token>` for short links (auth isn't available at filename time), so `-O` auto-output names are usable but not yet the real page id.

## [0.4.0]

### Changed
* **Parallel fetch across all sources** — every dumper now fans out its independent HTTP / subprocess work behind a single tunable cap (`--max-concurrency`, default 5):
  * **Slack**: per-instance memoization of `users.info` / `conversations.info`. A thread with 5 unique participants used to fire ~45 lookups (one per message + mention); now ~5. On a 25-message thread this drops wall time from ~8.8s to ~1.6s (−82%) and HTTP calls from 45 to 7.
  * **GitHub PR**: the 5 `gh` subprocess calls in `fetch()` (pr view, issue comments, review comments, reviews, diff) now run concurrently. Wall is now bounded by the slowest single call — typically `gh pr diff` — instead of the sum. On a heavy PR (124 comments, 95 reviews): ~6.8s → ~4.2s (−38%).
  * **Confluence recursive**: page-level export loop runs concurrently; within each page, comment-children lookups and image-attachment downloads also fan out. On a 14-page sub-tree with images: ~26s → ~4s (−85%).

### Added
* **`--profile`** flag prints an HTTP / subprocess / stage timing table to stderr after the dump. Non-2xx responses are split into `http.<source>.4xx` / `5xx` buckets and urllib3 retry attempts surface as `http.<source>.retry`, so transient failures don't get buried in totals.
* **`--max-concurrency N`** (1-32, default 5) caps the parallel fan-out. Lower it if a server is sensitive to bursts.
* **Retry-After-aware retries** — Slack, Confluence (REST + Media), and Jira sessions now mount a shared `HTTPAdapter` with a urllib3 `Retry` policy that respects the `Retry-After` header on 429 / 5xx (3 retries, exponential backoff). No business-code changes required.
* **`scripts/bench.sh`** — repeatable benchmark harness for the 4 representative scenarios (Slack thread, Confluence single + images, Confluence recursive + images, GitHub PR). URLs are injected via env vars; output goes to `.bench-out/` (gitignored).

### Fixed
* **Confluence media downloads now visible in profile / retried correctly**: `ConfluenceClient.download_attachment` previously used a bare `requests.get` which bypassed both instrumentation and the session-mounted retry policy. It now goes through a dedicated `_media_session` (kept separate because media URLs use embedded JWT tokens, not Basic auth), so media downloads count toward `http.confluence_media` and inherit Retry-After handling.
* **Thread-safe Confluence caches**: `_user_cache` / `_space_cache` / `_media_token_cache` previously raced under concurrent page exports (two pages hitting the same author would each fire the `users.info` lookup). Replaced with a per-key locking pattern (`_locked_compute`) — different keys still fetch in parallel, the same key collapses to one HTTP call. On the 14-page benchmark this dropped duplicate fetches from +15 calls back to 0.

## [0.3.3]

### Added
* **Obsidian mode** (`--obsidian`) : new flag for Confluence and Jira that writes a single Markdown note prefixed with a YAML frontmatter block (`{source}_url`, `{source}_title`), making the dump round-trippable as an Obsidian vault note. Requires `-o <file>` or `-O`; auto-naming derives a filename from the remote title with Obsidian-link-sensitive characters stripped. Confluence attachments referenced by the page are downloaded into `<attachments-base>/<ATTACHMENTS_DIR>/{page_id}-*` where `<attachments-base>` is the nearest ancestor containing `.obsidian/` (vault root auto-detection), falling back to the output file's parent. `ATTACHMENTS_DIR` defaults to `assets`, configurable via `~/.config/ctxd/config`. Stale files sharing the same `{page_id}-` prefix are cleaned up on each export. Rejects GitHub/Slack URLs, `-r/--recursive`, and `-f text`. Absorbs the `obsync` companion project — a separate repo previously maintained for this workflow.

### Fixed
* **Confluence attachment downloads via Atlassian Media Service** : the legacy `/wiki/download/attachments/...` endpoint now returns `401 Unauthorized` for API-token Basic auth on at least some Confluence Cloud sites (response carries `WWW-Authenticate: OAuth`, indicating the endpoint has been moved behind OAuth-only auth — consistent with Atlassian's ongoing migration of "classic" API tokens to scoped tokens). `ConfluenceClient.download_attachment` has been rewritten to route through the same Media Service the Confluence web UI uses: it fetches a per-page JWT `mediaToken` via `GET /wiki/rest/api/content/{pageId}?expand=body.view.mediaToken`, decodes the JWT's `iss` claim as the media client ID, then issues `GET https://api.media.atlassian.com/file/{fileId}/binary?token=…&client=…&collection=…`. Tokens are cached per page for the duration of the run. This fixes both `--obsidian` attachment refresh and the previously-broken `-r -i` recursive image export.

### Changed
* **`ConfluenceClient.download_attachment` signature** : changed from `download_attachment(download_link: str)` to `download_attachment(file_id: str, page_id: str)`. The old `downloadLink` field from the v2 attachments API now points at a 401-only endpoint and is no longer useful. Internal callers (the recursive image export and `--obsidian` attachment refresh) have been updated; treat this as a breaking change if you import ctxd as a library (which the README still advises against).

## [0.3.2]

### Added
* **Confluence page metadata** : every dumped Confluence page now leads with a `## Metadata` table (Space, Author, Created, Last Modified, URL), mirroring the Jira dumper and closing the largest self-containment gap in Confluence output. Dates render as `YYYY-MM-DD`; unresolved users/spaces fall back to the raw account/space id so the table schema stays stable for LLM consumers. Adds one cached `/wiki/api/v2/spaces/{id}` lookup per dump.
* **Jira issue URL in metadata** : the existing Jira `## Metadata` table (markdown) and `--- METADATA ---` block (text) gain a `URL` row pointing at `<site>/browse/<KEY>`, so dumped issues are self-linking without any extra API call.

## [0.3.1]

### Added
* **Confluence / Jira credentials via config file** : `CONFLUENCE_BASE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN` can now live in `~/.config/ctxd/config` (same file already used for `SLACK_TOKEN`), instead of being re-exported in every shell. Env vars still win over the file, so CI and one-off overrides are unaffected.
* **Loose permission warning** : ctxd now prints a one-shot stderr warning if `~/.config/ctxd/config` is readable by group/others (any bits in `0o077`), along with the exact `chmod 600` command to fix it.
* **Auto-output flag `-O`** : new short flag (curl-style) that auto-generates the output path/directory by source — e.g. `ctxd -O <url>` writes `pr-9.md` / `slack-C123-....md` / `confluence-<id>/` to the cwd. `-o <path>` and `-O` are mutually exclusive.

### Changed
* **Improved auth error messages** : when credentials are missing, the error now lists both the env-var form and the config-file form with the canonical path and sample keys, so you can pick whichever you prefer.
* **Removed `-o auto` syntax** : the magic string `auto` is no longer recognized as an `-o` value — use `-O` instead. (0.3.0 was never released, so this is a pre-release cleanup, not a breaking change against any published version.)

## [0.3.0]

### Breaking
* **Confluence defaults flipped** : `--recursive` and `--include-images` now default to `false`. `ctxd <confluence-url>` now prints the single page to stdout out-of-the-box; pass `-r` / `-i` (with `-o <dir>`) to opt into the full recursive + images export. Scripts that relied on the old tree-export default must now pass `-r -i` explicitly.
* **GitHub PR bot filter flipped** : bot-authored reviews, inline comments, and timeline comments are now kept by default (previously silently dropped). Corporate workflows where `pr-agent`, `devin-ai-integration`, `coderabbitai`, etc. are real reviewers now surface correctly. Pass `--no-bots` to restore the old filtering behavior.

### Added
* **Auto-quiet on piped stderr** : when stderr is not a TTY (e.g. redirected or consumed by another process) and neither `-q` nor `-v` was passed explicitly, progress logs are silenced automatically — no more noisy output when piping into other tools.
* **GitHub PR review section** : new top-level `## Reviews` block listing each review with `@author`, `**STATE**` (APPROVED / CHANGES_REQUESTED / COMMENTED / DISMISSED), submission timestamp, and body if any. Empty-body reviews (e.g. bare approvals) are now preserved — the state itself is the signal.
* **GitHub PR inline comment enrichment** : inline review comments now render as `@user [SIDE] L{start}-{end} (timestamp):` with diff side (LEFT/RIGHT) and multi-line ranges, under a top-level `## Inline Review Comments` grouped by file.
* **GitHub PR timestamps** : all comments and reviews now include the upstream ISO-8601 timestamp (with timezone) from the GitHub API.

### Changed
* **Friendlier Confluence flag errors** : using `-r` / `-i` / `--all-attachments` without `-o` now prints the exact command to copy-paste (with and without `-o <dir>`), instead of a generic hint.
* **GitHub PR output structure** : sections reordered to overview-first — `## Reviews` → `## Inline Review Comments` → `## Timeline Comments` → `## Git Diff`. Section headings promoted from `### ` under `## All Comments` to top-level `## `.

### Fixed
* **GitHub PR diff works from any cwd** : diff generation previously shelled out to local `git diff` / `git fetch`, which silently returned empty whenever the cwd wasn't the target repo's clone (e.g. running ctxd from `/tmp`, from a sibling repo, or when the PR branch hadn't been fetched). All modes now use GitHub API: `gh pr diff` for `full`/`compact`, `/repos/{o}/{r}/pulls/{n}/files` for `stat`. No local clone required.

## [0.2.1]

* **Confluence comments support** : Export inline comments (page annotations) and footer comments alongside page content. Comments are appended as a `## Comments` section with reply threading preserved.
* **Comment author resolution** : Resolve Confluence account IDs to display names via REST API (with caching).
* **Inline comment line numbers** : Each inline comment shows the annotated text as a blockquote with the corresponding line number in the exported Markdown (e.g. `> selection text (Line 14)`), distinguishing comments on repeated text.
* **Comment block separators** : Different annotation threads are separated by `---` for readability.

## [0.2.0]

* **Unified release** : Consolidated `pr-dump`, `confluence-dump`, and `slack-thread-dump` into ctxd. All three legacy projects are now archived.
* **Homebrew formula** : `brew install cheerchen/tap/ctxd` now available.
* **Chinese documentation** : Added README_CN.md.

## [0.1.2]

* **Jira issue support** : Added full Jira ticket dumping via [ctxd `<jira-url>`]. Supports any Atlassian Cloud Jira browse URL (`https://<site>.atlassian.net/browse/<KEY>`).
* **Jira authentication** : Reuses existing Confluence credentials (`CONFLUENCE_BASE_URL`, `CONFLUENCE_EMAIL`, `CONFLUENCE_API_TOKEN`) for Jira API access.
* **Custom field discovery** : Automatically detects and renders rich-text custom fields (e.g. `customfield_13977`) using the Jira `renderedFields` + [names] API expansion.
* **Debug mode for Jira** : [--debug] flag saves raw HTML from Jira API alongside the output file ([.debug.html]) for troubleshooting conversion issues.

---

## Pre-merge History

> The following changelogs are from the legacy projects that were merged into ctxd.
> Each entry is prefixed with its original project name.

### [confluence-dump] v0.2.1

- Support Confluence code macros conversion to Markdown code blocks
- Support drawio macro image extraction (converts to PNG preview)
- Global attachment pool for cross-page image sharing
- Improved attachment fetch error handling (graceful 400/404 warnings)
- Image download now falls back to global pool when not found in current page

### [confluence-dump] v0.2.0

- Skip exporting empty pages (pages with no content)
- Only download images referenced in the content by default (reduce size)
- Add `--all-attachments` flag to force downloading all attachments
- Add `--debug` flag to save raw HTML content for inspection
- Correctly sanitize folder names (preserving dates and numbers)
- Handle attachment download errors gracefully (continue export on 400/error)
- Folder naming now includes Page ID: `{page_id}_{title}`
- Prepend Page Title as H1 header in Markdown output

### [confluence-dump] v0.1.0

- Initial release: recursive export of Confluence pages to Markdown/HTML/JSON
- Download attachments and rewrite image links
- Add uv wrapper script for local and Homebrew-style usage

### [slack-thread-dump] v0.1.1

- Changed: Always export all messages returned by Slack API; removed `--include-bots` flag and default bot filtering.

### [slack-thread-dump] v0.1.0

- First cut of `slack-thread-dump` shell script with text/markdown output, URL parsing, and Slack API integration.
- User/channel name resolution with caching, bot filtering, and attachment listing/downloading.
- Added install helper, Homebrew formula scaffold, and docs.

### [pr-dump] v0.4.0 - 2026-02-24

#### Added
- `--clean-body` flag (default: **on**): cleans bot-generated HTML noise from PR body
  - Reformats "File Walkthrough" HTML tables (injected by PR bots such as CodiumAI/pr-agent) into compact plain text: `filename: description (+N/-M)`
  - Strips `&nbsp;`, HTML tags, and long GitHub diff hash links
  - Use `--no-clean-body` to opt out
- Code review comments now grouped by file under `####` headings, preserving conversation order within each file
- Multi-line comment bodies indented with 2 spaces so code blocks and suggestions stay inside their list item
- `(line null)` no longer appears for file-level review comments (line number omitted when unavailable)

#### Changed
- Default output format changed from `text` to `markdown` (default output file is now `pr-<number>.md`)
- Timeline comments and review summaries reformatted: removed `---` separators and redundant `Timeline comment from` / `Review summary from` prefixes; entries separated by blank lines

#### Token Impact
- Typical savings: **~20–25%** fewer tokens vs v0.3.0 on PRs with bot-generated File Walkthrough tables

### [pr-dump] v0.3.0 - 2026-01-20

#### Added
- Support for full GitHub PR URL as input (works anywhere without git repository)
- Two input modes:
  - **URL mode**: `pr-dump https://github.com/owner/repo/pull/123` (works anywhere)
  - **Number mode**: `pr-dump 123` (requires git repository)
- Smart default output filename: `pr-<number>.txt` or `pr-<number>.md` based on format
- Enhanced error messages with clear troubleshooting guidance

#### Changed
- Default output filename changed from `review.txt` to `pr-<number>.txt`
- URL mode no longer requires being inside a git repository
- Improved repository detection and validation
- Better error handling with specific error messages

### [pr-dump] v0.2.0 - 2025-12-17

#### Added
- New `--diff-mode` / `-d` option with three modes:
  - `full` (default): Complete diff with all code changes
  - `compact`: Only file paths, line numbers, and function context
  - `stat`: Only file change statistics
- Compact mode reduces token consumption by showing only file paths and line ranges

### [pr-dump] v0.1.1 - 2025-11-14

#### Fixed
- Fixed issue where git diff could include unrelated changes from current branch
- Now uses PR's exact commit SHA to generate accurate diff
- Added fetching of PR head branch to ensure correct commit references

### [pr-dump] v0.1.0 - 2025-09-16

#### Added
- Complete PR context extraction (metadata, comments, diff)
- Multiple output formats (text, markdown)
- CLI interface with full argument support
- Bot comment filtering
- Installation script