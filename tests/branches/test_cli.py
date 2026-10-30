# Do not run these tests with the -s flag to pytest

import json
import os
import re
import shutil
import subprocess
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from pytest_httpserver.httpserver import HTTPServer

GIT_TMP_DIRPATH_LOCAL = os.path.join(os.path.dirname(__file__), "test_cli_local")
GIT_TMP_DIRPATH_ORIGIN = os.path.join(os.path.dirname(__file__), "test_cli_origin")
GIT_TMP_DIRPATH_WORKTREE = os.path.join(os.path.dirname(__file__), "test_cli_worktree")
SRC_DIRPATH = os.path.join(Path(__file__).resolve().parents[2], "src")


@pytest.fixture(autouse=True)
def around_each():
  shutil.rmtree(GIT_TMP_DIRPATH_ORIGIN, ignore_errors=True)
  shutil.rmtree(GIT_TMP_DIRPATH_LOCAL, ignore_errors=True)
  shutil.rmtree(GIT_TMP_DIRPATH_WORKTREE, ignore_errors=True)
  os.makedirs(GIT_TMP_DIRPATH_ORIGIN)
  os.makedirs(GIT_TMP_DIRPATH_LOCAL)
  run_command("git init --bare .", GIT_TMP_DIRPATH_ORIGIN)
  yield
  shutil.rmtree(GIT_TMP_DIRPATH_WORKTREE, ignore_errors=True)
  shutil.rmtree(GIT_TMP_DIRPATH_LOCAL, ignore_errors=True)
  shutil.rmtree(GIT_TMP_DIRPATH_ORIGIN, ignore_errors=True)


def run_command(command: str, dirpath: str = GIT_TMP_DIRPATH_LOCAL) -> CompletedProcess[str]:
  return subprocess.run(
    f"cd '{dirpath}' && {command}", shell=True, capture_output=True, text=True, check=False
  )


def run_prep(*commands: str):
  result = run_command(" && ".join(commands))
  assert result.returncode == 0, f"Prep stdout:\n{result.stdout}\nPrep stderr:\n{result.stderr}"


def git_graph(dirpath: str = GIT_TMP_DIRPATH_LOCAL) -> str:
  return run_command(
    "git log --graph --all --author-date-order --pretty=format:'%<|(10)%gd%s%d'", dirpath
  ).stdout


def assert_graph(expected: str, dirpath: str = GIT_TMP_DIRPATH_LOCAL):
  actual = git_graph(dirpath)
  actual_lines = [line.rstrip() for line in actual.splitlines()]
  assert actual_lines == textwrap.dedent(expected).strip().splitlines(), (
    f"Unexpected git graph:\n{actual}"
  )


def run_test(
  expected_graph: str | None,
  trigger_command: str,
  expected_stdout: str | list[str],
  expected_returncode=0,
  cleanup_command: str | None = None,
  httpserver: HTTPServer | None = None,
  trigger_command_dir: str | None = None,
  directory: str | None = None,
):
  if expected_graph is not None:
    assert_graph(expected_graph)

  envars = [f"PYTHONPATH='{SRC_DIRPATH}'"]
  if httpserver is not None:
    envars += [
      "GITHUB_PROTO='http'",
      f"GITHUB_DOMAIN='{httpserver.host}:{httpserver.port}'",
      "GITHUB_TOKEN='testtoken'",
    ]

  envars = " ".join(envars)
  print(envars)
  if directory:
    command = [f"cd '{directory}'"]
  else:
    command = [f"cd '{GIT_TMP_DIRPATH_LOCAL}'"]
  if trigger_command_dir:
    command.append(f"cd {trigger_command_dir}")
  command.append(f"{envars} python -m {trigger_command}")

  result = subprocess.run(
    " && ".join(command),
    shell=True,
    capture_output=True,
    text=True,
    check=False,
  )

  if "SAVE_CLI_RESULT" in os.environ:
    with open(os.path.join(os.path.dirname(__file__), "test_cli_result.txt"), "w") as result_file:
      result_file.write(result.stdout)

    with open(os.path.join(os.path.dirname(__file__), "test_cli_result.py"), "w") as result_file:
      result_file.write(
        f"{json.dumps(result.stdout.splitlines(), indent=2, ensure_ascii=False)},\n"
      )

  assert result.returncode == expected_returncode, (
    f"Unexpected returncode {result.returncode}. Full output:\n{result.stdout}\nSTDERR:\n{result.stderr}"
  )

  result_lines = result.stdout.splitlines()

  if isinstance(expected_stdout, str):
    expected_stdout = expected_stdout.splitlines()

  assert len(result_lines) == len(expected_stdout), (
    f"Unexpected line length {len(result_lines)}. Full output:\n{result.stdout}"
  )
  for idx, (result_line, expected_line) in enumerate(zip(result_lines, expected_stdout)):
    assert re.fullmatch(expected_line, result_line), (
      f"Line {idx + 1}\n"
      f"Expected:\n{expected_line!r}\n"
      f"Got:\n{result_line!r}\n"
      f"Full output:\n{result.stdout}"
    )

  if len(cleanup_command or "") > 0:
    subprocess.run(f"cd '{GIT_TMP_DIRPATH_LOCAL}' && {cleanup_command}", shell=True, check=False)


def commit(
  name: str, date: datetime | None = None, author: str | None = None, file: str | None = None
) -> str:
  """`file` is the file to write to, without extension. Defaults to `name`."""
  ret = f"echo '{name}.txt' > {file or name}.txt && git add -A && "

  if date:
    # Committer date too, so the order in `git_graph` doesn't depend on timing
    tformat = "%Y-%m-%dT%H:%M:%S%z"
    ret += f"GIT_COMMITTER_DATE='{date.strftime(tformat)}' git commit -m '{name}'"
    ret += f" --date='{date.strftime(tformat)}'"
  else:
    ret += f"git commit -m '{name}'"

  if author:
    ret += f" --author='{author}'"

  return ret


def set_mockserver_expectations(httpserver, github_requests_expected):
  for expected_branch, expected_payload in github_requests_expected:
    httpserver.expect_ordered_request(
      "/repos/branches/test_cli_origin/pulls",
      method="GET",
      query_string={"head": f"branches:{expected_branch}", "state": "all"},
    ).respond_with_json(expected_payload, status=200)


def test_mockserver(httpserver):
  """
  Description:
    Tests that PR info from the GitHub API shows up in the table, and that a merged PR whose head
    is exactly the local sha suggests deleting the branch.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  set_mockserver_expectations(
    httpserver,
    [
      (
        "main",
        [],
      ),
      (
        "branch1",
        [
          {
            "number": 123,
            "title": "Fix thing",
            "head": {"sha": "5259dcf3e0e9b774689f5fb761e07d25f6683fd5"},
            "html_url": "http://localhost/branches/test_cli_origin/pull/123",
            "user": {"login": "santi-h"},
          }
        ],
      ),
    ],
  )

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    commit("B", now + sec * 2),
    "git checkout -b branch1",
    commit("C", now + sec * 3),
    "git checkout main",
    commit("D", now + sec * 4),
    "git push",
  )
  run_test(
    r"""
    *         D (HEAD -> main, origin/main)
    | *       C (branch1)
    |/
    *         B
    *         A
    """,
    "branches",
    [
      r"                                                                ",
      r" Origin - Local  Age <- -> Branch  Base PR                      ",
      r" ────────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                                 ",
      r"          \w{5}    0  1 1  branch1      #123 \(5259d\) by santi-h ",
      r"                                                                ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout main",
      r"",
    ],
    httpserver=httpserver,
  )

  # If the PR is merged and the HEAD sha of the PR is exactly the same as the local sha, suggest
  # deletion.
  set_mockserver_expectations(
    httpserver,
    [
      (
        "main",
        [],
      ),
      (
        "branch1",
        [
          {
            "number": 123,
            "title": "Fix thing",
            "head": {"sha": run_command("git rev-parse branch1").stdout.strip()},
            "html_url": "http://localhost/branches/test_cli_origin/pull/123",
            "user": {"login": "santi-h"},
            "merged_at": "2026-02-14T16:31:13Z",
          }
        ],
      ),
    ],
  )

  run_prep("git checkout branch1")
  run_test(
    r"""
    *         D (origin/main, main)
    | *       C (HEAD -> branch1)
    |/
    *         B
    *         A
    """,
    "branches",
    [
      r"                                                                ",
      r" Origin - Local  Age <- -> Branch  Base PR                      ",
      r" ────────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                                 ",
      r"          \w{5}    0  1 1  branch1      #123 \(\w{5}\) by santi-h ",
      r"                                                                ",
      r"git checkout main && \\",
      r"git branch -D branch1",
      r"",
    ],
    httpserver=httpserver,
  )


def test_merged_base(httpserver: HTTPServer):
  """
  Description:
    Tests what happens when the base of a stacked branch has a merged PR: the base gets deleted and
    the stacked branch gets rebased onto main.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git checkout -b branch2",
    commit("C", now + sec * 3),
    "git checkout main",
    commit("D", now + sec * 4),
    "git push",
  )
  run_test(
    r"""
    *         D (HEAD -> main, origin/main)
    | *       C (branch2)
    | *       B (branch1)
    |/
    *         A
    """,
    "branches",
    [
      r"                                              ",
      r" Origin - Local  Age <- -> Branch  Base    PR ",
      r" ──────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main               ",
      r"          \w{5}    0  1 2  branch2 branch1    ",
      r"          \w{5}    0  1 1  branch1            ",
      r"                                              ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && \\",
      r"git checkout main",
      r"",
    ],
  )

  print(run_command("git rev-parse branch1").stdout.strip())

  set_mockserver_expectations(
    httpserver,
    [
      ("main", []),
      ("branch2", []),
      (
        "branch1",
        [
          {
            "state": "closed",
            "merged_at": "2026-02-18T16:46:11Z",
            "number": 123,
            "title": "Fix thing",
            "head": {"sha": run_command("git rev-parse branch1").stdout.strip()},
            "html_url": "http://localhost/branches/test_cli_origin/pull/123",
            "user": {"login": "santi-h"},
          }
        ],
      ),
    ],
  )

  run_test(
    r"""
    *         D (HEAD -> main, origin/main)
    | *       C (branch2)
    | *       B (branch1)
    |/
    *         A
    """,
    "branches",
    [
      r"                                                                   ",
      r" Origin - Local  Age <- -> Branch  Base    PR                      ",
      r" ───────────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                                    ",
      r"          \w{5}    0  1 2  branch2 branch1                         ",
      r"          \w{5}    0  1 1  branch1         #123 \(\w{5}\) by santi-h ",
      r"                                                                   ",
      r"git branch -D branch1 && \\",
      r"git checkout branch2 && git rebase main && \\",
      r"git checkout main",
      r"",
    ],
    httpserver=httpserver,
  )

  set_mockserver_expectations(
    httpserver,
    [
      ("main", []),
      ("branch2", []),
      (
        "branch1",
        [
          {
            "state": "closed",
            "merged_at": "2026-02-18T16:46:11Z",
            "number": 123,
            "title": "Fix thing",
            "head": {"sha": run_command("git rev-parse branch1").stdout.strip()},
            "html_url": "http://localhost/branches/test_cli_origin/pull/123",
            "user": {"login": "santi-h"},
          }
        ],
      ),
    ],
  )

  run_prep("git checkout branch2")
  run_test(
    r"""
    *         D (origin/main, main)
    | *       C (HEAD -> branch2)
    | *       B (branch1)
    |/
    *         A
    """,
    "branches",
    [
      r"                                                                   ",
      r" Origin - Local  Age <- -> Branch  Base    PR                      ",
      r" ───────────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                                    ",
      r"          \w{5}    0  1 2  branch2 branch1                         ",
      r"          \w{5}    0  1 1  branch1         #123 \(\w{5}\) by santi-h ",
      r"                                                                   ",
      r"git checkout main && \\",
      r"git branch -D branch1 && \\",
      r"git checkout branch2 && git rebase main",
      r"",
    ],
    httpserver=httpserver,
  )


