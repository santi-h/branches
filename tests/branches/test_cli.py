# Do not run these tests with the -s flag to pytest

import pytest
import os
import shutil
import subprocess
from pathlib import Path
from subprocess import CompletedProcess
import re
from datetime import datetime, timezone, timedelta
import json
from pytest_httpserver.httpserver import HTTPServer

GIT_TMP_DIRPATH_LOCAL = os.path.join(os.path.dirname(__file__), "test_cli_local")
GIT_TMP_DIRPATH_ORIGIN = os.path.join(os.path.dirname(__file__), "test_cli_origin")
SRC_DIRPATH = os.path.join(Path(__file__).resolve().parents[2], "src")


@pytest.fixture(autouse=True)
def around_each():
  shutil.rmtree(GIT_TMP_DIRPATH_ORIGIN, ignore_errors=True)
  shutil.rmtree(GIT_TMP_DIRPATH_LOCAL, ignore_errors=True)
  os.makedirs(GIT_TMP_DIRPATH_ORIGIN)
  os.makedirs(GIT_TMP_DIRPATH_LOCAL)
  run_command("git init --bare .", GIT_TMP_DIRPATH_ORIGIN)
  yield
  shutil.rmtree(GIT_TMP_DIRPATH_LOCAL, ignore_errors=True)
  shutil.rmtree(GIT_TMP_DIRPATH_ORIGIN, ignore_errors=True)


def run_command(command: str, dirpath: str = GIT_TMP_DIRPATH_LOCAL) -> CompletedProcess[str]:
  return subprocess.run(f"cd '{dirpath}' && {command}", shell=True, capture_output=True, text=True)


