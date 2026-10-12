from __future__ import annotations

import sys
from pathlib import Path

import pytest

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


class FakeDumper:
    """Records what the CLI hands a dumper; does no I/O.

    ``kwargs`` is everything the CLI passed to the constructor; ``output``
    is the path the CLI finally resolved (it may reassign it after
    construction).  The class-level ``instances`` list keeps every dumper
    the CLI built in this test.
    """

    default_name = "out.md"
    instances: list["FakeDumper"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.output = kwargs.get("output")
        self.url = kwargs.get("url", "")
        self.fmt = kwargs.get("fmt", "md")
        self.quiet = kwargs.get("quiet")
        self.verbose = kwargs.get("verbose")
        type(self).instances.append(self)

    def default_filename(self) -> str:
        return self.default_name

    def render(self) -> str:
        return "fake content\n"

    def log(self, message: str) -> None:
        pass

    def dump(self) -> None:
        pass


@pytest.fixture
def fake_source(monkeypatch):
    """``fake_source(Source.X, default_name)`` routes every URL to a
    FakeDumper subclass for that source and returns the class."""
    from ctxd.dumpers import DUMPERS

    def install(source, default_name: str = "out.md"):
        cls = type(f"Fake{source.name}", (FakeDumper,), {"default_name": default_name, "instances": []})
        monkeypatch.setattr("ctxd.cli.detect", lambda _url: source)
        monkeypatch.setitem(DUMPERS, source, cls)
        return cls

    return install