def test_cli_misc():
  """
  Description:
    Tests a large tree of stacked, empty and duplicated branches, some of them pushed:
      - `branches` and `branches -s` from main, and `-s` from branches in different stacks, which
        only lists the stack of the current branch
      - `branches -s -q`, which suggests no update commands
      - `branches amend` with staged changes from the middle of a stack, from a branch with a
        duplicate, and from a branch with nothing on top of it
      - `branches amend` with no changes, and from main, which both fail
      - `branches -y`, which runs the suggested commands, and running it again with nothing to do
      - local main ahead of origin, behind origin, and deviated from origin
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)
  tformat = "%Y-%m-%dT%H:%M:%S%z"

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    commit("B", now + sec * 2),
    "git checkout -b branch1",
    commit("C", now + sec * 3),
    "git push",
    "git checkout -b branch2",
    commit("D", now + sec * 4),
    commit("E", now + sec * 5),
    "git checkout -b branch3",
    commit("F", now + sec * 6),
    "git push",
    "git checkout -b branch4",
    "git checkout -b branch6",
    commit("G", now + sec * 7),
    "git checkout branch3",
    "git checkout -b branch5",
    commit("H", now + sec * 8),
    commit("I", now + sec * 9),
    "git checkout branch1",
    commit("J", now + sec * 10),
    "git checkout -b branch10",
    "git checkout main",
    commit("K", now + sec * 11),
    commit("L", now + sec * 12),
    commit("M", now + sec * 13),
    "git checkout -b branch7",
    commit("O", now + sec * 14),
    "git checkout -b branch8",
    commit("P", now + sec * 15),
    "git checkout main~2",
    "git checkout -b branch9",
    commit("Q", now + sec * 16),
    "git checkout main",
  )
  run_test(
    r"""
    *         Q (branch9)
    | *       P (branch8)
    | *       O (branch7)
    | *       M (HEAD -> main)
    | *       L
    |/
    *         K
    | *       J (branch10, branch1)
    | | *     I (branch5)
    | | *     H
    | | | *   G (branch6)
    | | |/
    | | *     F (origin/branch3, branch4, branch3)
    | | *     E (branch2)
    | | *     D
    | |/
    | *       C (origin/branch1)
    |/
    *         B
    *         A
    """,
    "branches",
    [
      r"                                                 ",
      r" Origin - Local  Age <- -> Branch   Base      PR ",
      r" ─────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                  ",
      r"          \w{5}    0  2 1  branch9               ",
      r"          \w{5}    0  0 2  branch8  branch7      ",
      r"          \w{5}    0  0 1  branch7               ",
      r"  \w{5} < \w{5}    0  3 2  branch1               ",
      r"          \w{5}    0  3 2  branch10 branch1      ",
      r"          \w{5}    0  3 6  branch5  branch3      ",
      r"          \w{5}    0  3 5  branch6  branch3      ",
      r"  \w{5}   \w{5}    0  3 4  branch3  branch2      ",
      r"          \w{5}    0  3 4  branch4  branch3      ",
      r"          \w{5}    0  3 3  branch2  branch1~1    ",
      r"                                                 ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch10 && git reset --hard branch1 && \\",
      r"git checkout branch2 && git rebase --onto branch1~1 branch2~2 && \\",
      r"git checkout branch3 && git rebase --onto branch2 branch3~1 && git push -f && \\",
      r"git checkout branch4 && git reset --hard branch3 && \\",
      r"git checkout branch6 && git rebase --onto branch3 branch6~1 && \\",
      r"git checkout branch5 && git rebase --onto branch3 branch5~2 && \\",
      r"git checkout branch9 && git rebase main && \\",
      r"git checkout main",
      r"",
    ],
  )

  run_test(
    r"""
    *         Q (branch9)
    | *       P (branch8)
    | *       O (branch7)
    | *       M (HEAD -> main)
    | *       L
    |/
    *         K
    | *       J (branch10, branch1)
    | | *     I (branch5)
    | | *     H
    | | | *   G (branch6)
    | | |/
    | | *     F (origin/branch3, branch4, branch3)
    | | *     E (branch2)
    | | *     D
    | |/
    | *       C (origin/branch1)
    |/
    *         B
    *         A
    """,
    "branches -s",
    [
      r"                                          ",
      r" Origin - Local  Age <- -> Branch Base PR ",
      r" ──────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main           ",
      r"                                          ",
    ],
  )

  run_prep("git checkout branch2")
  run_test(
    r"""
    *         Q (branch9)
    | *       P (branch8)
    | *       O (branch7)
    | *       M (main)
    | *       L
    |/
    *         K
    | *       J (branch10, branch1)
    | | *     I (branch5)
    | | *     H
    | | | *   G (branch6)
    | | |/
    | | *     F (origin/branch3, branch4, branch3)
    | | *     E (HEAD -> branch2)
    | | *     D
    | |/
    | *       C (origin/branch1)
    |/
    *         B
    *         A
    """,
    "branches -s",
    [
      r"                                                 ",
      r" Origin - Local  Age <- -> Branch   Base      PR ",
      r" ─────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                  ",
      r"          \w{5}    0  3 3  branch2  branch1~1    ",
      r"  \w{5} < \w{5}    0  3 2  branch1               ",
      r"  \w{5}   \w{5}    0  3 4  branch3  branch2      ",
      r"          \w{5}    0  3 4  branch4  branch3      ",
      r"          \w{5}    0  3 5  branch6  branch3      ",
      r"          \w{5}    0  3 6  branch5  branch3      ",
      r"          \w{5}    0  3 2  branch10 branch1      ",
      r"                                                 ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch10 && git reset --hard branch1 && \\",
      r"git checkout branch2 && git rebase --onto branch1~1 branch2~2 && \\",
      r"git checkout branch3 && git rebase --onto branch2 branch3~1 && git push -f && \\",
      r"git checkout branch4 && git reset --hard branch3 && \\",
      r"git checkout branch6 && git rebase --onto branch3 branch6~1 && \\",
      r"git checkout branch5 && git rebase --onto branch3 branch5~2 && \\",
      r"git checkout branch2",
      r"",
    ],
  )

  run_prep("git checkout branch2 && echo test >> E.txt && git add E.txt")
  run_test(
    r"""
    *         Q (branch9)
    | *       P (branch8)
    | *       O (branch7)
    | *       M (main)
    | *       L
    |/
    *         K
    | *       J (branch10, branch1)
    | | *     I (branch5)
    | | *     H
    | | | *   G (branch6)
    | | |/
    | | *     F (origin/branch3, branch4, branch3)
    | | *     E (HEAD -> branch2)
    | | *     D
    | |/
    | *       C (origin/branch1)
    |/
    *         B
    *         A
    """,
    "branches amend",
    [
      r"                                                 ",
      r" Origin - Local  Age <- -> Branch   Base      PR ",
      r" ─────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                  ",
      r"          \w{5}    0  3 3  branch2  branch1~1    ",
      r"  \w{5} < \w{5}    0  3 2  branch1               ",
      r"  \w{5}   \w{5}    0  3 4  branch3  branch2      ",
      r"          \w{5}    0  3 4  branch4  branch3      ",
      r"          \w{5}    0  3 5  branch6  branch3      ",
      r"          \w{5}    0  3 6  branch5  branch3      ",
      r"          \w{5}    0  3 2  branch10 branch1      ",
      r"                                                 ",
      r"git add -A && git commit --amend --no-edit && \\",
      r"git checkout branch3 && git rebase --onto branch2 branch3~1 && git push -f && \\",
      r"git checkout branch4 && git reset --hard branch3 && \\",
      r"git checkout branch6 && git rebase --onto branch3 branch6~1 && \\",
      r"git checkout branch5 && git rebase --onto branch3 branch5~2 && \\",
      r"git checkout branch2",
      r"",
    ],
    cleanup_command="git reset HEAD && git checkout .",
  )

  run_prep("git checkout branch1")
  run_test(
    r"""
    *         Q (branch9)
    | *       P (branch8)
    | *       O (branch7)
    | *       M (main)
    | *       L
    |/
    *         K
    | *       J (HEAD -> branch1, branch10)
    | | *     I (branch5)
    | | *     H
    | | | *   G (branch6)
    | | |/
    | | *     F (origin/branch3, branch4, branch3)
    | | *     E (branch2)
    | | *     D
    | |/
    | *       C (origin/branch1)
    |/
    *         B
    *         A
    """,
    "branches -s",
    [
      r"                                                 ",
      r" Origin - Local  Age <- -> Branch   Base      PR ",
      r" ─────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                  ",
      r"  \w{5} < \w{5}    0  3 2  branch1               ",
      r"          \w{5}    0  3 2  branch10 branch1      ",
      r"          \w{5}    0  3 3  branch2  branch1~1    ",
      r"  \w{5}   \w{5}    0  3 4  branch3  branch2      ",
      r"          \w{5}    0  3 4  branch4  branch3      ",
      r"          \w{5}    0  3 5  branch6  branch3      ",
      r"          \w{5}    0  3 6  branch5  branch3      ",
      r"                                                 ",
      r"git rebase main && \\",
      r"git checkout branch10 && git reset --hard branch1 && \\",
      r"git checkout branch2 && git rebase --onto branch1~1 branch2~2 && \\",
      r"git checkout branch3 && git rebase --onto branch2 branch3~1 && git push -f && \\",
      r"git checkout branch4 && git reset --hard branch3 && \\",
      r"git checkout branch6 && git rebase --onto branch3 branch6~1 && \\",
      r"git checkout branch5 && git rebase --onto branch3 branch5~2 && \\",
      r"git checkout branch1",
      r"",
    ],
  )

  run_prep("git checkout branch1 && echo test >> J.txt && git add J.txt")
  run_test(
    r"""
    *         Q (branch9)
    | *       P (branch8)
    | *       O (branch7)
    | *       M (main)
    | *       L
    |/
    *         K
    | *       J (HEAD -> branch1, branch10)
    | | *     I (branch5)
    | | *     H
    | | | *   G (branch6)
    | | |/
    | | *     F (origin/branch3, branch4, branch3)
    | | *     E (branch2)
    | | *     D
    | |/
    | *       C (origin/branch1)
    |/
    *         B
    *         A
    """,
    "branches amend",
    [
      r"                                                 ",
      r" Origin - Local  Age <- -> Branch   Base      PR ",
      r" ─────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                  ",
      r"  \w{5} < \w{5}    0  3 2  branch1               ",
      r"          \w{5}    0  3 2  branch10 branch1      ",
      r"          \w{5}    0  3 3  branch2  branch1~1    ",
      r"  \w{5}   \w{5}    0  3 4  branch3  branch2      ",
      r"          \w{5}    0  3 4  branch4  branch3      ",
      r"          \w{5}    0  3 5  branch6  branch3      ",
      r"          \w{5}    0  3 6  branch5  branch3      ",
      r"                                                 ",
      r"git add -A && git commit --amend --no-edit && \\",
      r"git checkout branch10 && git reset --hard branch1 && \\",
      r"git checkout branch1",
      r"",
    ],
    cleanup_command="git reset HEAD && git checkout .",
  )

  run_prep("git checkout branch10")
  run_test(
    r"""
    *         Q (branch9)
    | *       P (branch8)
    | *       O (branch7)
    | *       M (main)
    | *       L
    |/
    *         K
    | *       J (HEAD -> branch10, branch1)
    | | *     I (branch5)
    | | *     H
    | | | *   G (branch6)
    | | |/
    | | *     F (origin/branch3, branch4, branch3)
    | | *     E (branch2)
    | | *     D
    | |/
    | *       C (origin/branch1)
    |/
    *         B
    *         A
    """,
    "branches -s",
    [
      r"                                                 ",
      r" Origin - Local  Age <- -> Branch   Base      PR ",
      r" ─────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                  ",
      r"          \w{5}    0  3 2  branch10 branch1      ",
      r"  \w{5} < \w{5}    0  3 2  branch1               ",
      r"          \w{5}    0  3 3  branch2  branch1~1    ",
      r"  \w{5}   \w{5}    0  3 4  branch3  branch2      ",
      r"          \w{5}    0  3 4  branch4  branch3      ",
      r"          \w{5}    0  3 5  branch6  branch3      ",
      r"          \w{5}    0  3 6  branch5  branch3      ",
      r"                                                 ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch10 && git reset --hard branch1 && \\",
      r"git checkout branch2 && git rebase --onto branch1~1 branch2~2 && \\",
      r"git checkout branch3 && git rebase --onto branch2 branch3~1 && git push -f && \\",
      r"git checkout branch4 && git reset --hard branch3 && \\",
      r"git checkout branch6 && git rebase --onto branch3 branch6~1 && \\",
      r"git checkout branch5 && git rebase --onto branch3 branch5~2 && \\",
      r"git checkout branch10",
      r"",
    ],
  )

  run_prep("git checkout branch9")
  run_test(
    r"""
    *         Q (HEAD -> branch9)
    | *       P (branch8)
    | *       O (branch7)
    | *       M (main)
    | *       L
    |/
    *         K
    | *       J (branch10, branch1)
    | | *     I (branch5)
    | | *     H
    | | | *   G (branch6)
    | | |/
    | | *     F (origin/branch3, branch4, branch3)
    | | *     E (branch2)
    | | *     D
    | |/
    | *       C (origin/branch1)
    |/
    *         B
    *         A
    """,
    "branches -s",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main            ",
      r"          \w{5}    0  2 1  branch9         ",
      r"                                           ",
      r"git rebase main",
      r"",
    ],
  )

  run_prep("git checkout branch9")
  run_test(
    r"""
    *         Q (HEAD -> branch9)
    | *       P (branch8)
    | *       O (branch7)
    | *       M (main)
    | *       L
    |/
    *         K
    | *       J (branch10, branch1)
    | | *     I (branch5)
    | | *     H
    | | | *   G (branch6)
    | | |/
    | | *     F (origin/branch3, branch4, branch3)
    | | *     E (branch2)
    | | *     D
    | |/
    | *       C (origin/branch1)
    |/
    *         B
    *         A
    """,
    "branches -s -q",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main            ",
      r"          \w{5}    0  2 1  branch9         ",
      r"                                           ",
    ],
  )

  run_prep("git checkout branch9 && echo test >> Q.txt && git add Q.txt")
  run_test(
    r"""
    *         Q (HEAD -> branch9)
    | *       P (branch8)
    | *       O (branch7)
    | *       M (main)
    | *       L
    |/
    *         K
    | *       J (branch10, branch1)
    | | *     I (branch5)
    | | *     H
    | | | *   G (branch6)
    | | |/
    | | *     F (origin/branch3, branch4, branch3)
    | | *     E (branch2)
    | | *     D
    | |/
    | *       C (origin/branch1)
    |/
    *         B
    *         A
    """,
    "branches amend",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main            ",
      r"          \w{5}    0  2 1  branch9         ",
      r"                                           ",
      r"git add -A && git commit --amend --no-edit",
      r"",
    ],
    cleanup_command="git reset HEAD && git checkout .",
  )

  run_prep("git checkout branch9")
  run_test(
    r"""
    *         Q (HEAD -> branch9)
    | *       P (branch8)
    | *       O (branch7)
    | *       M (main)
    | *       L
    |/
    *         K
    | *       J (branch10, branch1)
    | | *     I (branch5)
    | | *     H
    | | | *   G (branch6)
    | | |/
    | | *     F (origin/branch3, branch4, branch3)
    | | *     E (branch2)
    | | *     D
    | |/
    | *       C (origin/branch1)
    |/
    *         B
    *         A
    """,
    "branches amend",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main            ",
      r"          \w{5}    0  2 1  branch9         ",
      r"                                           ",
      r"No changes to amend with.",
      r"",
    ],
    expected_returncode=1,
  )

  run_prep("git checkout main && echo test >> A.txt && git add A.txt")
  run_test(
    r"""
    *         Q (branch9)
    | *       P (branch8)
    | *       O (branch7)
    | *       M (HEAD -> main)
    | *       L
    |/
    *         K
    | *       J (branch10, branch1)
    | | *     I (branch5)
    | | *     H
    | | | *   G (branch6)
    | | |/
    | | *     F (origin/branch3, branch4, branch3)
    | | *     E (branch2)
    | | *     D
    | |/
    | *       C (origin/branch1)
    |/
    *         B
    *         A
    """,
    "branches amend",
    [
      r"                                          ",
      r" Origin - Local  Age <- -> Branch Base PR ",
      r" ──────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main           ",
      r"                                          ",
      r"Cannot run amend on the main branch. Checkout a different branch.",
      r"",
    ],
    expected_returncode=1,
    cleanup_command="git reset HEAD && git checkout .",
  )

  run_prep("git reset HEAD && git checkout . && git checkout main")
  run_test(
    r"""
    *         Q (branch9)
    | *       P (branch8)
    | *       O (branch7)
    | *       M (HEAD -> main)
    | *       L
    |/
    *         K
    | *       J (branch10, branch1)
    | | *     I (branch5)
    | | *     H
    | | | *   G (branch6)
    | | |/
    | | *     F (origin/branch3, branch4, branch3)
    | | *     E (branch2)
    | | *     D
    | |/
    | *       C (origin/branch1)
    |/
    *         B
    *         A
    """,
    "branches -y",
    [
      r"                                                 ",
      r" Origin - Local  Age <- -> Branch   Base      PR ",
      r" ─────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                  ",
      r"          \w{5}    0  2 1  branch9               ",
      r"          \w{5}    0  0 2  branch8  branch7      ",
      r"          \w{5}    0  0 1  branch7               ",
      r"  \w{5} < \w{5}    0  3 2  branch1               ",
      r"          \w{5}    0  3 2  branch10 branch1      ",
      r"          \w{5}    0  3 6  branch5  branch3      ",
      r"          \w{5}    0  3 5  branch6  branch3      ",
      r"  \w{5}   \w{5}    0  3 4  branch3  branch2      ",
      r"          \w{5}    0  3 4  branch4  branch3      ",
      r"          \w{5}    0  3 3  branch2  branch1~1    ",
      r"                                                 ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch10 && git reset --hard branch1 && \\",
      r"git checkout branch2 && git rebase --onto branch1~1 branch2~2 && \\",
      r"git checkout branch3 && git rebase --onto branch2 branch3~1 && git push -f && \\",
      r"git checkout branch4 && git reset --hard branch3 && \\",
      r"git checkout branch6 && git rebase --onto branch3 branch6~1 && \\",
      r"git checkout branch5 && git rebase --onto branch3 branch5~2 && \\",
      r"git checkout branch9 && git rebase main && \\",
      r"git checkout main",
      r"",
      r"Switched to branch 'branch1'",
      r"Your branch is ahead of 'origin/branch1' by 1 commit.",
      r"  \(use \"git push\" to publish your local commits\)",
      r"Rebasing \(1/2\)",
      r"Rebasing \(2/2\)",
      r"Successfully rebased and updated refs/heads/branch1.",
      r"Switched to branch 'branch10'",
      r"HEAD is now at \w{7} J",
      r"Switched to branch 'branch2'",
      r"Rebasing \(1/2\)",
      r"Rebasing \(2/2\)",
      r"Successfully rebased and updated refs/heads/branch2.",
      r"Switched to branch 'branch3'",
      r"Your branch is up to date with 'origin/branch3'.",
      r"Rebasing \(1/1\)",
      r"Successfully rebased and updated refs/heads/branch3.",
      f"To {GIT_TMP_DIRPATH_ORIGIN}",
      r" \+ \w{7}...\w{7} branch3 -> branch3 \(forced update\)",
      r"Switched to branch 'branch4'",
      r"HEAD is now at \w{7} F",
      r"Switched to branch 'branch6'",
      r"Rebasing \(1/1\)",
      r"Successfully rebased and updated refs/heads/branch6.",
      r"Switched to branch 'branch5'",
      r"Rebasing \(1/2\)",
      r"Rebasing \(2/2\)",
      r"Successfully rebased and updated refs/heads/branch5.",
      r"Switched to branch 'branch9'",
      r"Rebasing \(1/1\)",
      r"Successfully rebased and updated refs/heads/branch9.",
      r"Switched to branch 'main'",
    ],
  )

  run_prep("git checkout main")
  run_test(
    r"""
    *         Q (branch9)
    | *       P (branch8)
    | *       O (branch7)
    |/
    | *       J (branch10, branch1)
    | | *     I (branch5)
    | | *     H
    | | | *   G (branch6)
    | | |/
    | | *     F (origin/branch3, branch4, branch3)
    | | *     E (branch2)
    | | *     D
    | |/
    | | *     C (origin/branch1)
    | * |     C
    |/ /
    * |       M (HEAD -> main)
    * |       L
    * |       K
    |/
    *         B
    *         A
    """,
    "branches -y",
    [
      r"                                                 ",
      r" Origin - Local  Age <- -> Branch   Base      PR ",
      r" ─────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                  ",
      r"          \w{5}    0  0 1  branch9               ",
      r"          \w{5}    0  0 2  branch8  branch7      ",
      r"          \w{5}    0  0 1  branch7               ",
      r"  \w{5} Y \w{5}    0  0 2  branch1               ",
      r"          \w{5}    0  0 2  branch10 branch1      ",
      r"          \w{5}    0  0 6  branch5  branch3      ",
      r"          \w{5}    0  0 5  branch6  branch3      ",
      r"  \w{5}   \w{5}    0  0 4  branch3  branch2      ",
      r"          \w{5}    0  0 4  branch4  branch3      ",
      r"          \w{5}    0  0 3  branch2  branch1~1    ",
      r"                                                 ",
    ],
  )

  # When the local `main` is ahead and the remote sha is an ancestor
  run_prep(
    "git push",
    "echo test >> Q.txt && git add Q.txt",
    f"git commit -m 'Q' --date='{(now + sec * 17).strftime(tformat)}' --author='Name <me@git.com>'",
  )
  run_test(
    r"""
    *         Q (HEAD -> main)
    | *       Q (branch9)
    |/
    | *       P (branch8)
    | *       O (branch7)
    |/
    | *       J (branch10, branch1)
    | | *     I (branch5)
    | | *     H
    | | | *   G (branch6)
    | | |/
    | | *     F (origin/branch3, branch4, branch3)
    | | *     E (branch2)
    | | *     D
    | |/
    | | *     C (origin/branch1)
    | * |     C
    |/ /
    * |       M (origin/main)
    * |       L
    * |       K
    |/
    *         B
    *         A
    """,
    "branches -s",
    [
      r"                                          ",
      r" Origin - Local  Age <- -> Branch Base PR ",
      r" ──────────────────────────────────────── ",
      r"  \w{5} < \w{5}    0  0 0  main           ",
      r"                                          ",
    ],
  )

  # When the remote `main` is ahead and the local sha is an ancestor
  run_prep("git push && git reset --hard HEAD~1")
  run_test(
    r"""
    *         Q (origin/main)
    | *       Q (branch9)
    |/
    | *       P (branch8)
    | *       O (branch7)
    |/
    | *       J (branch10, branch1)
    | | *     I (branch5)
    | | *     H
    | | | *   G (branch6)
    | | |/
    | | *     F (origin/branch3, branch4, branch3)
    | | *     E (branch2)
    | | *     D
    | |/
    | | *     C (origin/branch1)
    | * |     C
    |/ /
    * |       M (HEAD -> main)
    * |       L
    * |       K
    |/
    *         B
    *         A
    """,
    "branches -s",
    [
      r"                                          ",
      r" Origin - Local  Age <- -> Branch Base PR ",
      r" ──────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main           ",
      r"                                          ",
      r"git pull",
      r"",
    ],
  )

  # When the remote `main` and local `main` deviated
  run_prep(
    "echo test >> Q.txt && git add Q.txt",
    f"git commit -m 'Q' --date='{(now + sec * 19).strftime(tformat)}'",
  )
  run_test(
    r"""
    *         Q (HEAD -> main)
    | *       Q (origin/main)
    |/
    | *       Q (branch9)
    |/
    | *       P (branch8)
    | *       O (branch7)
    |/
    | *       J (branch10, branch1)
    | | *     I (branch5)
    | | *     H
    | | | *   G (branch6)
    | | |/
    | | *     F (origin/branch3, branch4, branch3)
    | | *     E (branch2)
    | | *     D
    | |/
    | | *     C (origin/branch1)
    | * |     C
    |/ /
    * |       M
    * |       L
    * |       K
    |/
    *         B
    *         A
    """,
    "branches -s",
    [
      r"                                          ",
      r" Origin - Local  Age <- -> Branch Base PR ",
      r" ──────────────────────────────────────── ",
      r"  \w{5} Y \w{5}    0  0 0  main           ",
      r"                                          ",
    ],
  )


def test_misc1():
  """
  Description:
    Tests what happens when the branch origin diverted, and local is behind.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch1 HEAD~1",
    commit("C", now + sec * 3),
    "git push",
    "git reset --hard HEAD~1",
    commit("D", now + sec * 4),
  )
  run_test(
    r"""
    *         D (HEAD -> branch1)
    | *       C (origin/branch1)
    |/
    | *       B (origin/main, main)
    |/
    *         A
    """,
    "branches",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main            ",
      r"  \w{5} Y \w{5}    0  1 1  branch1         ",
      r"                                           ",
      r"git rebase main",
      r"",
    ],
  )