def run_test(
  prep_command: str | None,
  trigger_command: str,
  expected_stdout: str | list[str],
  expected_returncode=0,
  cleanup_command: str | None = None,
  httpserver: HTTPServer | None = None,
  trigger_command_dir: str | None = None,
):
  if len(prep_command or "") > 0:
    result = run_command(prep_command)
    assert result.returncode == 0, (
      f"Prep command output:\n{result.stdout}\nPrep command stderr:\n{result.stderr}"
    )

  envars = [f"PYTHONPATH='{SRC_DIRPATH}'"]
  if httpserver is not None:
    envars += [
      "GITHUB_PROTO='http'",
      f"GITHUB_DOMAIN='{httpserver.host}:{httpserver.port}'",
      "GITHUB_TOKEN='testtoken'",
    ]

  envars = " ".join(envars)
  print(envars)
  command = [f"cd '{GIT_TMP_DIRPATH_LOCAL}'"]
  if trigger_command_dir:
    command.append(f"cd {trigger_command_dir}")
  command.append(f"{envars} python -m {trigger_command}")

  result = subprocess.run(
    " && ".join(command),
    shell=True,
    capture_output=True,
    text=True,
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
    subprocess.run(f"cd '{GIT_TMP_DIRPATH_LOCAL}' && {cleanup_command}", shell=True)


def commit(name: str, date: datetime | None = None, author: str | None = None) -> str:
  ret = f"echo '{name}.txt' > {name}.txt && git add -A && git commit -m '{name}.txt'"

  if date:
    tformat = "%Y-%m-%dT%H:%M:%S%z"
    ret += f" --date='{date.strftime(tformat)}'"

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
  #       C     <- branch1
  #      /
  # A---B---D   <- main
  now = datetime.now(timezone.utc) - timedelta(hours=6)
  sec = timedelta(seconds=1)
  tformat = "%Y-%m-%dT%H:%M:%S%z"

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

  run_test(
    f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN} && "
    "echo 'A.txt' > A.txt && git add . && "
    f"git commit -m 'A' --date='{(now + sec * 1).strftime(tformat)}' && git push && "
    "echo 'B.txt' > B.txt && git add . && "
    f"git commit -m 'B' --date='{(now + sec * 2).strftime(tformat)}' && "
    "git checkout -b branch1 && "
    "echo 'C.txt' > C.txt && git add . && "
    f"git commit -m 'C' --date='{(now + sec * 3).strftime(tformat)}' && "
    "git checkout main && "
    "echo 'D.txt' > D.txt && git add . && "
    f"git commit -m 'D' --date='{(now + sec * 4).strftime(tformat)}' && git push",
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

  # If the PR is merged and the head sha of the PR is exactly the same as the local sha, suggest
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

  run_test(
    "git checkout branch1",
    "branches",
    [
      r"                                                                ",
      r" Origin - Local  Age <- -> Branch  Base PR                      ",
      r" ────────────────────────────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main                                 ",
      r"          \w{5}    0  1 1  branch1      #123 \(\w{5}\) by santi-h ",
      r"                                                                ",
      r"git checkout main && \\",
      r"git branch -D branch1 && \\",
      r"git checkout main",
      r"",
    ],
    httpserver=httpserver,
  )


def test_merged_base(httpserver: HTTPServer):
  """
  #     C <- branch2
  #    /
  #   B   <- branch1
  #  /
  # A---D <- main
  """
  now = datetime.now(timezone.utc) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_test(
    " && ".join(
      [
        f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
        commit("A", now + sec * 1),
        "git checkout -b branch1",
        commit("B", now + sec * 2),
        "git checkout -b branch2",
        commit("C", now + sec * 3),
        "git checkout main",
        commit("D", now + sec * 4),
        "git push",
      ]
    ),
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
    None,
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

  run_test(
    "git checkout branch2",
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
      r"git checkout branch2 && git rebase main && \\",
      r"git checkout main",
      r"",
    ],
    httpserver=httpserver,
  )


def test_cli_misc():
  #                 G      <- branch6
  #                /
  #               | H---I  <- branch5
  #               |/
  #               F        <- branch3, branch4
  #              /
  #         D---E          <- branch2
  #        /
  #       C---J            <- branch1, branch10
  #      /
  # A---B---K---L---M      <- *main
  #          \       \
  #           \       O    <- branch7
  #            \       \
  #             \       P  <- branch8
  #              \
  #               Q        <- branch9
  now = datetime.now(timezone.utc) - timedelta(hours=6)
  sec = timedelta(seconds=1)
  tformat = "%Y-%m-%dT%H:%M:%S%z"

  run_test(
    " && ".join(
      [
        f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
        "echo 'A.txt' > A.txt && git add .",
        f"git commit -m 'A' --date='{(now + sec * 1).strftime(tformat)}'",
        "echo 'B.txt' > B.txt && git add .",
        f"git commit -m 'B' --date='{(now + sec * 2).strftime(tformat)}'",
        "git checkout -b branch1",
        "echo 'C.txt' > C.txt && git add .",
        f"git commit -m 'C' --date='{(now + sec * 3).strftime(tformat)}' && git push",
        "git checkout -b branch2",
        "echo 'D.txt' > D.txt && git add .",
        f"git commit -m 'D' --date='{(now + sec * 4).strftime(tformat)}'",
        "echo 'E.txt' > E.txt && git add .",
        f"git commit -m 'E' --date='{(now + sec * 5).strftime(tformat)}'",
        "git checkout -b branch3",
        "echo 'F.txt' > F.txt && git add .",
        f"git commit -m 'F' --date='{(now + sec * 6).strftime(tformat)}' && git push",
        "git checkout -b branch4",
        "git checkout -b branch6",
        "echo 'G.txt' > G.txt && git add .",
        f"git commit -m 'G' --date='{(now + sec * 7).strftime(tformat)}'",
        "git checkout branch3",
        "git checkout -b branch5",
        "echo 'H.txt' > H.txt && git add .",
        f"git commit -m 'H' --date='{(now + sec * 8).strftime(tformat)}'",
        "echo 'I.txt' > I.txt && git add .",
        f"git commit -m 'I' --date='{(now + sec * 9).strftime(tformat)}'",
        "git checkout branch1",
        "echo 'J.txt' > J.txt && git add .",
        f"git commit -m 'J' --date='{(now + sec * 10).strftime(tformat)}'",
        "git checkout -b branch10",
        "git checkout main",
        "echo 'K.txt' > K.txt && git add .",
        f"git commit -m 'K' --date='{(now + sec * 11).strftime(tformat)}'",
        "echo 'L.txt' > L.txt && git add .",
        f"git commit -m 'L' --date='{(now + sec * 12).strftime(tformat)}'",
        "echo 'M.txt' > M.txt && git add .",
        f"git commit -m 'M' --date='{(now + sec * 13).strftime(tformat)}'",
        "git checkout -b branch7",
        "echo 'O.txt' > O.txt && git add .",
        f"git commit -m 'O' --date='{(now + sec * 14).strftime(tformat)}'",
        "git checkout -b branch8",
        "echo 'P.txt' > P.txt && git add .",
        f"git commit -m 'P' --date='{(now + sec * 15).strftime(tformat)}'",
        "git checkout main~2",
        "git checkout -b branch9",
        "echo 'Q.txt' > Q.txt && git add .",
        f"git commit -m 'Q' --date='{(now + sec * 16).strftime(tformat)}'",
        "git checkout main",
      ]
    ),
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
    None,
    "branches -s",
    [
      r"                                          ",
      r" Origin - Local  Age <- -> Branch Base PR ",
      r" ──────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main           ",
      r"                                          ",
    ],
  )

  run_test(
    "git checkout branch2",
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
      r"git checkout main",
      r"",
    ],
  )

  run_test(
    "git checkout branch2 && echo test >> E.txt && git add E.txt",
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

  run_test(
    "git checkout branch1",
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
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch10 && git reset --hard branch1 && \\",
      r"git checkout branch2 && git rebase --onto branch1~1 branch2~2 && \\",
      r"git checkout branch3 && git rebase --onto branch2 branch3~1 && git push -f && \\",
      r"git checkout branch4 && git reset --hard branch3 && \\",
      r"git checkout branch6 && git rebase --onto branch3 branch6~1 && \\",
      r"git checkout branch5 && git rebase --onto branch3 branch5~2 && \\",
      r"git checkout main",
      r"",
    ],
  )

  run_test(
    "git checkout branch1 && echo test >> J.txt && git add J.txt",
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

  run_test(
    "git checkout branch10",
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
      r"git checkout main",
      r"",
    ],
  )

  run_test(
    "git checkout branch9",
    "branches -s",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main            ",
      r"          \w{5}    0  2 1  branch9         ",
      r"                                           ",
      r"git checkout branch9 && git rebase main && \\",
      r"git checkout main",
      r"",
    ],
  )

  run_test(
    "git checkout branch9",
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

  run_test(
    "git checkout branch9 && echo test >> Q.txt && git add Q.txt",
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

  run_test(
    "git checkout branch9",
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

  run_test(
    "git checkout main && echo test >> A.txt && git add A.txt",
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

  run_test(
    "git reset HEAD && git checkout . && git checkout main",
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

  run_test(
    "git checkout main",
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
  run_test(
    " && ".join(
      [
        "git push",
        "echo test >> Q.txt && git add Q.txt",
        f"git commit -m 'Q' --date='{(now + sec * 17).strftime(tformat)}' --author='Name <me@git.com>'",
      ]
    ),
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
  run_test(
    "git push && git reset --hard HEAD~1",
    "branches -s",
    [
      r"                                          ",
      r" Origin - Local  Age <- -> Branch Base PR ",
      r" ──────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main           ",
      r"                                          ",
      r"git pull && \\",
      r"git checkout main",
      r"",
    ],
  )

  # When the remote `main` and local `main` deviated
  run_test(
    " && ".join(
      [
        "echo test >> Q.txt && git add Q.txt",
        f"git commit -m 'Q' --date='{(now + sec * 19).strftime(tformat)}'",
      ]
    ),
    "branches -s",
    [
      r"                                          ",
      r" Origin - Local  Age <- -> Branch Base PR ",
      r" ──────────────────────────────────────── ",
      r"  \w{5} Y \w{5}    0  0 0  main           ",
      r"                                          ",
    ],
  )


def test_cli_amend():
  #     C---D <- branch2
  #    /
  #   B       <- branch1
  #  /
  # A         <- main
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

  now = datetime.now(timezone.utc) - timedelta(hours=6)
  sec = timedelta(seconds=1)
  tformat = "%Y-%m-%dT%H:%M:%S%z"

  run_test(
    " && ".join(
      [
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
      ]
    ),
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

  run_test(
    f'echo "{file_content_b_new}" > testfile.txt',
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
    None,
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

  run_test(
    "git checkout branch1 && git push && echo 'new file' > testnewfile.txt",
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

  run_test(
    "git checkout branch2 && git push && echo 'file5' > file5.txt",
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
    None,
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

  run_test(
    "git checkout branch1 && git push && echo 'file5' > file5.txt",
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
  #     D     <- branch2
  #    /
  #   C       <- branch1
  #  /
  # A---B     <- main
  now = datetime.now(timezone.utc) - timedelta(hours=6)
  sec = timedelta(seconds=1)
  tformat = "%Y-%m-%dT%H:%M:%S%z"

  run_test(
    " && ".join(
      [
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
      ]
    ),
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

  run_test(
    "echo 'newline' >> A.txt",
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

  run_test(
    "echo 'newline' >> A.txt",
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


def test_authors():
  #   C       <- branch1
  #  /
  # A---B     <- main
  now = datetime.now(timezone.utc) - timedelta(hours=6)
  sec = timedelta(seconds=1)
  tformat = "%Y-%m-%dT%H:%M:%S%z"

  # Local branch has commits by a different author
  run_test(
    " && ".join(
      [
        f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
        "echo 'A.txt' > A.txt && git add .",
        f"git commit -m 'A.txt' --date='{(now + sec * 1).strftime(tformat)}'",
        "echo 'B.txt' > B.txt && git add .",
        f"git commit -m 'B.txt' --date='{(now + sec * 2).strftime(tformat)}'",
        "git checkout -b branch1",
        "echo 'C.txt' > C.txt && git add .",
        f"git commit -m 'C.txt' --date='{(now + sec * 3).strftime(tformat)}' --author='Name <me@git.com>'",
      ]
    ),
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

  # Remote and local branch have commits by a different author
  run_test(
    "git push",
    "branches",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main            ",
      r" !\w{5}   \w{5}!   0  0 1  branch1         ",
      r"                                           ",
    ],
    expected_returncode=0,
  )

  # Remote branch has commits by a different author
  git_name = run_command("git config --get user.name").stdout.strip()
  git_email = run_command("git config --get user.email").stdout.strip()
  run_test(
    f"git commit --amend --author='{git_name} <{git_email}>' --no-edit",
    "branches",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"          \w{5}    0  0 0  main            ",
      r" !\w{5} Y \w{5}    0  0 1  branch1         ",
      r"                                           ",
    ],
    expected_returncode=0,
  )


def test_pulls1():
  """
        E   <- origin/branch2, branch3, origin/branch3
       /
      D     <- origin/branch1, branch2
     /
    C       <- branch1
   /
  A---B     <- main
  """
  now = datetime.now(timezone.utc) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_test(
    " && ".join(
      [
        f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
        commit("A", now + sec * 1),
        commit("B", now + sec * 2),
        "git push",
        "git checkout -b branch1 head~1",
        commit("C", now + sec * 3),
        commit("D", now + sec * 4),
        "git push",
        "git checkout -b branch2",
        commit("E", now + sec * 5),
        "git checkout -b branch3 && git push",
        "git checkout branch2 && git push && git reset --hard head~1",
        "git checkout branch1 && git reset --hard head~1",
      ]
    ),
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
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch2 && git rebase --onto branch1 branch2~1 && \\",
      r"git checkout branch3 && git reset --hard branch2 && git push -f && \\",
      r"git checkout main",
      r"",
    ],
  )


def test_pulls2():
  """
        E   <- branch3, origin/branch3
       /
      D     <- origin/branch1, origin/branch2, branch2
     /
    C       <- branch1
   /
  A---B     <- main
  """
  now = datetime.now(timezone.utc) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_test(
    " && ".join(
      [
        f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
        commit("A", now + sec * 1),
        commit("B", now + sec * 2),
        "git push",
        "git checkout -b branch1 head~1",
        commit("C", now + sec * 3),
        commit("D", now + sec * 4),
        "git push",
        "git checkout -b branch2 && git push",
        "git checkout -b branch3",
        commit("E", now + sec * 5),
        "git push",
        "git checkout branch1 && git reset --hard head~1",
      ]
    ),
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
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch2 && git reset --hard branch1 && git push -f && \\",
      r"git checkout branch3 && git rebase --onto branch1 branch3~1 && git push -f && \\",
      r"git checkout main",
      r"",
    ],
  )


def test_pulls3():
  """
        E   <- branch3, origin/branch3, origin/branch1
       /
      D     <- origin/branch2, branch2
     /
    C       <- branch1
   /
  A---B     <- main
  """
  now = datetime.now(timezone.utc) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_test(
    " && ".join(
      [
        f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
        commit("A", now + sec * 1),
        commit("B", now + sec * 2),
        "git push",
        "git checkout -b branch1 head~1",
        commit("C", now + sec * 3),
        commit("D", now + sec * 4),
        commit("E", now + sec * 5),
        "git push",
        "git checkout -b branch3 && git push",
        "git checkout -b branch2 head~1 && git push",
        "git checkout branch1 && git reset --hard head~2",
      ]
    ),
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
      r"git checkout branch1 && git rebase --onto branch2 branch1~1 && \\",
      r"git checkout branch3 && git reset --hard branch1 && git push -f && \\",
      r"git checkout main",
      r"",
    ],
  )


def test_pulls4():
  """
        C    <- origin/main, origin/branch1
       /
  A---B     <- main, branch1
  """
  now = datetime.now(timezone.utc) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_test(
    " && ".join(
      [
        f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
        commit("A", now + sec * 1),
        commit("B", now + sec * 2),
        commit("C", now + sec * 3),
        "git push",
        "git checkout -b branch1 && git push && git reset --hard head~1",
        "git checkout main && git reset --hard head~1",
      ]
    ),
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
          D  <- origin/branch1
         /
        C    <- origin/main
       /
  A---B      <- main, branch1
  """
  now = datetime.now(timezone.utc) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_test(
    " && ".join(
      [
        f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
        commit("A", now + sec * 1),
        commit("B", now + sec * 2),
        commit("C", now + sec * 3),
        "git push",
        commit("D", now + sec * 4),
        "git checkout -b branch1 && git push && git reset --hard head~2",
        "git checkout main && git reset --hard head~2",
      ]
    ),
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
          D  <- origin/main
         /
        C    <- origin/branch1
       /
  A---B      <- main, branch1
  """
  now = datetime.now(timezone.utc) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_test(
    " && ".join(
      [
        f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
        commit("A", now + sec * 1),
        commit("B", now + sec * 2),
        commit("C", now + sec * 3),
        commit("D", now + sec * 4),
        "git push",
        "git checkout -b branch1 head~1 && git push && git reset --hard head~1",
        "git checkout main && git reset --hard head~2",
      ]
    ),
    "branches",
    [
      # Undesired behavior
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"  \w{5} > \w{5}    0  0 0  main            ",
      r"  \w{5} > \w{5}    0  0 0  branch1         ",
      r"                                           ",
      r"git pull && \\",
      r"git checkout branch1 && git pull && \\",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout main",
      r"",
    ],
  )


def test_pulls7():
  """
  Setup:

        D  <- branch2, origin/branch1
       /
      C    <- branch1
     /
    A---B  <- main
  """
  now = datetime.now(timezone.utc) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_test(
    " && ".join(
      [
        f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
        commit("A", now + sec * 1),
        commit("B", now + sec * 2),
        "git push",
        "git checkout -b branch1 head~1",
        commit("C", now + sec * 3),
        commit("D", now + sec * 4),
        "git push",
        "git checkout -b branch2",
        "git checkout branch1 && git reset --hard head~1",
        "echo 'change' >> C.txt",
      ]
    ),
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

  Setup:

        D  <- !origin/branch1
       /
      C    <- branch1
     /
    A---B  <- main
  """
  now = datetime.now(timezone.utc) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_test(
    " && ".join(
      [
        f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
        commit("A", now + sec * 1),
        commit("B", now + sec * 2),
        "git push",
        "git checkout -b branch1 head~1",
        commit("C", now + sec * 3),
        commit("D", now + sec * 4, 'Name <me@git.com>'),
        "git push",
        "git reset --hard head~1",
      ]
    ),
    "branches",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"  \w{5}   \w{5}    0  0 0  main            ",
      r" !\w{5} > \w{5}    0  1 1  branch1         ",
      r"                                           ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout main",
      r"",
    ],
  )


def test_pull_amend_base():
  """
        E   <- origin/branch2, branch3, origin/branch3
       /
      D     <- origin/branch1, branch2
     /
    C       <- branch1
   /
  A---B     <- main
  """
  now = datetime.now(timezone.utc) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_test(
    " && ".join(
      [
        f"git init && git remote add origin {GIT_TMP_DIRPATH_ORIGIN}",
        commit("A", now + sec * 1),
        commit("B", now + sec * 2),
        "git push",
        "git checkout -b branch1 head~1",
        commit("C", now + sec * 3),
        commit("D", now + sec * 4),
        "git push",
        "git checkout -b branch2",
        commit("E", now + sec * 5),
        "git checkout -b branch3 && git push",
        "git checkout branch2 && git push && git reset --hard head~1",
        "git checkout branch1 && git reset --hard head~1",
        "echo 'change' >> C.txt",
      ]
    ),
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

  Setup:

    A---B  <- branch1
  """
  now = datetime.now(timezone.utc) - timedelta(hours=6)
  sec = timedelta(seconds=1)

  run_test(
    " && ".join(
      [
        f"git init && git checkout -b branch1",
        commit("A", now + sec * 1),
        commit("B", now + sec * 2),
      ]
    ),
    "branches",
    [
      r"                                           ",
      r" Origin - Local  Age <- -> Branch  Base PR ",
      r" ───────────────────────────────────────── ",
      r"          \w{5}    0  0 0  branch1         ",
      r"                                           ",
    ],
  )

  run_test(
    " && ".join(
      [
        f"git checkout -b branch2",
        commit("C", now + sec * 3),
      ]
    ),
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
