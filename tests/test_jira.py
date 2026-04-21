from unittest.mock import MagicMock, patch

from ctxd.jira.url_parser import parse_jira_url
from ctxd.router import Source, detect


def test_parse_jira_url() -> None:
    site, issue_key = parse_jira_url(
        "https://kinto-dev.atlassian.net/browse/INFRA-10588"
    )
    assert site == "https://kinto-dev.atlassian.net"
    assert issue_key == "INFRA-10588"


def test_parse_jira_url_different_project() -> None:
    site, issue_key = parse_jira_url(
        "https://myteam.atlassian.net/browse/DEV-42"
    )
    assert site == "https://myteam.atlassian.net"
    assert issue_key == "DEV-42"


def test_parse_jira_url_invalid() -> None:
    try:
        parse_jira_url("https://kinto-dev.atlassian.net/wiki/spaces/FOO")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_detect_jira_url() -> None:
    source = detect("https://kinto-dev.atlassian.net/browse/INFRA-10588")
    assert source is Source.JIRA


def test_detect_confluence_url_not_jira() -> None:
    source = detect("https://kinto-dev.atlassian.net/wiki/spaces/KIDPF/pages/123/title")
    assert source is Source.CONFLUENCE


def test_jira_dumper_transform() -> None:
    from ctxd.dumpers.jira import JiraDumper

    dumper = JiraDumper(
        url="https://kinto-dev.atlassian.net/browse/INFRA-10588",
        output=None,
        fmt="md",
    )

    raw = {
        "key": "INFRA-10588",
        "fields": {
            "summary": "Test Issue",
            "status": {"name": "In Progress"},
            "priority": {"name": "High"},
            "issuetype": {"name": "Task"},
            "assignee": {"displayName": "Alice"},
            "reporter": {"displayName": "Bob"},
            "labels": ["infra", "urgent"],
            "components": [{"name": "Backend"}],
            "created": "2026-03-01T10:00:00.000+0000",
            "updated": "2026-03-10T12:00:00.000+0000",
            "description": "This is a test description",
            "subtasks": [],
            "issuelinks": [],
        },
        "rendered": {
            "description": "<p>This is a <strong>test</strong> description</p>",
        },
        "comments": [
            {
                "author": {"displayName": "Charlie"},
                "created": "2026-03-05T09:00:00.000+0000",
                "body": "Working on this now.",
                "renderedBody": "<p>Working on this now.</p>",
            }
        ],
    }

    result = dumper.transform(raw)
    assert "# [INFRA-10588] Test Issue" in result
    assert "In Progress" in result
    assert "High" in result
    assert "Alice" in result
    assert "Bob" in result
    assert "infra" in result
    assert "Backend" in result
    assert "test" in result
    assert "Charlie" in result
    assert "Working on this now" in result
    assert "| **URL** | https://kinto-dev.atlassian.net/browse/INFRA-10588 |" in result


def test_jira_dumper_transform_text() -> None:
    from ctxd.dumpers.jira import JiraDumper

    dumper = JiraDumper(
        url="https://kinto-dev.atlassian.net/browse/INFRA-10588",
        output=None,
        fmt="text",
    )

    raw = {
        "key": "INFRA-10588",
        "fields": {
            "summary": "Test Issue",
            "status": {"name": "Done"},
            "priority": {"name": "Low"},
            "issuetype": {"name": "Bug"},
            "assignee": None,
            "reporter": {"displayName": "Eve"},
            "labels": [],
            "components": [],
            "created": "2026-03-01T10:00:00.000+0000",
            "updated": "2026-03-10T12:00:00.000+0000",
            "description": "Plain description",
            "subtasks": [],
            "issuelinks": [],
        },
        "rendered": {
            "description": "",
        },
        "comments": [],
    }

    result = dumper.transform(raw)
    assert "JIRA ISSUE" in result
    assert "INFRA-10588" in result
    assert "Done" in result
    assert "Unassigned" in result
    assert "Plain description" in result
    assert "URL:        https://kinto-dev.atlassian.net/browse/INFRA-10588" in result


def test_jira_dumper_default_filename() -> None:
    from ctxd.dumpers.jira import JiraDumper

    dumper = JiraDumper(
        url="https://kinto-dev.atlassian.net/browse/INFRA-10588",
        output=None,
        fmt="md",
    )
    assert dumper.default_filename() == "jira-INFRA-10588.md"

    dumper_txt = JiraDumper(
        url="https://kinto-dev.atlassian.net/browse/INFRA-10588",
        output=None,
        fmt="text",
    )
    assert dumper_txt.default_filename() == "jira-INFRA-10588.txt"


# --- Converter unit tests (real HTML fragments from Jira API) ---

from ctxd.jira.converter import (
    convert_double_brace_monospace,
    convert_tt_to_code,
    preprocess_jira_html,
    rejoin_split_dollar_variables,
    repair_broken_preformatted,
)


def test_convert_tt_to_code() -> None:
    html = "<p>Use <tt>ecs:runTask.sync</tt> to start tasks</p>"
    result = convert_tt_to_code(html)
    assert "<code>ecs:runTask.sync</code>" in result
    assert "<tt>" not in result


def test_convert_double_brace_simple() -> None:
    html = "<p>{{producer}}をlambda名に含む</p>"
    result = convert_double_brace_monospace(html)
    assert "<code>producer</code>" in result
    assert "{{" not in result


def test_convert_double_brace_with_html_tags() -> None:
    """Jira splits {{...}} content across <p> tags."""
    html = "{{<p>sid</p>/xxx}}"
    result = convert_double_brace_monospace(html)
    assert "<code>" in result
    assert "sid" in result
    assert "/xxx" in result


def test_convert_double_brace_multiline() -> None:
    html = "{{${env}-db-masking-\nproducer-prepare-execution-role}}"
    result = convert_double_brace_monospace(html)
    assert "<code>" in result
    assert "db-masking" in result


def test_rejoin_dollar_variable_newline() -> None:
    html = "Environment: $\n{env}<br/>"
    result = rejoin_split_dollar_variables(html)
    assert "${env}" in result


def test_rejoin_dollar_variable_across_p_tag() -> None:
    html = "alias/$</p>\n{env}-db-masking"
    result = rejoin_split_dollar_variables(html)
    assert "${env}" in result


def test_rejoin_dollar_variable_with_br() -> None:
    html = 'arn:aws:iam::${account_id}:role/$<br/>\n{env}'
    result = rejoin_split_dollar_variables(html)
    assert "${env}" in result
    # ${account_id} should remain intact
    assert "${account_id}" in result


def test_repair_broken_preformatted() -> None:
    html = (
        '<div class="preformatted panel" style="border-width: 1px;">'
        '<div class="preformattedContent panelContent">'
        "<pre></pre>"
        "</div></div>"
        'line1<br/>\nline2<br/>\nline3'
        '<div class="preformatted panel" style="border-width: 1px;">'
        '<div class="preformattedContent panelContent">'
        "<pre></pre>"
        "</div></div>"
    )
    result = repair_broken_preformatted(html)
    assert "<pre><code>" in result
    assert "line1" in result
    assert "line2" in result
    assert "</code></pre>" in result


def test_preprocess_pipeline_combined() -> None:
    """Test the full pipeline with realistic Jira HTML."""
    html = (
        "<p>Deploy to <tt>production</tt> using {{deploy-tool}}</p>"
        "<p>Set $\n{env} variable</p>"
    )
    result = preprocess_jira_html(html)
    assert "<code>production</code>" in result
    assert "<code>deploy-tool</code>" in result
    assert "${env}" in result