def test_misc2():
  """
  Description:
    Tests what happens when the branch origin diverted, and local is caught up and ahead.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch1 HEAD~1",
    commit("C", now + sec * 3),
    "git push",
    "git reset --hard main",
    commit("D", now + sec * 4),
  )
  run_test(
    r"""
    *         D (HEAD -> branch1)
    | *       C (origin/branch1)
    * |       B (origin/main, main)
    |/
    *         A
    """,
    "branches",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main            ",
      r"  \w{5} Y \w{5}    0  0 1  branch1         ",
      r"                                           ",
    ],
  )


def test_cli_amend():
  """
  Description:
    Tests `branches amend` when there is nothing to amend, when changes are amended into a branch
    with branches stacked on top, and when those stacked branches are pushed or contain merges.
  """
  file_content_a = "\\n".join(
    [
      "line1",
      "",
      "",
      "line4",
      "",
      "line3 - original from main",
      "",
      "line7",
      "",
      "",
      "",
      "line8 last one",
    ]
  )

  file_content_b = "\\n".join(
    [
      "line1",
      "",
      "",
      "line4 - changed by branch1",
      "",
      "line3 - original from main",
      "",
      "line7",
      "",
      "",
      "",
      "line8 last one",
    ]
  )

  file_content_c = "\\n".join(
    [
      "line1 - changed by branch2",
      "",
      "",
      "line4 - changed by branch1",
      "",
      "line3 - original from main",
      "",
      "line7",
      "",
      "",
      "",
      "line8 last one",
    ]
  )

  file_content_d = "\\n".join(
    [
      "line1 - changed by branch2 - changed again at D",
      "changed at commit D",
      "",
      "line4 - changed by branch1",
      "",
      "line3 - original from main",
      "",
      "line7",
      "",
      "",
      "",
      "line8 last one",
    ]
  )

  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)
  tformat = "%Y-%m-%dT%H:%M:%S%z"

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    f'echo "{file_content_a}" > testfile.txt && git add .',
    f"git commit -m 'A' --date='{(now + sec * 1).strftime(tformat)}'",
    "git checkout -b branch1",
    f'echo "{file_content_b}" > testfile.txt && git add .',
    f"git commit -m 'B' --date='{(now + sec * 2).strftime(tformat)}'",
    "git checkout -b branch2",
    f'echo "{file_content_c}" > testfile.txt && git add .',
    f"git commit -m 'C' --date='{(now + sec * 3).strftime(tformat)}'",
    f'echo "{file_content_d}" > testfile.txt && git add .',
    f"git commit -m 'D' --date='{(now + sec * 3).strftime(tformat)}'",
    "git checkout branch1",
  )
  run_test(
    r"""
    *         D (branch2)
    *         C
    *         B (HEAD -> branch1)
    *         A (main)
    """,
    "branches amend",
    [
      r"                                              ",
      r" Origin - Local  Age <- -> Branch  Base    PR ",
      r" ──────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main               ",
      r"          \w{5}    0  0 1  branch1            ",
      r"          \w{5}    0  0 3  branch2 branch1    ",
      r"                                              ",
      r"No changes to amend with.",
      r"",
    ],
    expected_returncode=1,
  )

  file_content_b_new = "\\n".join(
    [
      "line1",
      "",
      "",
      "line4",
      "",
      "line3 - original from main",
      "",
      "line7",
      "",
      "",
      "changed by branch1",
      "line8 last one",
    ]
  )

  run_prep(f'echo "{file_content_b_new}" > testfile.txt')
  run_test(
    r"""
    *         D (branch2)
    *         C
    *         B (HEAD -> branch1)
    *         A (main)
    """,
    "branches amend -y",
    [
      r"                                              ",
      r" Origin - Local  Age <- -> Branch  Base    PR ",
      r" ──────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main               ",
      r"          \w{5}    0  0 1  branch1            ",
      r"          \w{5}    0  0 3  branch2 branch1    ",
      r"                                              ",
      r"git add -A && git commit --amend --no-edit && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~2 && \\",
      r"git checkout branch1",
      r"",
      r"\[branch1 \w{7}\] B",
      r" Date: .*",
      r" 1 file changed, 1 insertion\(\+\), 1 deletion\(-\)",
      r"Switched to branch 'branch2'",
      r"Rebasing \(1/2\)",
      r"Rebasing \(2/2\)",
      r"Successfully rebased and updated refs/heads/branch2.",
      r"Switched to branch 'branch1'",
    ],
  )

  run_test(
    r"""
    *         D (branch2)
    *         C
    *         B (HEAD -> branch1)
    *         A (main)
    """,
    "branches",
    [
      r"                                              ",
      r" Origin - Local  Age <- -> Branch  Base    PR ",
      r" ──────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main               ",
      r"          \w{5}    0  0 1  branch1            ",
      r"          \w{5}    0  0 3  branch2 branch1    ",
      r"                                              ",
    ],
  )

  assert run_command("cat testfile.txt").stdout == "\n".join(
    [
      "line1",
      "",
      "",
      "line4",
      "",
      "line3 - original from main",
      "",
      "line7",
      "",
      "",
      "changed by branch1",
      "line8 last one",
      "",
    ]
  )

  assert run_command("git checkout branch2 && cat testfile.txt").stdout == "\n".join(
    [
      "line1 - changed by branch2 - changed again at D",
      "changed at commit D",
      "",
      "line4",
      "",
      "line3 - original from main",
      "",
      "line7",
      "",
      "",
      "changed by branch1",
      "line8 last one",
      "",
    ]
  )

  run_prep("git checkout branch1 && git push && echo 'new file' > testnewfile.txt")
  run_test(
    r"""
    *         D (branch2)
    *         C
    *         B (HEAD -> branch1, origin/branch1)
    *         A (main)
    """,
    "branches amend -y",
    [
      r"                                              ",
      r" Origin - Local  Age <- -> Branch  Base    PR ",
      r" ──────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main               ",
      r"  \w{5}   \w{5}    0  0 1  branch1            ",
      r"          \w{5}    0  0 3  branch2 branch1    ",
      r"                                              ",
      r"git add -A && git commit --amend --no-edit && git push -f && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~2 && \\",
      r"git checkout branch1",
      r"",
      r"\[branch1 \w{7}\] B",
      r" Date: .*",
      r" 2 files changed, 2 insertions\(\+\), 1 deletion\(\-\)",
      r" create mode 100644 testnewfile.txt",
      f"To {GIT_TMP_DIRPATH_ORIGIN}",
      r" \+ \w{7}...\w{7} branch1 -> branch1 \(forced update\)",
      r"Switched to branch 'branch2'",
      r"Rebasing \(1/2\)",
      r"Rebasing \(2/2\)",
      r"Successfully rebased and updated refs/heads/branch2.",
      r"Switched to branch 'branch1'",
      r"Your branch is up to date with 'origin/branch1'.",
    ],
  )

  run_command(
    "git checkout main && "
    "git checkout -b branch3 && "
    "echo 'yet another file' > yetanotherfile.txt && "
    "git add . && git commit -m 'yet another file' && "
    "git checkout branch2 && git merge branch3"
  )

  run_prep("git checkout branch2 && git push && echo 'file5' > file5.txt")
  run_test(
    r"""
    *         Merge branch 'branch3' into branch2 (HEAD -> branch2, origin/branch2)
    |\
    | *       yet another file (branch3)
    * |       D
    * |       C
    * |       B (origin/branch1, branch1)
    |/
    *         A (main)
    """,
    "branches amend",
    [
      r"                                            ",
      r" Origin - Local  Age <- ->  Branch  Base PR ",
      r" ────────────────────────────────────────── ",
      r"          \w{5}    0  0 0   main            ",
      r"  \w{5}   \w{5}    0  0 5 M branch2         ",
      r"                                            ",
      r"Tool limitation: cannot amend or update branches with merge commits.",
    ],
    expected_returncode=1,
  )

  run_test(
    r"""
    *         Merge branch 'branch3' into branch2 (HEAD -> branch2, origin/branch2)
    |\
    | *       yet another file (branch3)
    * |       D
    * |       C
    * |       B (origin/branch1, branch1)
    |/
    *         A (main)
    """,
    "branches amend -y",
    [
      r"                                            ",
      r" Origin - Local  Age <- ->  Branch  Base PR ",
      r" ────────────────────────────────────────── ",
      r"          \w{5}    0  0 0   main            ",
      r"  \w{5}   \w{5}    0  0 5 M branch2         ",
      r"                                            ",
      r"Tool limitation: cannot amend or update branches with merge commits.",
    ],
    expected_returncode=1,
    cleanup_command="git clean -fd",
  )

  run_prep("git checkout branch1 && git push && echo 'file5' > file5.txt")
  run_test(
    r"""
    *         Merge branch 'branch3' into branch2 (origin/branch2, branch2)
    |\
    | *       yet another file (branch3)
    * |       D
    * |       C
    * |       B (HEAD -> branch1, origin/branch1)
    |/
    *         A (main)
    """,
    "branches amend",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main            ",
      r"  \w{5}   \w{5}    0  0 1  branch1         ",
      r"                                           ",
      r"git add -A && git commit --amend --no-edit && git push -f",
      r"",
    ],
  )


def test_subdir():
  """
  Description:
    Tests running `branches amend` from a subdirectory of the repo.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)
  tformat = "%Y-%m-%dT%H:%M:%S%z"

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    "echo 'A.txt' > A.txt && git add .",
    f"git commit -m 'A.txt' --date='{(now + sec * 1).strftime(tformat)}'",
    "echo 'B.txt' > B.txt && git add .",
    f"git commit -m 'B.txt' --date='{(now + sec * 2).strftime(tformat)}'",
    "git checkout -b branch1",
    "mkdir ./subdir",
    "echo 'subdir/C.txt' > subdir/C.txt && git add .",
    f"git commit -m 'subdir/C.txt' --date='{(now + sec * 3).strftime(tformat)}'",
    "git checkout -b branch2",
    "echo 'D.txt' > D.txt && git add .",
    f"git commit -m 'D.txt' --date='{(now + sec * 4).strftime(tformat)}'",
    "git checkout branch1",
  )
  run_test(
    r"""
    *         D.txt (branch2)
    *         subdir/C.txt (HEAD -> branch1)
    *         B.txt (main)
    *         A.txt
    """,
    "branches",
    [
      r"                                              ",
      r" Origin - Local  Age <- -> Branch  Base    PR ",
      r" ──────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main               ",
      r"          \w{5}    0  0 1  branch1            ",
      r"          \w{5}    0  0 2  branch2 branch1    ",
      r"                                              ",
    ],
    expected_returncode=0,
  )

  run_prep("echo 'newline' >> A.txt")
  run_test(
    r"""
    *         D.txt (branch2)
    *         subdir/C.txt (HEAD -> branch1)
    *         B.txt (main)
    *         A.txt
    """,
    "branches amend",
    [
      r"                                              ",
      r" Origin - Local  Age <- -> Branch  Base    PR ",
      r" ──────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main               ",
      r"          \w{5}    0  0 1  branch1            ",
      r"          \w{5}    0  0 2  branch2 branch1    ",
      r"                                              ",
      r"git add -A && git commit --amend --no-edit && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && \\",
      r"git checkout branch1",
      r"",
    ],
    expected_returncode=0,
    trigger_command_dir="subdir",
  )

  run_prep("echo 'newline' >> A.txt")
  run_test(
    r"""
    *         D.txt (branch2)
    *         subdir/C.txt (HEAD -> branch1)
    *         B.txt (main)
    *         A.txt
    """,
    "branches amend -y",
    [
      r"                                              ",
      r" Origin - Local  Age <- -> Branch  Base    PR ",
      r" ──────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main               ",
      r"          \w{5}    0  0 1  branch1            ",
      r"          \w{5}    0  0 2  branch2 branch1    ",
      r"                                              ",
      r"git add -A && git commit --amend --no-edit && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && \\",
      r"git checkout branch1",
      r"",
      r"\[branch1 \w{7}\] subdir/C.txt",
      r" Date: .*",
      r" 2 files changed, 3 insertions\(\+\)",
      r" create mode 100644 subdir/C.txt",
      r"Switched to branch 'branch2'",
      r"Rebasing \(1/1\)",
      r"Successfully rebased and updated refs/heads/branch2.",
      r"Switched to branch 'branch1'",
    ],
    expected_returncode=0,
    trigger_command_dir="subdir",
  )


def test_authors1():
  """
  Description:
    Tests different "other authors" scenarios
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  # Local branch has commits by a different author
  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    commit("B", now + sec * 2),
    "git checkout -b branch1",
    commit("C", now + sec * 3, "Name <me@git.com>"),
  )
  run_test(
    r"""
    *         C (HEAD -> branch1)
    *         B (main)
    *         A
    """,
    "branches",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main            ",
      r"          \w{5}!   0  0 1  branch1         ",
      r"                                           ",
    ],
    expected_returncode=0,
  )

  # Remote and local branch have commits by a different author, but main is not in origin
  run_prep("git push")
  run_test(
    r"""
    *         C (HEAD -> branch1, origin/branch1)
    *         B (main)
    *         A
    """,
    "branches",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main            ",
      r"  \w{5}   \w{5}!   0  0 1  branch1         ",
      r"                                           ",
    ],
    expected_returncode=0,
  )

  # Remote and local branch have commits by a different author, and main is in origin
  run_prep("git checkout main && git push && git checkout branch1")
  run_test(
    r"""
    *         C (HEAD -> branch1, origin/branch1)
    *         B (origin/main, main)
    *         A
    """,
    "branches",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main            ",
      r" !\w{5}   \w{5}!   0  0 1  branch1         ",
      r"                                           ",
    ],
    expected_returncode=0,
  )

  # Remote branch only has commits by a different author
  git_name = run_command("git config --get user.name").stdout.strip()
  git_email = run_command("git config --get user.email").stdout.strip()
  run_prep(f"git commit --amend --author='{git_name} <{git_email}>' --no-edit")
  run_test(
    r"""
    *         C (HEAD -> branch1)
    | *       C (origin/branch1)
    |/
    *         B (origin/main, main)
    *         A
    """,
    "branches",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main            ",
      r" !\w{5} Y \w{5}    0  0 1  branch1         ",
      r"                                           ",
    ],
    expected_returncode=0,
  )


def test_authors2():
  """
  Description:
    Tests what happens when:
      - main origin is ahead
      - the local branch is behind but got caught up via a merge commit
      - the origin branch deviated and was also caught up via a merge commit
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1, "Name <me@git.com>"),
    commit("B", now + sec * 2, "Name <me@git.com>"),
    commit("C", now + sec * 3, "Name <me@git.com>"),
    commit("D", now + sec * 4, "Name <me@git.com>"),
    "git push",
    "git checkout -b branch1 HEAD~2",
    commit("E", now + sec * 5),
    "git checkout -b tmp && git checkout branch1",
    commit("F", now + sec * 6),
    f"GIT_AUTHOR_DATE='{(now + sec * 8).isoformat()}' git merge main",
    "git push",
    "git reset --hard tmp && git branch -D tmp",
    commit("G", now + sec * 7),
    "git checkout main && git reset --hard HEAD~1",
    "git checkout branch1",
    f"GIT_AUTHOR_DATE='{(now + sec * 9).isoformat()}' git merge main",
  )
  run_test(
    r"""
    *         Merge branch 'main' into branch1 (HEAD -> branch1)
    |\
    | | *     Merge branch 'main' into branch1 (origin/branch1)
    | | |\
    * | | |   G
    | | * |   F
    | |/ /
    |/| |
    * | |     E
    | | *     D (origin/main)
    | |/
    | *       C (main)
    |/
    *         B
    *         A
    """,
    "branches",
    [
      r"                                            ",
      r" Origin - Local  Age <- ->  Branch  Base PR ",
      r" ────────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0   main            ",
      r"  \w{5} Y \w{5}    0  0 3 M branch1         ",
      r"                                            ",
      r"git checkout main && git pull && \\",
      r"git checkout branch1",
      r"",
    ],
  )


