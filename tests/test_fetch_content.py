"""The deploy step that pulls the private lessons repo.

It must never fail a deploy and never expose the token: not in argv (process
list), not in the clone's .git/config, not in the build log — even when git's
own error text repeats it.
"""

import base64
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "classes"))

import fetch_content  # noqa: E402

pytestmark = pytest.mark.unit

TOKEN = "ghp_SECRET1234567890abcdefghij"
ENV = {"MP_CLASSES_TOKEN": TOKEN, "MP_CLASSES_REPO": "o/r"}


class Git:
    """Records every git invocation and answers with a fixed result."""

    def __init__(self, code=0, stderr=""):
        self.calls, self.code, self.stderr = [], code, stderr

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        return types.SimpleNamespace(returncode=self.code, stdout="", stderr=self.stderr)


def test_no_token_means_no_pull_and_no_failure(tmp_path):
    git = Git()
    assert fetch_content.main(env={}, run=git, dest=tmp_path / "classes") == 0
    assert git.calls == []


def test_the_token_rides_in_git_config_env_never_in_argv(tmp_path, capsys):
    git = Git()
    assert fetch_content.main(env=ENV, run=git, dest=tmp_path / "classes") == 0
    (cmd, kw), = git.calls
    assert cmd[:2] == ["git", "clone"] and "https://github.com/o/r.git" in cmd
    assert not any(TOKEN in part for part in cmd)                     # not in the process list
    header = kw["env"]["GIT_CONFIG_VALUE_0"]
    assert base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode() in header
    assert kw["env"]["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err


def test_an_existing_clone_is_scrubbed_then_fast_forwarded(tmp_path):
    dest = tmp_path / "classes"
    (dest / ".git").mkdir(parents=True)
    git = Git()
    fetch_content.main(env=ENV, run=git, dest=dest)
    cmds = [c for c, _ in git.calls]
    assert cmds[0][-4:] == ["remote", "set-url", "origin", "https://github.com/o/r.git"]   # drops any old token
    assert "pull" in cmds[1] and "--ff-only" in cmds[1]
    assert not any(TOKEN in part for c in cmds for part in c)


def test_a_failed_pull_never_fails_the_deploy_or_leaks(tmp_path, capsys):
    git = Git(code=128, stderr=f"fatal: auth {TOKEN} failed")
    assert fetch_content.main(env=ENV, run=git, dest=tmp_path / "classes") == 0
    out = capsys.readouterr()
    assert TOKEN not in out.out + out.err and "empty catalogue" in out.err


def test_redaction_happens_before_the_log_is_trimmed(tmp_path, capsys):
    # A token straddling the trim point must not leave a partial token behind.
    git = Git(code=1, stderr="x" * (fetch_content.MAX_LOG - 40) + TOKEN)
    fetch_content.main(env=ENV, run=git, dest=tmp_path / "classes")
    err = capsys.readouterr().err
    assert TOKEN[:12] not in err


def test_git_blowing_up_never_fails_the_deploy(tmp_path, capsys):
    def boom(cmd, **kw):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad byte")
    assert fetch_content.main(env=ENV, run=boom, dest=tmp_path / "classes") == 0
    assert "empty catalogue" in capsys.readouterr().err


@pytest.mark.parametrize("repo", ["../x", "o/..", ".hidden/r", "o", "o/r/extra", "o/r;rm -rf /", "-o/r"])
def test_a_bad_repo_name_is_skipped_not_run(tmp_path, repo):
    git = Git()
    assert fetch_content.main(env={**ENV, "MP_CLASSES_REPO": repo}, run=git, dest=tmp_path / "c") == 0
    assert git.calls == []
