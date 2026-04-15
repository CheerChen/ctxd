# Changelog

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