def test_pulls1():
  """
  Description:
    Tests what happens when a stack of local branches is behind their origins and main is ahead:
    pull each branch, then rebase the stack onto main.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch1 HEAD~1",
    commit("C", now + sec * 3),
    commit("D", now + sec * 4),
    "git push",
    "git checkout -b branch2",
    commit("E", now + sec * 5),
    "git checkout -b branch3 && git push",
    "git checkout branch2 && git push && git reset --hard HEAD~1",
    "git checkout branch1 && git reset --hard HEAD~1",
  )
  run_test(
    r"""
    *         E (origin/branch3, origin/branch2, branch3)
    *         D (origin/branch1, branch2)
    *         C (HEAD -> branch1)
    | *       B (origin/main, main)
    |/
    *         A
    """,
    "branches",
    [
      r"                                              ",
      r" Origin - Local  Age <- -> Branch  Base    PR ",
      r" ──────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main               ",
      r"  \w{5} > \w{5}    0  1 1  branch1            ",
      r"  \w{5}   \w{5}    0  1 3  branch3 branch2    ",
      r"  \w{5} > \w{5}    0  1 2  branch2 branch1    ",
      r"                                              ",
      r"git checkout branch1 && git pull && \\",
      r"git checkout branch2 && git pull && \\",
      r"git checkout branch1 && git rebase main && git push -f && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && git push -f && \\",
      r"git checkout branch3 && git reset --hard branch2 && git push -f && \\",
      r"git checkout branch1",
      r"",
    ],
  )


def test_pulls2():
  """
  Description:
    Tests what happens when a branch is behind its origin and a branch stacked on top points at the
    same commit as it.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch1 HEAD~1",
    commit("C", now + sec * 3),
    commit("D", now + sec * 4),
    "git push",
    "git checkout -b branch2 && git push",
    "git checkout -b branch3",
    commit("E", now + sec * 5),
    "git push",
    "git checkout branch1 && git reset --hard HEAD~1",
  )
  run_test(
    r"""
    *         E (origin/branch3, branch3)
    *         D (origin/branch2, origin/branch1, branch2)
    *         C (HEAD -> branch1)
    | *       B (origin/main, main)
    |/
    *         A
    """,
    "branches",
    [
      r"                                              ",
      r" Origin - Local  Age <- -> Branch  Base    PR ",
      r" ──────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main               ",
      r"  \w{5} > \w{5}    0  1 1  branch1            ",
      r"  \w{5}   \w{5}    0  1 3  branch3 branch2    ",
      r"  \w{5}   \w{5}    0  1 2  branch2 branch1    ",
      r"                                              ",
      r"git checkout branch1 && git pull && \\",
      r"git rebase main && git push -f && \\",
      r"git checkout branch2 && git reset --hard branch1 && git push -f && \\",
      r"git checkout branch3 && git rebase --onto branch1 branch3~1 && git push -f && \\",
      r"git checkout branch1",
      r"",
    ],
  )


def test_pulls3():
  """
  Description:
    Tests what happens when a branch is behind its origin by more than one commit and another branch
    sits in the middle of it.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch1 HEAD~1",
    commit("C", now + sec * 3),
    commit("D", now + sec * 4),
    commit("E", now + sec * 5),
    "git push",
    "git checkout -b branch3 && git push",
    "git checkout -b branch2 HEAD~1 && git push",
    "git checkout branch1 && git reset --hard HEAD~2",
  )
  run_test(
    r"""
    *         E (origin/branch3, origin/branch1, branch3)
    *         D (origin/branch2, branch2)
    *         C (HEAD -> branch1)
    | *       B (origin/main, main)
    |/
    *         A
    """,
    "branches",
    [
      r"                                              ",
      r" Origin - Local  Age <- -> Branch  Base    PR ",
      r" ──────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main               ",
      r"  \w{5} > \w{5}    0  1 1  branch1            ",
      r"  \w{5}   \w{5}    0  1 3  branch3 branch2    ",
      r"  \w{5}   \w{5}    0  1 2  branch2 branch1    ",
      r"                                              ",
      r"git checkout branch1 && git pull && \\",
      r"git checkout branch2 && git rebase main && git push -f && \\",
      r"git checkout branch1 && git rebase --onto branch2 branch1~1 && git push -f && \\",
      r"git checkout branch3 && git reset --hard branch1 && git push -f && \\",
      r"git checkout branch1",
      r"",
    ],
  )


def test_pulls4():
  """
  Description:
    Tests what happens when main and a branch on the same commit are both one commit behind their
    origins.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    commit("B", now + sec * 2),
    commit("C", now + sec * 3),
    "git push",
    "git checkout -b branch1 && git push && git reset --hard HEAD~1",
    "git checkout main && git reset --hard HEAD~1",
  )
  run_test(
    r"""
    *         C (origin/main, origin/branch1)
    *         B (HEAD -> main, branch1)
    *         A
    """,
    "branches",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main            ",
      r"  \w{5} > \w{5}    0  0 0  branch1         ",
      r"                                           ",
      r"git pull && \\",
      r"git checkout branch1 && git pull && \\",
      r"git checkout main",
      r"",
    ],
  )


def test_pulls5():
  """
  Description:
    Tests what happens when main and a branch on the same commit are behind their origins, with the
    branch's origin ahead of main's origin.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    commit("B", now + sec * 2),
    commit("C", now + sec * 3),
    "git push",
    commit("D", now + sec * 4),
    "git checkout -b branch1 && git push && git reset --hard HEAD~2",
    "git checkout main && git reset --hard HEAD~2",
  )
  run_test(
    r"""
    *         D (origin/branch1)
    *         C (origin/main)
    *         B (HEAD -> main, branch1)
    *         A
    """,
    "branches",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main            ",
      r"  \w{5} > \w{5}    0  0 0  branch1         ",
      r"                                           ",
      r"git pull && \\",
      r"git checkout branch1 && git pull && \\",
      r"git checkout main",
      r"",
    ],
  )


def test_pulls6():
  """
  Description:
    Tests what happens when main and a branch on the same commit are behind their origins, with
    main's origin ahead of the branch's origin: pull both, then rebase the branch onto main.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    commit("B", now + sec * 2),
    commit("C", now + sec * 3),
    commit("D", now + sec * 4),
    "git push",
    "git checkout -b branch1 HEAD~1 && git push && git reset --hard HEAD~1",
    "git checkout main && git reset --hard HEAD~2",
  )
  run_test(
    r"""
    *         D (origin/main)
    *         C (origin/branch1)
    *         B (HEAD -> main, branch1)
    *         A
    """,
    "branches",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main            ",
      r"  \w{5} > \w{5}    0  0 0  branch1         ",
      r"                                           ",
      r"git pull && \\",
      r"git checkout branch1 && git pull && \\",
      r"git rebase main && git push -f && \\",
      r"git checkout main",
      r"",
    ],
  )


def test_pulls7():
  """
  Description:
    Tests `branches amend` when the current branch is behind its origin.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch1 HEAD~1",
    commit("C", now + sec * 3),
    commit("D", now + sec * 4),
    "git push",
    "git checkout -b branch2",
    "git checkout branch1 && git reset --hard HEAD~1",
    "echo 'change' >> C.txt",
  )
  run_test(
    r"""
    *         D (origin/branch1, branch2)
    *         C (HEAD -> branch1)
    | *       B (origin/main, main)
    |/
    *         A
    """,
    "branches amend",
    [
      r"                                              ",
      r" Origin - Local  Age <- -> Branch  Base    PR ",
      r" ──────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main               ",
      r"  \w{5} > \w{5}    0  1 1  branch1            ",
      r"          \w{5}    0  1 2  branch2 branch1    ",
      r"                                              ",
      r"git add -A && git commit --amend --no-edit && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && \\",
      r"git checkout branch1",
      r"",
    ],
  )


def test_pulls8():
  """
  Description:
    Tests what happens when the branch origin is ahead but has other authors. This current behavior
    might be undesired. Probably not safe to rebase the local branch in this case automatically.
    We should let the user manually handle this case. The fact that there is other authors in origin
    might need to "pin" the local branch even if it's behind main.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch1 HEAD~1",
    commit("C", now + sec * 3),
    commit("D", now + sec * 4, "Name <me@git.com>"),
    "git push",
    "git reset --hard HEAD~1",
  )
  run_test(
    r"""
    *         D (origin/branch1)
    *         C (HEAD -> branch1)
    | *       B (origin/main, main)
    |/
    *         A
    """,
    "branches",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main            ",
      r" !\w{5} > \w{5}    0  1 1  branch1         ",
      r"                                           ",
      r"git rebase main",
      r"",
    ],
  )


def test_pull_amend_base():
  """
  Description:
    Tests `branches amend` when the current branch and the branch stacked on top of it are behind
    their origins.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch1 HEAD~1",
    commit("C", now + sec * 3),
    commit("D", now + sec * 4),
    "git push",
    "git checkout -b branch2",
    commit("E", now + sec * 5),
    "git checkout -b branch3 && git push",
    "git checkout branch2 && git push && git reset --hard HEAD~1",
    "git checkout branch1 && git reset --hard HEAD~1",
    "echo 'change' >> C.txt",
  )
  run_test(
    r"""
    *         E (origin/branch3, origin/branch2, branch3)
    *         D (origin/branch1, branch2)
    *         C (HEAD -> branch1)
    | *       B (origin/main, main)
    |/
    *         A
    """,
    "branches amend",
    [
      r"                                              ",
      r" Origin - Local  Age <- -> Branch  Base    PR ",
      r" ──────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main               ",
      r"  \w{5} > \w{5}    0  1 1  branch1            ",
      r"  \w{5} > \w{5}    0  1 2  branch2 branch1    ",
      r"  \w{5}   \w{5}    0  1 3  branch3 branch2    ",
      r"                                              ",
      r"git add -A && git commit --amend --no-edit && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && \\",
      r"git checkout branch3 && git rebase --onto branch2 branch3~1 && git push -f && \\",
      r"git checkout branch1",
      r"",
    ],
  )


def test_no_main():
  """
  Description:
    Tests what happens when there is no main branch and no origin
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    "git init && git checkout -b branch1",
    commit("A", now + sec * 1),
    commit("B", now + sec * 2),
  )
  run_test(
    r"""
    *         B (HEAD -> branch1)
    *         A
    """,
    "branches",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"          \w{5}    0  0 0  branch1         ",
      r"                                           ",
    ],
  )

  run_prep(
    "git checkout -b branch2",
    commit("C", now + sec * 3),
  )
  run_test(
    r"""
    *         C (HEAD -> branch2)
    *         B (branch1)
    *         A
    """,
    "branches",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"          \w{5}    0  0 0  branch1         ",
      r"          \w{5}    0  0 1  branch2         ",
      r"                                           ",
    ],
  )


def test_no_git_directory():
  """
  Description:
    Tests what happens when the branches command is not run in a git directory
  """
  run_test(
    None,
    "branches",
    "Not a git repository.",
    expected_returncode=1,
    directory=os.environ["HOME"],
  )


def test_path_argument():
  """
  Description:
    Tests the -C argument
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep("git init && " + commit("A", now + sec * 1))
  run_test(
    r"""
    *         A (HEAD -> main)
    """,
    "branches",
    "Not a git repository.",
    expected_returncode=1,
    directory=os.environ["HOME"],
  )

  run_test(
    r"""
    *         A (HEAD -> main)
    """,
    f"branches -C '{GIT_TMP_DIRPATH_LOCAL}'",
    [
      r"                                          ",
      r" Origin - Local  Age <- -> Branch Base PR ",
      r" ──────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main           ",
      r"                                          ",
    ],
    expected_returncode=0,
    directory=os.environ["HOME"],
  )


def test_worktree():
  """
  Description:
    Tests that branches checked out in another worktree are not displayed
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    f"git worktree add -b branch1 '{GIT_TMP_DIRPATH_WORKTREE}'",
    f"cd '{GIT_TMP_DIRPATH_WORKTREE}'",
    commit("B", now + sec * 2),
  )
  run_test(
    r"""
    *         B (branch1)
    *         A (HEAD -> main, origin/main)
    """,
    "branches",
    [
      r"                                          ",
      r" Origin - Local  Age <- -> Branch Base PR ",
      r" ──────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main           ",
      r"                                          ",
    ],
  )


def github_merge_and_rebase(branch_to_merge: str, branches_to_rebase: list[str]) -> list[str]:
  """Returns commands that simulate GitHub merging a stacked PR

  Squash-merges `branch_to_merge` into origin's main and deletes it from origin. Then, like GitHub
  does for stacked PRs, each of `branches_to_rebase` (in stack order) has its own commit
  cherry-picked on top of the previous one and is force pushed. Local branches are left untouched.
  """
  ret = [
    "git checkout main",
    f"git merge --squash {branch_to_merge}",
    f'git commit -m "$(git log -1 --format=%s {branch_to_merge})\' (#1)"',
    "git push",
    f"git push origin --delete {branch_to_merge}",
    "git checkout -b github_tmp",
  ]
  for branch in branches_to_rebase:
    ret += [f"git cherry-pick {branch}", f"git push -f origin github_tmp:{branch}"]
  ret += ["git checkout main", "git reset --hard HEAD~1", "git branch -D github_tmp"]
  return ret


def github_stack_pull_requests(rows: list[str], merged: str) -> list[tuple[str, list[dict]]]:
  """Returns mock server expectations for `rows` (in table order)

  `merged` gets a merged PR whose head is its local sha. Every other branch except main gets an open
  PR whose head is its origin sha.
  """
  ret = []
  for branch in rows:
    remote = run_command(f"git ls-remote origin {branch}").stdout.split()
    if branch == "main" or (not remote and branch != merged):
      ret.append((branch, []))
      continue

    number = len([prs for _, prs in ret if prs]) + 1
    pr = {
      "number": number,
      "title": branch,
      "html_url": f"http://localhost/branches/test_cli_origin/pull/{number}",
      "user": {"login": "santi-h"},
    }
    if branch == merged:
      pr |= {
        "state": "closed",
        "merged_at": "2026-10-25T16:46:11Z",
        "head": {"sha": run_command(f"git rev-parse {branch}").stdout.strip()},
      }
    else:
      pr |= {"state": "open", "head": {"sha": remote[0]}}
    ret.append((branch, [pr]))

  return ret


def test_github_rebased1(httpserver: HTTPServer):
  """
  Description:
    GitHub merged branch1 and rebased branch2 onto main. Locally, branch2 still sits on branch1.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch2",
    commit("C", now + sec * 3),
    "git push",
    *github_merge_and_rebase("branch1", ["branch2"]),
    "git checkout branch2",
  )
  set_mockserver_expectations(
    httpserver, github_stack_pull_requests(["main", "branch2", "branch1"], "branch1")
  )
  run_test(
    r"""
    *         C (origin/branch2)
    *         B' (#1) (origin/main)
    | *       C (HEAD -> branch2)
    | *       B (branch1)
    |/
    *         A (main)
    """,
    "branches",
    [
      r"                                                                 ",
      r" Origin - Local  Age <- -> Branch  Base    PR                    ",
      r" ─────────────────────────────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main                                  ",
      r"  \w{5} R \w{5}    0  0 2  branch2 branch1 #1 \(\w{5}\) by santi-h ",
      r"          \w{5}    0  0 1  branch1         #2 \(\w{5}\) by santi-h ",
      r"                                                                 ",
      r"git checkout main && \\",
      r"git branch -D branch1 && \\",
      r"git pull && \\",
      r"git branch -f branch2 \w{40} && \\",
      r"git checkout branch2",
      r"",
    ],
    httpserver=httpserver,
  )


def test_github_rebased2(httpserver: HTTPServer):
  """
  Description:
    Same as test_github_rebased1, but there is a local only branch3 stacked on top of branch2.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch2",
    commit("C", now + sec * 3),
    "git push",
    "git checkout -b branch3",
    commit("D", now + sec * 4),
    *github_merge_and_rebase("branch1", ["branch2"]),
    "git checkout branch3",
  )
  set_mockserver_expectations(
    httpserver, github_stack_pull_requests(["main", "branch3", "branch2", "branch1"], "branch1")
  )
  run_test(
    r"""
    *         D (HEAD -> branch3)
    | *       C (origin/branch2)
    | *       B' (#1) (origin/main)
    * |       C (branch2)
    * |       B (branch1)
    |/
    *         A (main)
    """,
    "branches",
    [
      r"                                                                 ",
      r" Origin - Local  Age <- -> Branch  Base    PR                    ",
      r" ─────────────────────────────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main                                  ",
      r"          \w{5}    0  0 3  branch3 branch2                       ",
      r"  \w{5} R \w{5}    0  0 2  branch2 branch1 #1 \(\w{5}\) by santi-h ",
      r"          \w{5}    0  0 1  branch1         #2 \(\w{5}\) by santi-h ",
      r"                                                                 ",
      r"git checkout main && \\",
      r"git branch -D branch1 && \\",
      r"git pull && \\",
      r"git branch -f branch2 \w{40} && \\",
      r"git checkout branch3 && git rebase --onto branch2 branch3~1",
      r"",
    ],
    httpserver=httpserver,
  )


