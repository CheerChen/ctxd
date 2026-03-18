# ctxd

Unified context dumper for LLM workflows.

**📖 [中文文档](README_CN.md)**

## Supported Sources

| Source | URL Pattern |
|--------|-------------|
| GitHub PR | `https://github.com/<owner>/<repo>/pull/<number>` |
| Slack Thread | `https://*.slack.com/archives/...` or `.../client/.../thread/...` |
| Confluence | `https://*.atlassian.net/wiki/...` |
| Jira | `https://*.atlassian.net/browse/<KEY>` |

## Installation

### Homebrew (recommended)

```bash
brew tap cheerchen/tap
brew install ctxd
```

### From source

```bash
cd ctxd
uv sync --group dev
```

## Shell Alias

```bash
# zsh / bash
eval "$(ctxd init zsh)"

# fish
ctxd init fish | source
```

This enables the `ctx` shorthand for `ctxd`.

## Global Options

| Option | Description |
|--------|-------------|
| `-o, --output <path>` | Write to file/directory (default: stdout) |
| `-o auto` | Auto-generate output path by source |
| `-f, --format text\|md` | Output format (default: `md`) |
| `-q, --quiet` | Suppress progress logs |
| `-v, --verbose` | Verbose logging |

Options can be placed before or after the URL (e.g. both `ctxd -q <url>` and `ctxd <url> -q`).

---

## GitHub PR

Export PR metadata, comments, and code changes.

### Prerequisites

Install and authenticate [GitHub CLI](https://cli.github.com/):

```bash
brew install gh
gh auth login
```

### Usage

```bash
ctxd https://github.com/owner/repo/pull/123
ctxd https://github.com/owner/repo/pull/123 -o pr-123.md
ctxd -o auto https://github.com/owner/repo/pull/123
```

### Options

| Option | Description |
|--------|-------------|
| `-d, --diff-mode full\|compact\|stat` | Diff output mode (default: `compact`) |
| `--clean-body / --no-clean-body` | Strip bot-injected HTML noise from PR body (default: on) |

---

## Slack Thread

Export a full Slack thread with username resolution and attachments.

### Prerequisites

Requires a Slack User Token (`xoxp-...`) with the following scopes:
- `channels:history`, `groups:history`, `im:history`, `mpim:history`
- `users:read`
- `files:read` (if downloading attachments)

Obtain at: [api.slack.com/apps](https://api.slack.com/apps) → Your App → OAuth & Permissions → User Token.

Configure the token (pick one):

```bash
# Option 1: Environment variable
export SLACK_TOKEN="xoxp-..."

# Option 2: Config file
mkdir -p ~/.config/ctxd
echo 'SLACK_TOKEN=xoxp-...' >> ~/.config/ctxd/config
```

### Usage

```bash
# New URL format
ctxd https://app.slack.com/client/T.../C.../thread/C...-1234567890.123456

# Archive URL format
ctxd https://your-workspace.slack.com/archives/C.../p...?thread_ts=...
```

### Options

| Option | Description |
|--------|-------------|
| `--download-files` | Download attachments to `./attachments` |
| `--raw` | Keep original Slack mrkdwn markup |

---

## Confluence

Recursively export Confluence pages to Markdown with image downloading.

### Prerequisites

Requires an Atlassian API Token. Obtain at: [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens).

Configure (all three environment variables are required):

```bash
export CONFLUENCE_BASE_URL="https://your-site.atlassian.net"
export CONFLUENCE_EMAIL="you@example.com"
export CONFLUENCE_API_TOKEN="your-token"
```

Or add to config file `~/.config/ctxd/config`.

### Usage

```bash
# Export to directory (recursive + images, default behavior)
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456 -o ./output

# stdout only (requires disabling recursive and images)
ctxd https://your-site.atlassian.net/wiki/spaces/SPACE/pages/123456 --no-recursive --no-include-images
```

> **Note**: Recursive export or image download requires `-o <dir>`, stdout is not supported.

### Options

| Option | Description |
|--------|-------------|
| `-r, --recursive / --no-recursive` | Include child pages (default: on) |
| `-i, --include-images / --no-include-images` | Download images (default: on) |
| `--all-attachments` | Download all attachments (default: only referenced images) |
| `--debug` | Save raw HTML for debugging |

---

## Jira

Export full Jira issue content (description, comments, custom fields).

### Prerequisites

Shares authentication with Confluence, using the same three environment variables:

```bash
export CONFLUENCE_BASE_URL="https://your-site.atlassian.net"
export CONFLUENCE_EMAIL="you@example.com"
export CONFLUENCE_API_TOKEN="your-token"
```

### Usage

```bash
ctxd https://your-site.atlassian.net/browse/PROJECT-123
ctxd https://your-site.atlassian.net/browse/PROJECT-123 -o issue.md
```

### Options

| Option | Description |
|--------|-------------|
| `--debug` | Save raw HTML (`.debug.html`) for troubleshooting conversion issues |

## License

[MIT](LICENSE)
