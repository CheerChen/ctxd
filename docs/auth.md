# Authentication & Configuration

**📖 [中文](auth_cn.md) · [Home](../README.md) · [CLI Reference](cli.md)**

Before `ctxd` (or its agent skill) can fetch a URL, the credentials for that source must be configured.

## How configuration is loaded

`ctxd` reads credentials from two places, in order of precedence:

1. **Environment variables** (highest precedence — useful for CI and one-off overrides)
2. **Config file**: `~/.config/ctxd/config`

Set up the config file once for persistent local use:

```bash
mkdir -p ~/.config/ctxd
cat >> ~/.config/ctxd/config <<'EOF'
GITHUB_TOKEN=ghp_...
SLACK_TOKEN=xoxp-...
CONFLUENCE_BASE_URL=https://your-site.atlassian.net
CONFLUENCE_EMAIL=you@example.com
CONFLUENCE_API_TOKEN=your-token
EOF
chmod 600 ~/.config/ctxd/config
```

If `~/.config/ctxd/config` is readable by group or others, `ctxd` prints a one-shot warning on stderr with the exact `chmod 600` command to fix it.

---

## GitHub PR

| Key | Value |
|-----|-------|
| `GITHUB_TOKEN` | Classic Personal Access Token (`ghp_...`) with the **`repo`** scope |

Create a [classic PAT](https://github.com/settings/tokens/new) and select **`repo`**. This covers every repository you have access to plus all public ones.

- **SAML SSO organizations**: after creating the token, click **Configure SSO** on the token list page and authorize that organization, otherwise the GitHub API returns `404` as if the repository did not exist.
- **Why not fine-grained PATs?** Fine-grained tokens are restricted to a single resource owner, so a token scoped to one organization cannot read public repositories elsewhere.
- **Independent of `gh` CLI**: `ctxd` does not read `gh auth` state, and your current working directory never changes which account it fetches as.

---

## Slack Thread

| Key | Value |
|-----|-------|
| `SLACK_TOKEN` | Slack **User Token** (`xoxp-...`) |

Required OAuth User Token Scopes:
- `channels:history`, `groups:history`, `im:history`, `mpim:history`
- `users:read`
- `files:read` *(required only when using `--download-files`)*

Obtain at [api.slack.com/apps](https://api.slack.com/apps) → Your App → **OAuth & Permissions** → **User Token Scopes** → Install/Reinstall to Workspace.

---

## Confluence & Jira

Confluence and Jira share the same Atlassian Cloud credentials. All three keys are required:

| Key | Value |
|-----|-------|
| `CONFLUENCE_BASE_URL` | Your Atlassian site root, e.g. `https://your-site.atlassian.net` |
| `CONFLUENCE_EMAIL` | Your Atlassian account email |
| `CONFLUENCE_API_TOKEN` | Atlassian API token |

Create an API token at [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens).