def test_github_rebased3(httpserver: HTTPServer):
  """
  Description:
    Same as test_github_rebased2, but branch3 was pushed so GitHub rebased it as well.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch2",
    commit("C", now + sec * 3),
    "git push",
    "git checkout -b branch3",
    commit("D", now + sec * 4),
    "git push",
    *github_merge_and_rebase("branch1", ["branch2", "branch3"]),
    "git checkout branch3",
  )
  set_mockserver_expectations(
    httpserver, github_stack_pull_requests(["main", "branch3", "branch2", "branch1"], "branch1")
  )
  run_test(
    r"""
    *         D (origin/branch3)
    | *       D (HEAD -> branch3)
    * |       C (origin/branch2)
    * |       B' (#1) (origin/main)
    | *       C (branch2)
    | *       B (branch1)
    |/
    *         A (main)
    """,
    "branches",
    [
      r"                                                                 ",
      r" Origin - Local  Age <- -> Branch  Base    PR                    ",
      r" ─────────────────────────────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main                                  ",
      r"  \w{5} R \w{5}    0  0 3  branch3 branch2 #1 \(\w{5}\) by santi-h ",
      r"  \w{5} R \w{5}    0  0 2  branch2 branch1 #2 \(\w{5}\) by santi-h ",
      r"          \w{5}    0  0 1  branch1         #3 \(\w{5}\) by santi-h ",
      r"                                                                 ",
      r"git checkout main && \\",
      r"git branch -D branch1 && \\",
      r"git pull && \\",
      r"git branch -f branch2 \w{40} && \\",
      r"git branch -f branch3 \w{40} && \\",
      r"git checkout branch3",
      r"",
    ],
    httpserver=httpserver,
  )


def test_github_rebased4(httpserver: HTTPServer):
  """
  Description:
    Same as test_github_rebased1, but someone else pushed a commit to origin/branch2 after GitHub
    rebased it. This should not be treated as a GitHub rebase.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch2",
    commit("C", now + sec * 3),
    "git push",
    *github_merge_and_rebase("branch1", ["branch2"]),
    "git checkout -b tmp origin/main",
    "git cherry-pick branch2",
    commit("E", now + sec * 5, "Name <me@git.com>"),
    "git push -f origin tmp:branch2",
    "git checkout branch2",
    "git branch -D tmp",
  )
  set_mockserver_expectations(
    httpserver, github_stack_pull_requests(["main", "branch2", "branch1"], "branch1")
  )
  run_test(
    r"""
    *         E (origin/branch2)
    | *       C (HEAD -> branch2)
    * |       C
    * |       B' (#1) (origin/main)
    | *       B (branch1)
    |/
    *         A (main)
    """,
    "branches",
    [
      r"                                                                 ",
      r" Origin - Local  Age <- -> Branch  Base    PR                    ",
      r" ─────────────────────────────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main                                  ",
      r" !\w{5} Y \w{5}    0  0 2  branch2 branch1 #1 \(\w{5}\) by santi-h ",
      r"          \w{5}    0  0 1  branch1         #2 \(\w{5}\) by santi-h ",
      r"                                                                 ",
      r"git checkout main && \\",
      r"git branch -D branch1 && \\",
      r"git pull && \\",
      r"git checkout branch2 && git rebase main",
      r"",
    ],
    httpserver=httpserver,
  )


def test_github_rebased5(httpserver: HTTPServer):
  """
  Description:
    Same as test_github_rebased1, but origin/branch2's commit has a different diff than the local
    one. This should not be treated as a GitHub rebase.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch2",
    commit("C", now + sec * 3),
    "git push",
    *github_merge_and_rebase("branch1", ["branch2"]),
    "git checkout -b tmp origin/main",
    "git cherry-pick branch2",
    "echo 'changed' >> C.txt && git commit -a --amend --no-edit",
    "git push -f origin tmp:branch2",
    "git checkout branch2",
    "git branch -D tmp",
  )
  set_mockserver_expectations(
    httpserver, github_stack_pull_requests(["main", "branch2", "branch1"], "branch1")
  )
  run_test(
    r"""
    *         C (origin/branch2)
    *         B' (#1) (origin/main)
    | *       C (HEAD -> branch2)
    | *       B (branch1)
    |/
    *         A (main)
    """,
    "branches",
    [
      r"                                                                 ",
      r" Origin - Local  Age <- -> Branch  Base    PR                    ",
      r" ─────────────────────────────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main                                  ",
      r"  \w{5} Y \w{5}    0  0 2  branch2 branch1 #1 \(\w{5}\) by santi-h ",
      r"          \w{5}    0  0 1  branch1         #2 \(\w{5}\) by santi-h ",
      r"                                                                 ",
      r"git checkout main && \\",
      r"git branch -D branch1 && \\",
      r"git pull && \\",
      r"git checkout branch2 && git rebase main",
      r"",
    ],
    httpserver=httpserver,
  )


def test_github_rebased6(httpserver: HTTPServer):
  """
  Description:
    Same as test_github_rebased1, but main was already pulled and branch1 deleted, so branch2 is
    still checked out when it is reset.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch2",
    commit("C", now + sec * 3),
    "git push",
    *github_merge_and_rebase("branch1", ["branch2"]),
    "git pull",
    "git branch -D branch1",
    "git checkout branch2",
  )
  set_mockserver_expectations(httpserver, github_stack_pull_requests(["main", "branch2"], ""))
  run_test(
    r"""
    *         C (origin/branch2)
    *         B' (#1) (origin/main, origin/HEAD, main)
    | *       C (HEAD -> branch2)
    | *       B
    |/
    *         A
    """,
    "branches",
    [
      r"                                                              ",
      r" Origin - Local  Age <- -> Branch  Base PR                    ",
      r" ──────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                               ",
      r"  \w{5} R \w{5}    0  1 2  branch2      #1 \(\w{5}\) by santi-h ",
      r"                                                              ",
      r"git reset --keep \w{40}",
      r"",
    ],
    httpserver=httpserver,
  )


def test_github_rebased7(httpserver: HTTPServer):
  """
  Description:
    Same as test_github_rebased1, but another PR was merged into main after GitHub rebased branch2.
    Once reset, branch2 follows origin so rebasing it is followed by a force push.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch2",
    commit("C", now + sec * 3),
    "git push",
    *github_merge_and_rebase("branch1", ["branch2"]),
    "git checkout -b tmp origin/main",
    commit("E", now + sec * 5),
    "git push origin tmp:main",
    "git checkout branch2",
    "git branch -D tmp",
  )
  set_mockserver_expectations(
    httpserver, github_stack_pull_requests(["main", "branch2", "branch1"], "branch1")
  )
  run_test(
    r"""
    *         E (origin/main)
    | *       C (origin/branch2)
    |/
    *         B' (#1)
    | *       C (HEAD -> branch2)
    | *       B (branch1)
    |/
    *         A (main)
    """,
    "branches",
    [
      r"                                                                 ",
      r" Origin - Local  Age <- -> Branch  Base    PR                    ",
      r" ─────────────────────────────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main                                  ",
      r"  \w{5} R \w{5}    0  0 2  branch2 branch1 #1 \(\w{5}\) by santi-h ",
      r"          \w{5}    0  0 1  branch1         #2 \(\w{5}\) by santi-h ",
      r"                                                                 ",
      r"git checkout main && \\",
      r"git branch -D branch1 && \\",
      r"git pull && \\",
      r"git branch -f branch2 \w{40} && \\",
      r"git checkout branch2 && git rebase main && git push -f",
      r"",
    ],
    httpserver=httpserver,
  )


def test_github_rebased8(httpserver: HTTPServer):
  """
  Description:
    Same as test_github_rebased1, but branch3 (pushed, without a PR so GitHub did not rebase it) is
    stacked on branch2, and a local only branch4 is stacked on branch3.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch2",
    commit("C", now + sec * 3),
    "git push",
    "git checkout -b branch3",
    commit("D", now + sec * 4),
    "git push",
    "git checkout -b branch4",
    commit("E", now + sec * 5),
    *github_merge_and_rebase("branch1", ["branch2"]),
    "git checkout branch4",
  )
  set_mockserver_expectations(
    httpserver,
    [
      ("main", []),
      ("branch4", []),
      ("branch3", []),
      *github_stack_pull_requests(["branch2", "branch1"], "branch1"),
    ],
  )
  run_test(
    r"""
    *         E (HEAD -> branch4)
    *         D (origin/branch3, branch3)
    | *       C (origin/branch2)
    | *       B' (#1) (origin/main)
    * |       C (branch2)
    * |       B (branch1)
    |/
    *         A (main)
    """,
    "branches",
    [
      r"                                                                 ",
      r" Origin - Local  Age <- -> Branch  Base    PR                    ",
      r" ─────────────────────────────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main                                  ",
      r"          \w{5}    0  0 4  branch4 branch3                       ",
      r"  \w{5}   \w{5}    0  0 3  branch3 branch2                       ",
      r"  \w{5} R \w{5}    0  0 2  branch2 branch1 #1 \(\w{5}\) by santi-h ",
      r"          \w{5}    0  0 1  branch1         #2 \(\w{5}\) by santi-h ",
      r"                                                                 ",
      r"git checkout main && \\",
      r"git branch -D branch1 && \\",
      r"git pull && \\",
      r"git branch -f branch2 \w{40} && \\",
      r"git checkout branch3 && git rebase --onto branch2 branch3~1 && git push -f && \\",
      r"git checkout branch4 && git rebase --onto branch3 branch4~1",
      r"",
    ],
    httpserver=httpserver,
  )


def test_github_rebased9(httpserver: HTTPServer):
  """
  Description:
    branch1 was rebased locally onto a newer main but not pushed. origin/branch1 has the same commit
    on an older base, so it is not a rebased copy (`R`) and resetting to it would move branch1
    backwards.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    "git checkout main",
    commit("X", now + sec * 3),
    "git push",
    "git checkout branch1",
    "git rebase main",
  )
  set_mockserver_expectations(httpserver, github_stack_pull_requests(["main", "branch1"], ""))
  run_test(
    r"""
    *         B (HEAD -> branch1)
    *         X (origin/main, main)
    | *       B (origin/branch1)
    |/
    *         A
    """,
    "branches",
    [
      r"                                                              ",
      r" Origin - Local  Age <- -> Branch  Base PR                    ",
      r" ──────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                               ",
      r"  \w{5} Y \w{5}    0  0 1  branch1      #1 \(\w{5}\) by santi-h ",
      r"                                                              ",
    ],
    httpserver=httpserver,
  )


def test_github_rebased10(httpserver: HTTPServer):
  """
  Description:
    branch1 was amended locally (new date, same diff and author) but not pushed. origin/branch1 has
    the same commit on the same base, so it is not a rebased copy (`R`).
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)
  tformat = "%Y-%m-%dT%H:%M:%S%z"

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    f"git commit --amend --no-edit --date='{(now + sec * 3).strftime(tformat)}'",
  )
  set_mockserver_expectations(httpserver, github_stack_pull_requests(["main", "branch1"], ""))
  run_test(
    r"""
    *         B (HEAD -> branch1)
    | *       B (origin/branch1)
    |/
    *         A (origin/main, main)
    """,
    "branches",
    [
      r"                                                              ",
      r" Origin - Local  Age <- -> Branch  Base PR                    ",
      r" ──────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                               ",
      r"  \w{5} Y \w{5}    0  0 1  branch1      #1 \(\w{5}\) by santi-h ",
      r"                                                              ",
    ],
    httpserver=httpserver,
  )


def test_github_rebased11(httpserver: HTTPServer):
  """
  Description:
    Same as test_github_rebased1, but branch2 has two commits. GitHub merged branch1 and rebased
    branch2 onto main. Locally, branch2 still sits on branch1.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch2",
    commit("C1", now + sec * 3),
    commit("C2", now + sec * 4),
    "git push",
    *github_merge_and_rebase("branch1", []),
    "git checkout -b github_tmp origin/main",
    "git cherry-pick branch1..branch2",
    "git push -f origin github_tmp:branch2",
    "git checkout branch2",
    "git branch -D github_tmp",
  )
  set_mockserver_expectations(
    httpserver, github_stack_pull_requests(["main", "branch2", "branch1"], "branch1")
  )
  run_test(
    r"""
    *         C2 (origin/branch2)
    | *       C2 (HEAD -> branch2)
    * |       C1
    * |       B' (#1) (origin/main)
    | *       C1
    | *       B (branch1)
    |/
    *         A (main)
    """,
    "branches",
    [
      r"                                                                 ",
      r" Origin - Local  Age <- -> Branch  Base    PR                    ",
      r" ─────────────────────────────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main                                  ",
      r"  \w{5} R \w{5}    0  0 3  branch2 branch1 #1 \(\w{5}\) by santi-h ",
      r"          \w{5}    0  0 1  branch1         #2 \(\w{5}\) by santi-h ",
      r"                                                                 ",
      r"git checkout main && \\",
      r"git branch -D branch1 && \\",
      r"git pull && \\",
      r"git branch -f branch2 \w{40} && \\",
      r"git checkout branch2",
      r"",
    ],
    httpserver=httpserver,
  )


def test_github_rebased12(httpserver: HTTPServer):
  """
  Description:
    Same as test_github_rebased1, but branch2 has a local commit D that was never pushed.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch2",
    commit("C", now + sec * 3),
    "git push",
    *github_merge_and_rebase("branch1", ["branch2"]),
    "git checkout branch2",
    commit("D", now + sec * 4),
  )
  set_mockserver_expectations(
    httpserver, github_stack_pull_requests(["main", "branch2", "branch1"], "branch1")
  )
  run_test(
    r"""
    *         D (HEAD -> branch2)
    | *       C (origin/branch2)
    | *       B' (#1) (origin/main)
    * |       C
    * |       B (branch1)
    |/
    *         A (main)
    """,
    "branches",
    [
      r"                                                                 ",
      r" Origin - Local  Age <- -> Branch  Base    PR                    ",
      r" ─────────────────────────────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main                                  ",
      r"  \w{5} Y \w{5}    0  0 3  branch2 branch1 #1 \(\w{5}\) by santi-h ",
      r"          \w{5}    0  0 1  branch1         #2 \(\w{5}\) by santi-h ",
      r"                                                                 ",
      r"git checkout main && \\",
      r"git branch -D branch1 && \\",
      r"git pull && \\",
      r"git checkout branch2 && git rebase main",
      r"",
    ],
    httpserver=httpserver,
  )


def test_github_rebased13(httpserver: HTTPServer):
  """
  Description:
    Same as test_github_rebased1, but C was reworded locally (same diff) and not pushed.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch2",
    commit("C", now + sec * 3),
    "git push",
    *github_merge_and_rebase("branch1", ["branch2"]),
    "git checkout branch2",
    "git commit --amend -m 'C reworded'",
  )
  set_mockserver_expectations(
    httpserver, github_stack_pull_requests(["main", "branch2", "branch1"], "branch1")
  )
  run_test(
    r"""
    *         C reworded (HEAD -> branch2)
    | *       C (origin/branch2)
    | *       B' (#1) (origin/main)
    * |       B (branch1)
    |/
    *         A (main)
    """,
    "branches",
    [
      r"                                                                 ",
      r" Origin - Local  Age <- -> Branch  Base    PR                    ",
      r" ─────────────────────────────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main                                  ",
      r"  \w{5} R \w{5}    0  0 2  branch2 branch1 #1 \(\w{5}\) by santi-h ",
      r"          \w{5}    0  0 1  branch1         #2 \(\w{5}\) by santi-h ",
      r"                                                                 ",
      r"git checkout main && \\",
      r"git branch -D branch1 && \\",
      r"git pull && \\",
      r"git branch -f branch2 \w{40} && \\",
      r"git checkout branch2",
      r"",
    ],
    httpserver=httpserver,
  )


def test_github_rebased14(httpserver: HTTPServer):
  """
  Description:
    Same as test_github_rebased1, but branch2 also has an empty commit.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)
  empty_date = (now + sec * 4).strftime("%Y-%m-%dT%H:%M:%S%z")

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch2",
    commit("C", now + sec * 3),
    f"GIT_COMMITTER_DATE='{empty_date}' git commit --allow-empty -m empty --date='{empty_date}'",
    "git push",
    *github_merge_and_rebase("branch1", []),
    "git checkout -b github_tmp origin/main",
    "git cherry-pick --allow-empty branch1..branch2",
    "git push -f origin github_tmp:branch2",
    "git checkout branch2",
    "git branch -D github_tmp",
  )
  set_mockserver_expectations(
    httpserver, github_stack_pull_requests(["main", "branch2", "branch1"], "branch1")
  )
  run_test(
    r"""
    *         empty (origin/branch2)
    | *       empty (HEAD -> branch2)
    * |       C
    * |       B' (#1) (origin/main)
    | *       C
    | *       B (branch1)
    |/
    *         A (main)
    """,
    "branches",
    [
      r"                                                                 ",
      r" Origin - Local  Age <- -> Branch  Base    PR                    ",
      r" ─────────────────────────────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main                                  ",
      r"  \w{5} Y \w{5}    0  0 3  branch2 branch1 #1 \(\w{5}\) by santi-h ",
      r"          \w{5}    0  0 1  branch1         #2 \(\w{5}\) by santi-h ",
      r"                                                                 ",
      r"git checkout main && \\",
      r"git branch -D branch1 && \\",
      r"git pull && \\",
      r"git checkout branch2 && git rebase main",
      r"",
    ],
    httpserver=httpserver,
  )


