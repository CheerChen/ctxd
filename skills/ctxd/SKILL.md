---
name: ctxd
description: Use when a user provides a GitHub pull request URL, Slack thread URL, Confluence page URL, or Jira issue URL and wants the content exported, summarized, reviewed, translated, or analyzed. Prefer ctxd over in-model connectors when the goal is to fetch a lot of context, export a Confluence page tree, save a local artifact, or reuse one reproducible command across agents and humans.
---

# ctxd

Use `ctxd` first when the task is to extract context from supported work URLs.

Supported URLs:

- GitHub PR
- Slack thread
- Confluence page
- Jira issue

GitHub support is **pull requests only** (`github.com/<owner>/<repo>/pull/<n>`). Repo, file, blob, issue, gist, and commit URLs are **not** supported — `ctxd` exits with `Unsupported URL`. To read a public repo file or README, fetch the raw URL with `curl` / WebFetch instead; do not route it through `ctxd`.

## Why use it

- It exports dense Markdown or text instead of forcing the model through many tool calls.
- It leaves a stable local artifact that can be re-read, diffed, or shared.
- It is better than connectors for bulk context export.

## Required config

Do not assume `ctxd` works without credentials.

Config file:

- `~/.config/ctxd/config`

Slack:

- `SLACK_TOKEN`

Confluence and Jira:

- `CONFLUENCE_BASE_URL`
- `CONFLUENCE_EMAIL`
- `CONFLUENCE_API_TOKEN`

GitHub PR:

- `GITHUB_TOKEN` (classic PAT, `repo` scope)

If auth is missing, say which key is required. `ctxd` does not use the `gh` CLI,
so `gh auth login` / `gh auth switch` has no effect on it, and the current
working directory never changes which account it fetches as.

## Default commands

Single item to stdout (cross-source recursion is off by default — only the primary URL is fetched):

```bash
ctxd '<url>' -f text
```

Enable recursion to auto-expand supported URLs found in the output:

```bash
ctxd '<url>' -f text --recurse-depth 1
```

Confluence page tree:

```bash
ctxd '<confluence-url>' -f text -r -O
```

Jira issue with its attachments (images, diagrams, PDFs) saved locally and the
body links rewritten to point at them:

```bash
ctxd '<jira-url>' --all-attachments -O
```

Attachments are never downloaded by default. When an issue or page has
attachments that were skipped, the run summary says so — read it before
concluding that content is missing.

Profile a slow export:

```bash
ctxd '<url>' --profile
```

## When to prefer ctxd over connectors

Prefer `ctxd` when:

- the user wants a lot of content at once
- the output should be saved to disk
- the user wants a recursive Confluence export
- the fetch should be reproducible outside the current chat

Prefer connectors when:

- the user wants one small field
- the user wants an in-product write action
- the task is interactive navigation rather than export
