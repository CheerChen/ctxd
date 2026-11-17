# 认证与配置

**📖 [English](auth.md) · [返回首页](../README_CN.md) · [CLI 参考手册](cli_cn.md)**

在使用 `ctxd`（或其配套 Agent Skill）抓取 URL 之前，需要先配好对应数据源的凭证。

## 配置加载优先级

`ctxd` 按以下优先级读取配置：

1. **环境变量**（优先级最高，适合 CI 或单次临时覆盖）
2. **配置文件**：`~/.config/ctxd/config`

本地长期使用建议一次性写好配置文件并收紧权限：

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

如果 `~/.config/ctxd/config` 对同组或其他用户可读，`ctxd` 会在 stderr 打印一条一次性提醒，并附上 `chmod 600` 修复命令。

---

## GitHub PR

| 配置项 | 说明 |
|--------|------|
| `GITHUB_TOKEN` | 勾选了 **`repo`** 权限的 Classic PAT（`ghp_...`） |

前往 [classic PAT 页面](https://github.com/settings/tokens/new) 创建，勾选 **`repo`**，即可覆盖你有权访问的所有私有仓库以及全部公开仓库。

- **开启了 SAML SSO 的组织**：创建后需在 Token 列表页点击 **Configure SSO** 对目标组织单独授权，否则 GitHub API 会返回 `404`（表现得像仓库不存在）。
- **为什么不用 fine-grained PAT？** Fine-grained PAT 只能绑定单一 resource owner，绑定到某个组织后就无法读取其他 owner 名下的公开仓库。
- **与 `gh` CLI 无关**：`ctxd` 不读取 `gh auth` 登录态，当前工作目录也不会影响它使用的账号。

---

## Slack Thread

| 配置项 | 说明 |
|--------|------|
| `SLACK_TOKEN` | Slack **User Token**（`xoxp-...`） |

需要以下 User Token Scopes：
- `channels:history`, `groups:history`, `im:history`, `mpim:history`
- `users:read`
- `files:read`（仅在使用 `--download-files` 下载附件时需要）

获取路径：[api.slack.com/apps](https://api.slack.com/apps) → 你的 App → **OAuth & Permissions** → **User Token Scopes** → 安装到工作区后复制 `xoxp-...`。

---

## Confluence 与 Jira

Confluence 与 Jira 共享同一套 Atlassian Cloud 凭证，三项均必填：

| 配置项 | 说明 |
|--------|------|
| `CONFLUENCE_BASE_URL` | Atlassian 站点根地址，如 `https://your-site.atlassian.net` |
| `CONFLUENCE_EMAIL` | Atlassian 账号邮箱 |
| `CONFLUENCE_API_TOKEN` | Atlassian API Token |

前往 [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens) 创建 API Token。