def test_github_rebased15(httpserver: HTTPServer):
  """
  Description:
    Same as test_github_rebased1, but origin/branch2 also has a commit D by the same author, pushed from elsewhere after GitHub's rebase.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch2",
    commit("C", now + sec * 3),
    "git push",
    *github_merge_and_rebase("branch1", ["branch2"]),
    "git checkout -b tmp origin/branch2",
    commit("D", now + sec * 4),
    "git push origin tmp:branch2",
    "git checkout branch2",
    "git branch -D tmp",
  )
  set_mockserver_expectations(
    httpserver, github_stack_pull_requests(["main", "branch2", "branch1"], "branch1")
  )
  run_test(
    r"""
    *         D (origin/branch2)
    | *       C (HEAD -> branch2)
    * |       C
    * |       B' (#1) (origin/main)
    | *       B (branch1)
    |/
    *         A (main)
    """,
    "branches",
    [
      r"                                                                 ",
      r" Origin - Local  Age <- -> Branch  Base    PR                    ",
      r" ─────────────────────────────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main                                  ",
      r"  \w{5} Y \w{5}    0  0 2  branch2 branch1 #1 \(\w{5}\) by santi-h ",
      r"          \w{5}    0  0 1  branch1         #2 \(\w{5}\) by santi-h ",
      r"                                                                 ",
      r"git checkout main && \\",
      r"git branch -D branch1 && \\",
      r"git pull && \\",
      r"git checkout branch2 && git rebase main",
      r"",
    ],
    httpserver=httpserver,
  )


def test_github_rebased16(httpserver: HTTPServer):
  """
  Description:
    Same as test_github_rebased1, but there are two local only branches, branch3 and branch4, both
    stacked directly on top of branch2.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch2",
    commit("C", now + sec * 3),
    "git push",
    "git checkout -b branch3",
    commit("D", now + sec * 4),
    "git checkout -b branch4 branch2",
    commit("E", now + sec * 5),
    *github_merge_and_rebase("branch1", ["branch2"]),
    "git checkout branch4",
  )
  set_mockserver_expectations(
    httpserver,
    github_stack_pull_requests(["main", "branch4", "branch3", "branch2", "branch1"], "branch1"),
  )
  run_test(
    r"""
    *         E (HEAD -> branch4)
    | *       D (branch3)
    |/
    | *       C (origin/branch2)
    | *       B' (#1) (origin/main)
    * |       C (branch2)
    * |       B (branch1)
    |/
    *         A (main)
    """,
    "branches",
    [
      r"                                                                 ",
      r" Origin - Local  Age <- -> Branch  Base    PR                    ",
      r" ─────────────────────────────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main                                  ",
      r"          \w{5}    0  0 3  branch4 branch2                       ",
      r"          \w{5}    0  0 3  branch3 branch2                       ",
      r"  \w{5} R \w{5}    0  0 2  branch2 branch1 #1 \(\w{5}\) by santi-h ",
      r"          \w{5}    0  0 1  branch1         #2 \(\w{5}\) by santi-h ",
      r"                                                                 ",
      r"git checkout main && \\",
      r"git branch -D branch1 && \\",
      r"git pull && \\",
      r"git branch -f branch2 \w{40} && \\",
      r"git checkout branch3 && git rebase --onto branch2 branch3~1 && \\",
      r"git checkout branch4 && git rebase --onto branch3~1 branch4~1",
      r"",
    ],
    httpserver=httpserver,
  )


def test_github_rebased17(httpserver: HTTPServer):
  """
  Description:
    Same as test_github_rebased10, but origin/branch1 was fetched shallow, so locally it has no
    parents and no merge base with main.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)
  tformat = "%Y-%m-%dT%H:%M:%S%z"

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    f"git commit --amend --no-edit --date='{(now + sec * 3).strftime(tformat)}'",
    "git fetch --depth=1 origin branch1",
  )
  set_mockserver_expectations(httpserver, github_stack_pull_requests(["main", "branch1"], ""))
  run_test(
    r"""
    *         B (HEAD -> branch1)
    | *       B (grafted, origin/branch1)
    *         A (origin/main, main)
    """,
    "branches",
    [
      r"                                                              ",
      r" Origin - Local  Age <- -> Branch  Base PR                    ",
      r" ──────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                               ",
      r"  \w{5} Y \w{5}    0  0 1  branch1      #1 \(\w{5}\) by santi-h ",
      r"                                                              ",
    ],
    httpserver=httpserver,
  )


def other_author_pull_requests(
  rows: list[str], prs: dict[str, dict]
) -> list[tuple[str, list[dict]]]:
  """Returns mock server expectations for `rows` (in table order)

  Each branch in `prs` gets a PR opened by another user whose head is its origin sha, with
  `prs[branch]` merged into it. Every other branch gets no PR.
  """
  ret = []
  for branch in rows:
    if branch not in prs:
      ret.append((branch, []))
      continue

    number = len([prs for _, prs in ret if prs]) + 1
    pr = {
      "number": number,
      "title": branch,
      "html_url": f"http://localhost/branches/test_cli_origin/pull/{number}",
      "user": {"login": "someone"},
      "head": {"sha": run_command(f"git rev-parse origin/{branch}").stdout.strip()},
    }
    ret.append((branch, [pr | prs[branch]]))

  return ret


def locked_prep(now: datetime, sec: timedelta) -> list[str]:
  """Returns commands that create branch1 with a commit by another author, in sync with origin"""
  return [
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2, "Name <me@git.com>"),
    "git push",
    "git checkout main",
    commit("C", now + sec * 3),
    "git push",
  ]


def test_locked1(httpserver: HTTPServer):
  """
  Description:
    branch1 has commits by another author, is in sync with origin, and has an open PR.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(*locked_prep(now, sec))
  set_mockserver_expectations(
    httpserver, other_author_pull_requests(["main", "branch1"], {"branch1": {"state": "open"}})
  )
  run_test(
    r"""
    *         C (HEAD -> main, origin/main)
    | *       B (origin/branch1, branch1)
    |/
    *         A
    """,
    "branches",
    [
      r"                                                               ",
      r" Origin - Local  Age <- ->  Branch  Base PR                    ",
      r" ───────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0   main                               ",
      r" !\w{5}   \w{5}!   0  1 1 L branch1      #1 \(\w{5}\) by someone ",
      r"                                                               ",
    ],
    httpserver=httpserver,
  )


def test_locked2(httpserver: HTTPServer):
  """
  Description:
    Same as test_locked1, but the PR is a draft.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(*locked_prep(now, sec))
  set_mockserver_expectations(
    httpserver,
    other_author_pull_requests(["main", "branch1"], {"branch1": {"state": "open", "draft": True}}),
  )
  run_test(
    r"""
    *         C (HEAD -> main, origin/main)
    | *       B (origin/branch1, branch1)
    |/
    *         A
    """,
    "branches",
    [
      r"                                                               ",
      r" Origin - Local  Age <- ->  Branch  Base PR                    ",
      r" ───────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0   main                               ",
      r" !\w{5}   \w{5}!   0  1 1 L branch1      #1 \(\w{5}\) by someone ",
      r"                                                               ",
    ],
    httpserver=httpserver,
  )


def test_locked3(httpserver: HTTPServer):
  """
  Description:
    Same as test_locked1, but the PR was closed without merging.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(*locked_prep(now, sec))
  set_mockserver_expectations(
    httpserver, other_author_pull_requests(["main", "branch1"], {"branch1": {"state": "closed"}})
  )
  run_test(
    r"""
    *         C (HEAD -> main, origin/main)
    | *       B (origin/branch1, branch1)
    |/
    *         A
    """,
    "branches",
    [
      r"                                                              ",
      r" Origin - Local  Age <- -> Branch  Base PR                    ",
      r" ──────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                               ",
      r" !\w{5}   \w{5}!   0  1 1  branch1      #1 \(\w{5}\) by someone ",
      r"                                                              ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout main",
      r"",
    ],
    httpserver=httpserver,
  )


def test_locked4(httpserver: HTTPServer):
  """
  Description:
    Same as test_locked1, but there is no PR.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(*locked_prep(now, sec))
  set_mockserver_expectations(httpserver, other_author_pull_requests(["main", "branch1"], {}))
  run_test(
    r"""
    *         C (HEAD -> main, origin/main)
    | *       B (origin/branch1, branch1)
    |/
    *         A
    """,
    "branches",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main            ",
      r" !\w{5}   \w{5}!   0  1 1  branch1         ",
      r"                                           ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout main",
      r"",
    ],
    httpserver=httpserver,
  )


def test_locked5(httpserver: HTTPServer):
  """
  Description:
    Same as test_locked1, but local branch1 has a commit that is not in origin.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    *locked_prep(now, sec),
    "git checkout branch1",
    commit("D", now + sec * 4),
    "git checkout main",
  )
  set_mockserver_expectations(
    httpserver, other_author_pull_requests(["main", "branch1"], {"branch1": {"state": "open"}})
  )
  run_test(
    r"""
    *         D (branch1)
    | *       C (HEAD -> main, origin/main)
    * |       B (origin/branch1)
    |/
    *         A
    """,
    "branches",
    [
      r"                                                              ",
      r" Origin - Local  Age <- -> Branch  Base PR                    ",
      r" ──────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                               ",
      r" !\w{5} < \w{5}!   0  1 2  branch1      #1 \(\w{5}\) by someone ",
      r"                                                              ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout main",
      r"",
    ],
    httpserver=httpserver,
  )


def test_locked6(httpserver: HTTPServer):
  """
  Description:
    Same as test_locked1, but branch1 has no commits by other authors.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    "git checkout main",
    commit("C", now + sec * 3),
    "git push",
  )
  set_mockserver_expectations(
    httpserver, other_author_pull_requests(["main", "branch1"], {"branch1": {"state": "open"}})
  )
  run_test(
    r"""
    *         C (HEAD -> main, origin/main)
    | *       B (origin/branch1, branch1)
    |/
    *         A
    """,
    "branches",
    [
      r"                                                              ",
      r" Origin - Local  Age <- -> Branch  Base PR                    ",
      r" ──────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                               ",
      r"  \w{5}   \w{5}    0  1 1  branch1      #1 \(\w{5}\) by someone ",
      r"                                                              ",
      r"git checkout branch1 && git rebase main && git push -f && \\",
      r"git checkout main",
      r"",
    ],
    httpserver=httpserver,
  )


def test_locked7(httpserver: HTTPServer):
  """
  Description:
    Same as test_locked1, but there are local only branches stacked on top of branch1.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    *locked_prep(now, sec),
    "git checkout -b branch2 branch1",
    commit("D", now + sec * 4),
    "git checkout -b branch3",
    commit("E", now + sec * 5),
  )
  set_mockserver_expectations(
    httpserver,
    other_author_pull_requests(
      ["main", "branch3", "branch2", "branch1"], {"branch1": {"state": "open"}}
    ),
  )
  run_test(
    r"""
    *         E (HEAD -> branch3)
    *         D (branch2)
    | *       C (origin/main, main)
    * |       B (origin/branch1, branch1)
    |/
    *         A
    """,
    "branches",
    [
      r"                                                                  ",
      r" Origin - Local  Age <- ->  Branch  Base    PR                    ",
      r" ──────────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0   main                                  ",
      r"          \w{5}!   0  1 3   branch3 branch2                       ",
      r"          \w{5}!   0  1 2   branch2 branch1                       ",
      r" !\w{5}   \w{5}!   0  1 1 L branch1         #1 \(\w{5}\) by someone ",
      r"                                                                  ",
    ],
    httpserver=httpserver,
  )


def test_locked8(httpserver: HTTPServer):
  """
  Description:
    Same as test_locked7, but branch1 got another commit after branch2 branched off of it.
    B and F are by another author.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    *locked_prep(now, sec),
    "git checkout -b branch2 branch1",
    commit("D", now + sec * 4),
    "git checkout -b branch3",
    commit("E", now + sec * 5),
    "git checkout branch1",
    commit("F", now + sec * 6, "Name <me@git.com>"),
    "git push",
    "git checkout branch3",
  )
  set_mockserver_expectations(
    httpserver,
    other_author_pull_requests(
      ["main", "branch3", "branch1", "branch2"], {"branch1": {"state": "open"}}
    ),
  )
  run_test(
    r"""
    *         F (origin/branch1, branch1)
    | *       E (HEAD -> branch3)
    | *       D (branch2)
    |/
    | *       C (origin/main, main)
    * |       B
    |/
    *         A
    """,
    "branches",
    [
      r"                                                                    ",
      r" Origin - Local  Age <- ->  Branch  Base      PR                    ",
      r" ────────────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0   main                                    ",
      r"          \w{5}!   0  1 3   branch3 branch2                         ",
      r" !\w{5}   \w{5}!   0  1 2 L branch1           #1 \(\w{5}\) by someone ",
      r"          \w{5}!   0  1 2   branch2 branch1~1                       ",
      r"                                                                    ",
    ],
    httpserver=httpserver,
  )


def test_locked9(httpserver: HTTPServer):
  """
  Description:
    Same as test_locked1, but the PR author pushed D to origin/branch1, so origin is ahead of local.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    *locked_prep(now, sec),
    "git checkout -b tmp branch1",
    commit("D", now + sec * 4, "Name <me@git.com>"),
    "git push origin tmp:branch1",
    "git checkout main",
    "git branch -D tmp",
  )
  set_mockserver_expectations(
    httpserver, other_author_pull_requests(["main", "branch1"], {"branch1": {"state": "open"}})
  )
  run_test(
    r"""
    *         D (origin/branch1)
    | *       C (HEAD -> main, origin/main)
    * |       B (branch1)
    |/
    *         A
    """,
    "branches",
    [
      r"                                                              ",
      r" Origin - Local  Age <- -> Branch  Base PR                    ",
      r" ──────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                               ",
      r" !\w{5} > \w{5}!   0  1 1  branch1      #1 \(\w{5}\) by someone ",
      r"                                                              ",
      r"git checkout branch1 && git pull && \\",
      r"git checkout main",
      r"",
    ],
    httpserver=httpserver,
  )


def test_locked10(httpserver: HTTPServer):
  """
  Description:
    Same as test_locked9, but there is a local only branch stacked on top of branch1.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    *locked_prep(now, sec),
    "git checkout -b branch2 branch1",
    commit("D", now + sec * 4),
    "git checkout -b tmp branch1",
    commit("E", now + sec * 5, "Name <me@git.com>"),
    "git push origin tmp:branch1",
    "git checkout branch2",
    "git branch -D tmp",
  )
  set_mockserver_expectations(
    httpserver,
    other_author_pull_requests(["main", "branch2", "branch1"], {"branch1": {"state": "open"}}),
  )
  run_test(
    r"""
    *         E (origin/branch1)
    | *       D (HEAD -> branch2)
    |/
    | *       C (origin/main, main)
    * |       B (branch1)
    |/
    *         A
    """,
    "branches",
    [
      r"                                                                 ",
      r" Origin - Local  Age <- -> Branch  Base    PR                    ",
      r" ─────────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                                  ",
      r"          \w{5}!   0  1 2  branch2 branch1                       ",
      r" !\w{5} > \w{5}!   0  1 1  branch1         #1 \(\w{5}\) by someone ",
      r"                                                                 ",
      r"git checkout branch1 && git pull && \\",
      r"git checkout branch2",
      r"",
    ],
    httpserver=httpserver,
  )


def test_locked11(httpserver: HTTPServer):
  """
  Description:
    Same as test_locked1, but the PR author rebased origin/branch1 onto main, so origin is a rebased
    copy of local.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    *locked_prep(now, sec),
    "git checkout -b tmp main",
    "git cherry-pick branch1",
    # Later author date than C, so the order in `git_graph` is deterministic
    f"GIT_COMMITTER_DATE='{(now + sec * 4).isoformat()}' git commit --amend --no-edit"
    f" --date='{(now + sec * 4).isoformat()}'",
    "git push -f origin tmp:branch1",
    "git checkout main",
    "git branch -D tmp",
  )
  set_mockserver_expectations(
    httpserver, other_author_pull_requests(["main", "branch1"], {"branch1": {"state": "open"}})
  )
  run_test(
    r"""
    *         B (origin/branch1)
    *         C (HEAD -> main, origin/main)
    | *       B (branch1)
    |/
    *         A
    """,
    "branches",
    [
      r"                                                              ",
      r" Origin - Local  Age <- -> Branch  Base PR                    ",
      r" ──────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                               ",
      r" !\w{5} R \w{5}!   0  1 1  branch1      #1 \(\w{5}\) by someone ",
      r"                                                              ",
      r"git branch -f branch1 \w{40}",
      r"",
    ],
    httpserver=httpserver,
  )


