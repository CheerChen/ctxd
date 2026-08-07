from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


class FakeGitHubClient:
    """Stand-in for ``GitHubClient`` — canned payloads, recorded calls.

    *fail* (an exception instance) makes every endpoint raise, which is how
    tests simulate a token that cannot see the repo.
    """

    def __init__(
        self,
        pull: dict | None = None,
        pages: dict[str, list[dict]] | None = None,
        diff: str = "",
        fail: Exception | None = None,
    ):
        self.pull = pull if pull is not None else {"title": "Test PR", "body": "Test body"}
        self.pages = pages or {}
        self.diff = diff
        self.fail = fail
        self.paths: list[str] = []

    def get_pull(self, owner: str, repo: str, number: str) -> dict:
        if self.fail:
            raise self.fail
        return self.pull

    def paginate(self, path: str) -> list[dict]:
        self.paths.append(path)
        if self.fail:
            raise self.fail
        return self.pages.get(path, [])

    def get_diff(self, owner: str, repo: str, number: str) -> str:
        if self.fail:
            raise self.fail
        return self.diff


def install_fake_github(monkeypatch, **kwargs) -> FakeGitHubClient:
    """Patch the GitHub dumper's token lookup and client with a fake.

    Returns the fake so callers can assert on the paths it saw.
    """
    fake = FakeGitHubClient(**kwargs)
    monkeypatch.setattr("ctxd.dumpers.github_pr.get_github_token", lambda: "test-token")
    monkeypatch.setattr("ctxd.dumpers.github_pr.GitHubClient", lambda token: fake)
    return fake
