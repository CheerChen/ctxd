"""Dumpers for different context sources."""

from ctxd.dumpers.base import BaseDumper
from ctxd.dumpers.confluence import ConfluenceDumper
from ctxd.dumpers.github_pr import GitHubPRDumper
from ctxd.dumpers.jira import JiraDumper
from ctxd.dumpers.slack import SlackDumper
from ctxd.router import Source

# Single place that maps a detected source to its dumper class.  Adding a
# new source means adding a Source member, a route, and one entry here.
DUMPERS: dict[Source, type[BaseDumper]] = {
    Source.GITHUB_PR: GitHubPRDumper,
    Source.SLACK_THREAD: SlackDumper,
    Source.CONFLUENCE: ConfluenceDumper,
    Source.JIRA: JiraDumper,
}

__all__ = [
    "BaseDumper",
    "ConfluenceDumper",
    "DUMPERS",
    "GitHubPRDumper",
    "JiraDumper",
    "SlackDumper",
]