def test_locked12(httpserver: HTTPServer):
  """
  Description:
    Same as test_locked9, but local branch1 also has D, which is not in origin.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    *locked_prep(now, sec),
    "git checkout -b tmp branch1",
    commit("E", now + sec * 5, "Name <me@git.com>"),
    "git push origin tmp:branch1",
    "git checkout branch1",
    commit("D", now + sec * 4),
    "git checkout main",
    "git branch -D tmp",
  )
  set_mockserver_expectations(
    httpserver, other_author_pull_requests(["main", "branch1"], {"branch1": {"state": "open"}})
  )
  run_test(
    r"""
    *         E (origin/branch1)
    | *       D (branch1)
    |/
    | *       C (HEAD -> main, origin/main)
    * |       B
    |/
    *         A
    """,
    "branches",
    [
      r"                                                              ",
      r" Origin - Local  Age <- -> Branch  Base PR                    ",
      r" ──────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                               ",
      r" !\w{5} Y \w{5}!   0  1 2  branch1      #1 \(\w{5}\) by someone ",
      r"                                                              ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout main",
      r"",
    ],
    httpserver=httpserver,
  )


def test_locked13(httpserver: HTTPServer):
  """
  Description:
    branch2 is locked and stacked on branch1, which is mine. branch3 is stacked on branch2 and
    branch4 is stacked on branch1. None of them are behind their base.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git push",
    "git checkout -b branch2",
    commit("D", now + sec * 4, "Name <me@git.com>"),
    "git push",
    "git checkout -b branch3",
    commit("E", now + sec * 5),
    "git checkout -b branch4 branch1",
    commit("F", now + sec * 6),
    "git checkout main",
    commit("C", now + sec * 3),
    "git push",
  )
  set_mockserver_expectations(
    httpserver,
    other_author_pull_requests(
      ["main", "branch4", "branch3", "branch2", "branch1"], {"branch2": {"state": "open"}}
    ),
  )
  run_test(
    r"""
    *         F (branch4)
    | *       E (branch3)
    | *       D (origin/branch2, branch2)
    |/
    | *       C (HEAD -> main, origin/main)
    * |       B (origin/branch1, branch1)
    |/
    *         A
    """,
    "branches",
    [
      r"                                                                  ",
      r" Origin - Local  Age <- ->  Branch  Base    PR                    ",
      r" ──────────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0   main                                  ",
      r"          \w{5}    0  1 2   branch4 branch1                       ",
      r"          \w{5}!   0  1 3   branch3 branch2                       ",
      r" !\w{5}   \w{5}!   0  1 2 L branch2 branch1 #1 \(\w{5}\) by someone ",
      r"  \w{5}   \w{5}    0  1 1   branch1                               ",
      r"                                                                  ",
    ],
    httpserver=httpserver,
  )


def squash_prep(now: datetime, sec: timedelta, author: str | None = None) -> list[str]:
  """Returns commands that create branch1 with two commits and branches stacked around it"""
  return [
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git checkout -b branch1",
    commit("B", now + sec * 2, author),
    commit("C", now + sec * 3),
    "git checkout -b branch2",
    commit("D", now + sec * 4),
    "git checkout branch1~1 && git checkout -b branch4",
    commit("G", now + sec * 7),
    "git checkout main",
    commit("E", now + sec * 5),
    "git checkout main~1 && git checkout -b branch3",
    commit("F", now + sec * 6),
    "git checkout branch1",
  ]


def test_squash1():
  """
  Description:
    Squashing C into B on branch1 suggests the squash and restacks branch2 and branch4 on top of
    it. branch4 branched off B, so it picks up C.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(*squash_prep(now, sec))
  run_test(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (main)
    | |/
    | | *     D (branch2)
    | | *     C (HEAD -> branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    "branches squash",
    [
      r"                                                ",
      r" Origin - Local  Age <- -> Branch  Base      PR ",
      r" ────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                 ",
      r"          \w{5}    0  1 2  branch1              ",
      r"          \w{5}    0  1 3  branch2 branch1      ",
      r"          \w{5}    0  1 2  branch4 branch1~1    ",
      r"                                                ",
      r"git reset --soft HEAD~1 && git commit --amend --no-edit && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && \\",
      r"git checkout branch4 && git rebase --onto branch1 branch4~1 && \\",
      r"git checkout branch1",
      r"",
    ],
  )


def test_squash2():
  """
  Description:
    Same as test_squash1, but branch1 and branch2 are in sync with origin, so the squash suggests
    force pushing them, unless --no-push is given.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    *squash_prep(now, sec),
    "git checkout main && git push",
    "git checkout branch1 && git push",
    "git checkout branch2 && git push",
    "git checkout branch1",
  )
  run_test(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (origin/main, main)
    | |/
    | | *     D (origin/branch2, branch2)
    | | *     C (HEAD -> branch1, origin/branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    "branches squash",
    [
      r"                                                ",
      r" Origin - Local  Age <- -> Branch  Base      PR ",
      r" ────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                 ",
      r"  \w{5}   \w{5}    0  1 2  branch1              ",
      r"  \w{5}   \w{5}    0  1 3  branch2 branch1      ",
      r"          \w{5}    0  1 2  branch4 branch1~1    ",
      r"                                                ",
      r"git reset --soft HEAD~1 && git commit --amend --no-edit && git push -f && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && git push -f && \\",
      r"git checkout branch4 && git rebase --onto branch1 branch4~1 && \\",
      r"git checkout branch1",
      r"",
    ],
  )
  run_test(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (origin/main, main)
    | |/
    | | *     D (origin/branch2, branch2)
    | | *     C (HEAD -> branch1, origin/branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    "branches squash --no-push",
    [
      r"                                                ",
      r" Origin - Local  Age <- -> Branch  Base      PR ",
      r" ────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                 ",
      r"  \w{5}   \w{5}    0  1 2  branch1              ",
      r"  \w{5}   \w{5}    0  1 3  branch2 branch1      ",
      r"          \w{5}    0  1 2  branch4 branch1~1    ",
      r"                                                ",
      r"git reset --soft HEAD~1 && git commit --amend --no-edit && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && \\",
      r"git checkout branch4 && git rebase --onto branch1 branch4~1 && \\",
      r"git checkout branch1",
      r"",
    ],
  )


def test_squash3():
  """
  Description:
    Same as test_squash1, but runs the suggested commands. branch1 ends up with a single commit
    that keeps B's message, and branch2 and branch4 are stacked on top of it.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(*squash_prep(now, sec))
  run_test(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (main)
    | |/
    | | *     D (branch2)
    | | *     C (HEAD -> branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    "branches squash -y",
    [
      r"                                                ",
      r" Origin - Local  Age <- -> Branch  Base      PR ",
      r" ────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                 ",
      r"          \w{5}    0  1 2  branch1              ",
      r"          \w{5}    0  1 3  branch2 branch1      ",
      r"          \w{5}    0  1 2  branch4 branch1~1    ",
      r"                                                ",
      r"git reset --soft HEAD~1 && git commit --amend --no-edit && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && \\",
      r"git checkout branch4 && git rebase --onto branch1 branch4~1 && \\",
      r"git checkout branch1",
      r"",
      r"\[branch1 \w{7}\] B",
      r" Date: .*",
      r" 2 files changed, 2 insertions\(\+\)",
      r" create mode 100644 B.txt",
      r" create mode 100644 C.txt",
      r"Switched to branch 'branch2'",
      r"Rebasing \(1/1\)",
      r"Successfully rebased and updated refs/heads/branch2.",
      r"Switched to branch 'branch4'",
      r"Rebasing \(1/1\)",
      r"Successfully rebased and updated refs/heads/branch4.",
      r"Switched to branch 'branch1'",
    ],
  )

  assert run_command("git log -1 --format=%s branch1").stdout == "B\n"
  assert run_command("git rev-list --count main~1..branch1").stdout == "1\n"
  assert run_command("git ls-tree --name-only branch1").stdout == "A.txt\nB.txt\nC.txt\n"
  assert (
    run_command("git rev-parse branch2~1").stdout == run_command("git rev-parse branch1").stdout
  )
  assert (
    run_command("git rev-parse branch4~1").stdout == run_command("git rev-parse branch1").stdout
  )
  assert run_command("git status --porcelain").stdout == ""


def test_squash4():
  """
  Description:
    Same as test_squash2, but B was authored by someone else, so the squash does not suggest
    force pushing branch1.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    *squash_prep(now, sec, "Name <me@git.com>"),
    "git checkout main && git push",
    "git checkout branch1 && git push",
    "git checkout branch2 && git push",
    "git checkout branch1",
  )
  run_test(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (origin/main, main)
    | |/
    | | *     D (origin/branch2, branch2)
    | | *     C (HEAD -> branch1, origin/branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    "branches squash",
    [
      r"                                                ",
      r" Origin - Local  Age <- -> Branch  Base      PR ",
      r" ────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                 ",
      r" !\w{5}   \w{5}!   0  1 2  branch1              ",
      r" !\w{5}   \w{5}!   0  1 3  branch2 branch1      ",
      r"          \w{5}!   0  1 2  branch4 branch1~1    ",
      r"                                                ",
      r"git reset --soft HEAD~1 && git commit --amend --no-edit && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && \\",
      r"git checkout branch4 && git rebase --onto branch1 branch4~1 && \\",
      r"git checkout branch1",
      r"",
    ],
  )


def test_squash5():
  """
  Description:
    Squashing is refused when there is no second to last commit on the current branch to squash
    into: on the main branch, on a detached HEAD, on a branch with a single commit (branch3), and
    on a branch whose second to last commit belongs to its base branch (branch2).
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(*squash_prep(now, sec))
  run_prep("git checkout main")
  run_test(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (HEAD -> main)
    | |/
    | | *     D (branch2)
    | | *     C (branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    "branches squash",
    [
      r"                                          ",
      r" Origin - Local  Age <- -> Branch Base PR ",
      r" ──────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main           ",
      r"                                          ",
      r"Cannot run squash on the main branch. Checkout a different branch.",
      r"",
    ],
    expected_returncode=1,
  )
  run_prep("git checkout --detach branch1")
  run_test(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (main)
    | |/
    | | *     D (branch2)
    | | *     C (HEAD, branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    "branches squash",
    [
      r"                                          ",
      r" Origin - Local  Age <- -> Branch Base PR ",
      r" ──────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main           ",
      r"                                          ",
      r"Cannot run squash on a detached HEAD. Check out a branch first.",
      r"",
    ],
    expected_returncode=1,
  )
  run_prep("git checkout branch3")
  run_test(
    r"""
    *         G (branch4)
    | *       F (HEAD -> branch3)
    | | *     E (main)
    | |/
    | | *     D (branch2)
    | | *     C (branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    "branches squash",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main            ",
      r"          \w{5}    0  1 1  branch3         ",
      r"                                           ",
      r"Cannot run squash: branch3 needs at least two commits on top of main.",
      r"",
    ],
    expected_returncode=1,
  )
  run_prep("git checkout branch2")
  run_test(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (main)
    | |/
    | | *     D (HEAD -> branch2)
    | | *     C (branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    "branches squash",
    [
      r"                                                ",
      r" Origin - Local  Age <- -> Branch  Base      PR ",
      r" ────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                 ",
      r"          \w{5}    0  1 3  branch2 branch1      ",
      r"          \w{5}    0  1 2  branch1              ",
      r"          \w{5}    0  1 2  branch4 branch1~1    ",
      r"                                                ",
      r"Cannot run squash: branch2 needs at least two commits on top of branch1.",
      r"",
    ],
    expected_returncode=1,
  )


def test_squash6():
  """
  Description:
    Squashing is refused when there are staged, unstaged, or untracked changes.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(*squash_prep(now, sec))
  run_prep("echo 'changed' >> C.txt && git add C.txt")
  run_test(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (main)
    | |/
    | | *     D (branch2)
    | | *     C (HEAD -> branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    "branches squash",
    [
      r"                                                ",
      r" Origin - Local  Age <- -> Branch  Base      PR ",
      r" ────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                 ",
      r"          \w{5}    0  1 2  branch1              ",
      r"          \w{5}    0  1 3  branch2 branch1      ",
      r"          \w{5}    0  1 2  branch4 branch1~1    ",
      r"                                                ",
      r"Cannot run squash with uncommitted changes. Commit or stash them first.",
      r"",
    ],
    expected_returncode=1,
    cleanup_command="git reset HEAD && git checkout .",
  )
  run_prep("echo 'changed' >> C.txt")
  run_test(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (main)
    | |/
    | | *     D (branch2)
    | | *     C (HEAD -> branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    "branches squash",
    [
      r"                                                ",
      r" Origin - Local  Age <- -> Branch  Base      PR ",
      r" ────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                 ",
      r"          \w{5}    0  1 2  branch1              ",
      r"          \w{5}    0  1 3  branch2 branch1      ",
      r"          \w{5}    0  1 2  branch4 branch1~1    ",
      r"                                                ",
      r"Cannot run squash with uncommitted changes. Commit or stash them first.",
      r"",
    ],
    expected_returncode=1,
    cleanup_command="git checkout .",
  )
  run_prep("echo 'new' > new.txt")
  run_test(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (main)
    | |/
    | | *     D (branch2)
    | | *     C (HEAD -> branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    "branches squash",
    [
      r"                                                ",
      r" Origin - Local  Age <- -> Branch  Base      PR ",
      r" ────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                 ",
      r"          \w{5}    0  1 2  branch1              ",
      r"          \w{5}    0  1 3  branch2 branch1      ",
      r"          \w{5}    0  1 2  branch4 branch1~1    ",
      r"                                                ",
      r"Cannot run squash with uncommitted changes. Commit or stash them first.",
      r"",
    ],
    expected_returncode=1,
    cleanup_command="git clean -fd",
  )


def test_squash7():
  """
  Description:
    Squashing is refused when the current branch has merge commits.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    *squash_prep(now, sec),
    "git merge --no-edit branch3",
    commit("H", now + sec * 8),
  )
  run_test(
    r"""
    *         H (HEAD -> branch1)
    *         Merge branch 'branch3' into branch1
    |\
    | | *     G (branch4)
    | * |     F (branch3)
    | | | *   E (main)
    | | |/
    | |/|
    | | | *   D (branch2)
    | |_|/
    |/| |
    * | |     C
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    "branches squash",
    [
      r"                                            ",
      r" Origin - Local  Age <- ->  Branch  Base PR ",
      r" ────────────────────────────────────────── ",
      r"          \w{5}    0  0 0   main            ",
      r"          \w{5}    0  1 5 M branch1         ",
      r"                                            ",
      r"Tool limitation: cannot squash or update branches with merge commits.",
    ],
    expected_returncode=1,
  )


def test_amend_message1():
  """
  Description:
    `amend -m` with no changes rewords the last commit and restacks branch2 on top of it. The
    message is quoted in the suggested command.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(*squash_prep(now, sec))
  run_test(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (main)
    | |/
    | | *     D (branch2)
    | | *     C (HEAD -> branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    """branches amend -m "It's \\$HOME" -y""",
    [
      r"                                                ",
      r" Origin - Local  Age <- -> Branch  Base      PR ",
      r" ────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                 ",
      r"          \w{5}    0  1 2  branch1              ",
      r"          \w{5}    0  1 3  branch2 branch1      ",
      r"          \w{5}    0  1 2  branch4 branch1~1    ",
      r"                                                ",
      re.escape("""git add -A && git commit --amend -m 'It'"'"'s $HOME' && \\"""),
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && \\",
      r"git checkout branch1",
      r"",
      r"\[branch1 \w{7}\] It's \$HOME",
      r" Date: .*",
      r" 1 file changed, 1 insertion\(\+\)",
      r" create mode 100644 C.txt",
      r"Switched to branch 'branch2'",
      r"Rebasing \(1/1\)",
      r"Successfully rebased and updated refs/heads/branch2.",
      r"Switched to branch 'branch1'",
    ],
  )
  assert_graph(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (main)
    | |/
    | | *     D (branch2)
    | | *     It's $HOME (HEAD -> branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """
  )


def test_amend_message2():
  """
  Description:
    `amend -m` with changes amends them into the last commit and replaces its message.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(*squash_prep(now, sec), "echo 'changed' >> C.txt")
  run_test(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (main)
    | |/
    | | *     D (branch2)
    | | *     C (HEAD -> branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    "branches amend --message 'C2'",
    [
      r"                                                ",
      r" Origin - Local  Age <- -> Branch  Base      PR ",
      r" ────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                 ",
      r"          \w{5}    0  1 2  branch1              ",
      r"          \w{5}    0  1 3  branch2 branch1      ",
      r"          \w{5}    0  1 2  branch4 branch1~1    ",
      r"                                                ",
      r"git add -A && git commit --amend -m C2 && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && \\",
      r"git checkout branch1",
      r"",
    ],
  )


def test_squash_message1():
  """
  Description:
    `squash -m` squashes C into B with the given message and restacks branch2 and branch4.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(*squash_prep(now, sec))
  run_test(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (main)
    | |/
    | | *     D (branch2)
    | | *     C (HEAD -> branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    "branches squash -m 'B and C' -y",
    [
      r"                                                ",
      r" Origin - Local  Age <- -> Branch  Base      PR ",
      r" ────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                 ",
      r"          \w{5}    0  1 2  branch1              ",
      r"          \w{5}    0  1 3  branch2 branch1      ",
      r"          \w{5}    0  1 2  branch4 branch1~1    ",
      r"                                                ",
      r"git reset --soft HEAD~1 && git commit --amend -m 'B and C' && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && \\",
      r"git checkout branch4 && git rebase --onto branch1 branch4~1 && \\",
      r"git checkout branch1",
      r"",
      r"\[branch1 \w{7}\] B and C",
      r" Date: .*",
      r" 2 files changed, 2 insertions\(\+\)",
      r" create mode 100644 B.txt",
      r" create mode 100644 C.txt",
      r"Switched to branch 'branch2'",
      r"Rebasing \(1/1\)",
      r"Successfully rebased and updated refs/heads/branch2.",
      r"Switched to branch 'branch4'",
      r"Rebasing \(1/1\)",
      r"Successfully rebased and updated refs/heads/branch4.",
      r"Switched to branch 'branch1'",
    ],
  )
  assert_graph(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (main)
    | |/
    | | *     D (branch2)
    | |/
    |/|
    * |       B and C (HEAD -> branch1)
    |/
    *         A
    """
  )


def test_squash_message2():
  """
  Description:
    `squash -m` is still refused when there are uncommitted changes.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(*squash_prep(now, sec), "echo 'changed' >> C.txt")
  run_test(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (main)
    | |/
    | | *     D (branch2)
    | | *     C (HEAD -> branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    "branches squash -m 'B and C'",
    [
      r"                                                ",
      r" Origin - Local  Age <- -> Branch  Base      PR ",
      r" ────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main                 ",
      r"          \w{5}    0  1 2  branch1              ",
      r"          \w{5}    0  1 3  branch2 branch1      ",
      r"          \w{5}    0  1 2  branch4 branch1~1    ",
      r"                                                ",
      r"Cannot run squash with uncommitted changes. Commit or stash them first.",
      r"",
    ],
    expected_returncode=1,
  )


def test_message_without_operation():
  """
  Description:
    -m is rejected without the amend or squash operation.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(*squash_prep(now, sec))
  run_test(
    r"""
    *         G (branch4)
    | *       F (branch3)
    | | *     E (main)
    | |/
    | | *     D (branch2)
    | | *     C (HEAD -> branch1)
    | |/
    |/|
    * |       B
    |/
    *         A
    """,
    "branches -m 'C2'",
    [],
    expected_returncode=2,
  )


def test_rebase_current1():
  """
  Description:
    Rebasing the current branch doesn't check it out first. Local main is ahead of origin/main, so
    there's no pull to move away from the current branch (#53).
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1),
    "git push -u origin main",
    commit("B", now + sec * 2),
    "git checkout -b next HEAD~1",
    commit("C", now + sec * 3),
    "git push -u origin next",
  )
  run_test(
    r"""
    *         C (HEAD -> next, origin/next)
    | *       B (main)
    |/
    *         A (origin/main)
    """,
    "branches",
    [
      r"                                          ",
      r" Origin - Local  Age <- -> Branch Base PR ",
      r" ──────────────────────────────────────── ",
      r"  \w{5} < \w{5}    0  0 0  main           ",
      r"  \w{5}   \w{5}    0  1 1  next           ",
      r"                                          ",
      r"git rebase main && git push -f",
      r"",
    ],
  )


def test_conflicts1():
  """
  Description:
    branch1 changes the same file as main does since branch1 branched off, so rebasing it would
    conflict, so it's not rebased. branch2 doesn't, so it is.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1, file="F"),
    "git checkout -b branch1",
    commit("B", now + sec * 2, file="F"),
    "git checkout -b branch2 main",
    commit("C", now + sec * 3),
    "git checkout main",
    commit("D", now + sec * 4, file="F"),
  )
  run_test(
    r"""
    *         D (HEAD -> main)
    | *       C (branch2)
    |/
    | *       B (branch1)
    |/
    *         A
    """,
    "branches",
    [
      r"                                            ",
      r" Origin - Local  Age <- ->  Branch  Base PR ",
      r" ────────────────────────────────────────── ",
      r"          \w{5}    0  0 0   main            ",
      r"          \w{5}    0  1 1   branch2         ",
      r"          \w{5}    0  1 1 C branch1         ",
      r"                                            ",
      r"git checkout branch2 && git rebase main && \\",
      r"git checkout main",
      r"",
    ],
  )


def test_conflicts2():
  """
  Description:
    origin/main changes the same file as branch1 does, and local main is behind. Conflicts are
    checked against origin/main, since main gets pulled before rebasing. branch1 is not rebased.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1, file="F"),
    commit("B", now + sec * 2, file="F"),
    "git push -u origin main",
    "git reset --hard HEAD~1",
    "git checkout -b branch1",
    commit("C", now + sec * 3, file="F"),
  )
  run_test(
    r"""
    *         C (HEAD -> branch1)
    | *       B (origin/main)
    |/
    *         A (main)
    """,
    "branches",
    [
      r"                                            ",
      r" Origin - Local  Age <- ->  Branch  Base PR ",
      r" ────────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0   main            ",
      r"          \w{5}    0  0 1 C branch1         ",
      r"                                            ",
      r"git checkout main && git pull && \\",
      r"git checkout branch1",
      r"",
    ],
  )


def test_conflicts3():
  """
  Description:
    Stacked branches. branch2 is stacked on branch1, which rebases cleanly onto main. branch2
    conflicts with main. branch4 is stacked on branch3, which conflicts with main, so branch4 is
    checked against branch3 as is, and doesn't conflict. Nothing is rebased: both stacks have a
    branch with conflicts, so rebasing branch1 would leave branch2 behind.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1, file="F"),
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    "git checkout -b branch2",
    commit("C", now + sec * 3, file="F"),
    "git checkout -b branch3 main",
    commit("D", now + sec * 4, file="F"),
    "git checkout -b branch4",
    commit("E", now + sec * 5),
    "git checkout main",
    commit("G", now + sec * 6, file="F"),
  )
  run_test(
    r"""
    *         G (HEAD -> main)
    | *       E (branch4)
    | *       D (branch3)
    |/
    | *       C (branch2)
    | *       B (branch1)
    |/
    *         A
    """,
    "branches",
    [
      r"                                               ",
      r" Origin - Local  Age <- ->  Branch  Base    PR ",
      r" ───────────────────────────────────────────── ",
      r"          \w{5}    0  0 0   main               ",
      r"          \w{5}    0  1 2   branch4 branch3    ",
      r"          \w{5}    0  1 1 C branch3            ",
      r"          \w{5}    0  1 2 C branch2 branch1    ",
      r"          \w{5}    0  1 1   branch1            ",
      r"                                               ",
    ],
  )


def test_conflicts4():
  """
  Description:
    branch2 and branch3 are stacked on branch1, and branch4 forks off branch1~1. branch2 conflicts
    with main, so none of them is rebased. branch5 is in its own stack, so it is.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1, file="F"),
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    commit("C", now + sec * 3),
    "git checkout -b branch2",
    commit("D", now + sec * 4, file="F"),
    "git checkout -b branch3 branch1",
    commit("E", now + sec * 5),
    "git checkout -b branch4 branch1~1",
    commit("G", now + sec * 6),
    "git checkout -b branch5 main",
    commit("H", now + sec * 7),
    "git checkout main",
    commit("I", now + sec * 8, file="F"),
  )
  run_test(
    r"""
    *         I (HEAD -> main)
    | *       H (branch5)
    |/
    | *       G (branch4)
    | | *     E (branch3)
    | | | *   D (branch2)
    | | |/
    | | *     C (branch1)
    | |/
    | *       B
    |/
    *         A
    """,
    "branches",
    [
      r"                                                 ",
      r" Origin - Local  Age <- ->  Branch  Base      PR ",
      r" ─────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0   main                 ",
      r"          \w{5}    0  1 1   branch5              ",
      r"          \w{5}    0  1 2   branch4 branch1~1    ",
      r"          \w{5}    0  1 3   branch3 branch1      ",
      r"          \w{5}    0  1 3 C branch2 branch1      ",
      r"          \w{5}    0  1 2   branch1              ",
      r"                                                 ",
      r"git checkout branch5 && git rebase main && \\",
      r"git checkout main",
      r"",
    ],
  )


def test_stack1():
  """
  Description:
    Same as test_conflicts4, but the current branch is branch3 and only its stack is shown. The
    stack is rebased even though branch2 has conflicts.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1, file="F"),
    "git checkout -b branch1",
    commit("B", now + sec * 2),
    commit("C", now + sec * 3),
    "git checkout -b branch2",
    commit("D", now + sec * 4, file="F"),
    "git checkout -b branch3 branch1",
    commit("E", now + sec * 5),
    "git checkout -b branch4 branch1~1",
    commit("G", now + sec * 6),
    "git checkout -b branch5 main",
    commit("H", now + sec * 7),
    "git checkout main",
    commit("I", now + sec * 8, file="F"),
    "git checkout branch3",
  )
  run_test(
    r"""
    *         I (main)
    | *       H (branch5)
    |/
    | *       G (branch4)
    | | *     E (HEAD -> branch3)
    | | | *   D (branch2)
    | | |/
    | | *     C (branch1)
    | |/
    | *       B
    |/
    *         A
    """,
    "branches -s",
    [
      r"                                                 ",
      r" Origin - Local  Age <- ->  Branch  Base      PR ",
      r" ─────────────────────────────────────────────── ",
      r"          \w{5}    0  0 0   main                 ",
      r"          \w{5}    0  1 3   branch3 branch1      ",
      r"          \w{5}    0  1 2   branch1              ",
      r"          \w{5}    0  1 3 C branch2 branch1      ",
      r"          \w{5}    0  1 2   branch4 branch1~1    ",
      r"                                                 ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch4 && git rebase --onto branch1~1 branch4~1 && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && \\",
      r"git checkout branch3 && git rebase --onto branch1 branch3~1",
      r"",
    ],
  )


def test_stack2(httpserver: HTTPServer):
  """
  Description:
    Same as test_locked7, but only the stack of the current branch is shown. The stack is rebased
    even though branch1 is locked. branch1 is not pushed, since it has a commit by another author.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(
    *locked_prep(now, sec),
    "git checkout -b branch2 branch1",
    commit("D", now + sec * 4),
    "git checkout -b branch3",
    commit("E", now + sec * 5),
  )
  set_mockserver_expectations(
    httpserver,
    other_author_pull_requests(
      ["main", "branch3", "branch2", "branch1"], {"branch1": {"state": "open"}}
    ),
  )
  run_test(
    r"""
    *         E (HEAD -> branch3)
    *         D (branch2)
    | *       C (origin/main, main)
    * |       B (origin/branch1, branch1)
    |/
    *         A
    """,
    "branches -s",
    [
      r"                                                                  ",
      r" Origin - Local  Age <- ->  Branch  Base    PR                    ",
      r" ──────────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0   main                                  ",
      r"          \w{5}!   0  1 3   branch3 branch2                       ",
      r"          \w{5}!   0  1 2   branch2 branch1                       ",
      r" !\w{5}   \w{5}!   0  1 1 L branch1         #1 \(\w{5}\) by someone ",
      r"                                                                  ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && \\",
      r"git checkout branch3 && git rebase --onto branch2 branch3~1",
      r"",
    ],
    httpserver=httpserver,
  )


def locked_conflicts_prep(now: datetime, sec: timedelta) -> list[str]:
  """Returns commands that create branch1, locked, with branch2 stacked on it, with conflicts

  branch1 has B by another author and C, and is in sync with origin. branch2 changes the same file
  as main does since branch1 branched off.
  """
  return [
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1, file="F"),
    "git push",
    "git checkout -b branch1",
    commit("B", now + sec * 2, "Name <me@git.com>"),
    commit("C", now + sec * 3),
    "git push",
    "git checkout -b branch2",
    commit("D", now + sec * 4, file="F"),
    "git checkout main",
    commit("E", now + sec * 5, file="F"),
    "git push",
  ]


def test_stack3(httpserver: HTTPServer):
  """
  Description:
    branch1 is locked and branch2, stacked on it, has conflicts. The stack is rebased anyway.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(*locked_conflicts_prep(now, sec), "git checkout branch2")
  set_mockserver_expectations(
    httpserver,
    other_author_pull_requests(["main", "branch2", "branch1"], {"branch1": {"state": "open"}}),
  )
  run_test(
    r"""
    *         E (origin/main, main)
    | *       D (HEAD -> branch2)
    | *       C (origin/branch1, branch1)
    | *       B
    |/
    *         A
    """,
    "branches -s",
    [
      r"                                                                  ",
      r" Origin - Local  Age <- ->  Branch  Base    PR                    ",
      r" ──────────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0   main                                  ",
      r"          \w{5}!   0  1 3 C branch2 branch1                       ",
      r" !\w{5}   \w{5}!   0  1 2 L branch1         #1 \(\w{5}\) by someone ",
      r"                                                                  ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1",
      r"",
    ],
    httpserver=httpserver,
  )


def test_stack4(httpserver: HTTPServer):
  """
  Description:
    Same as test_stack3, but amending branch1. Locks and conflicts don't apply to amend: branch1 is
    amended and branch2 is restacked on top of it. branch1 is not pushed, since it has a commit by
    another author.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(*locked_conflicts_prep(now, sec), "git checkout branch1", "echo 'X' > X.txt")
  set_mockserver_expectations(
    httpserver,
    other_author_pull_requests(["main", "branch1", "branch2"], {"branch1": {"state": "open"}}),
  )
  run_test(
    r"""
    *         E (origin/main, main)
    | *       D (branch2)
    | *       C (HEAD -> branch1, origin/branch1)
    | *       B
    |/
    *         A
    """,
    "branches amend",
    [
      r"                                                                  ",
      r" Origin - Local  Age <- ->  Branch  Base    PR                    ",
      r" ──────────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0   main                                  ",
      r" !\w{5}   \w{5}!   0  1 2 L branch1         #1 \(\w{5}\) by someone ",
      r"          \w{5}!   0  1 3 C branch2 branch1                       ",
      r"                                                                  ",
      r"git add -A && git commit --amend --no-edit && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && \\",
      r"git checkout branch1",
      r"",
    ],
    httpserver=httpserver,
  )


def test_stack5(httpserver: HTTPServer):
  """
  Description:
    Same as test_stack4, but squashing C into B on branch1.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_prep(*locked_conflicts_prep(now, sec), "git checkout branch1")
  set_mockserver_expectations(
    httpserver,
    other_author_pull_requests(["main", "branch1", "branch2"], {"branch1": {"state": "open"}}),
  )
  run_test(
    r"""
    *         E (origin/main, main)
    | *       D (branch2)
    | *       C (HEAD -> branch1, origin/branch1)
    | *       B
    |/
    *         A
    """,
    "branches squash",
    [
      r"                                                                  ",
      r" Origin - Local  Age <- ->  Branch  Base    PR                    ",
      r" ──────────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0   main                                  ",
      r" !\w{5}   \w{5}!   0  1 2 L branch1         #1 \(\w{5}\) by someone ",
      r"          \w{5}!   0  1 3 C branch2 branch1                       ",
      r"                                                                  ",
      r"git reset --soft HEAD~1 && git commit --amend --no-edit && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && \\",
      r"git checkout branch1",
      r"",
    ],
    httpserver=httpserver,
  )


def test_properties(httpserver: HTTPServer):
  """
  Description:
    One branch per combination of properties: M (merge commits), L (locked) and C (conflicts). The
    letters in each branch name are the properties it has. Every branch forks off main, so each is
    its own stack. M can't be combined with L: branches with merge commits don't track authors, so
    they're never locked.
  """
  now = datetime.now(UTC) - timedelta(hours=6)
  sec = timedelta(seconds=1)
  run_prep(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
    commit("A", now + sec * 1, file="F"),
    "git push",
    "git checkout -b branchM",
    commit("M2", now + sec * 2),
    "git checkout -b side main",
    commit("M3", now + sec * 3),
    "git checkout branchM",
    f"GIT_AUTHOR_DATE='{(now + sec * 4).isoformat()}' git merge --no-ff --no-edit side",
    "git branch -D side",
    "git checkout -b branchL main",
    commit("L1", now + sec * 5, "Name <me@git.com>"),
    commit("L2", now + sec * 6),
    "git push",
    "git checkout -b branchC main",
    commit("C2", now + sec * 7, file="F"),
    "git checkout -b branchMC main",
    commit("MC2", now + sec * 8, file="F"),
    "git checkout -b side main",
    commit("MC3", now + sec * 9),
    "git checkout branchMC",
    f"GIT_AUTHOR_DATE='{(now + sec * 10).isoformat()}' git merge --no-ff --no-edit side",
    "git branch -D side",
    "git checkout -b branchLC main",
    commit("LC1", now + sec * 11, "Name <me@git.com>"),
    commit("LC2", now + sec * 12, file="F"),
    "git push",
    "git checkout main",
    commit("B", now + sec * 13, file="F"),
    "git push",
  )
  set_mockserver_expectations(
    httpserver,
    other_author_pull_requests(
      ["main", "branchLC", "branchMC", "branchC", "branchL", "branchM"],
      {"branchLC": {"state": "open"}, "branchL": {"state": "open"}},
    ),
  )
  run_test(
    r"""
    *         B (HEAD -> main, origin/main)
    | *       LC2 (origin/branchLC, branchLC)
    | *       LC1
    |/
    | *       Merge branch 'side' into branchMC (branchMC)
    | |\
    | | *     MC3
    | |/
    |/|
    | *       MC2
    |/
    | *       C2 (branchC)
    |/
    | *       L2 (origin/branchL, branchL)
    | *       L1
    |/
    | *       Merge branch 'side' into branchM (branchM)
    | |\
    | | *     M3
    | |/
    |/|
    | *       M2
    |/
    *         A
    """,
    "branches",
    [
      r"                                                                 ",
      r" Origin - Local  Age <- ->   Branch   Base PR                    ",
      r" ─────────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0    main                                ",
      r" !\w{5}   \w{5}!   0  1 2 LC branchLC      #1 \(\w{5}\) by someone ",
      r"          \w{5}    0  1 3 MC branchMC                            ",
      r"          \w{5}    0  1 1 C  branchC                             ",
      r" !\w{5}   \w{5}!   0  1 2 L  branchL       #2 \(\w{5}\) by someone ",
      r"          \w{5}    0  1 3 M  branchM                             ",
      r"                                                                 ",
    ],
    httpserver=httpserver,
  )
