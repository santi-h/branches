# Do not run these tests with the -s flag to pytest

import pytest
import os
import shutil
import subprocess
from pathlib import Path
from subprocess import CompletedProcess
import re
from datetime import datetime, timezone, timedelta

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
):
  if len(prep_command or "") > 0:
    result = run_command(prep_command)
    assert result.returncode == 0, (
      f"Prep command output:\n{result.stdout}\nPrep command stderr:\n{result.stderr}"
    )

  result = subprocess.run(
    f"cd '{GIT_TMP_DIRPATH_LOCAL}' && PYTHONPATH='{SRC_DIRPATH}' python -m {trigger_command}",
    shell=True,
    capture_output=True,
    text=True,
  )

  if "SAVE_CLI_RESULT" in os.environ:
    with open(os.path.join(os.path.dirname(__file__), "test_cli_result.txt"), "w") as result_file:
      result_file.write(result.stdout)

  assert result.returncode == expected_returncode, f"Full output:\n{result.stdout}"

  result_lines = result.stdout.splitlines()

  if isinstance(expected_stdout, str):
    expected_stdout = expected_stdout.splitlines()

  assert len(result_lines) == len(expected_stdout), f"Full output:\n{result.stdout}"
  for idx, (result_line, expected_line) in enumerate(zip(result_lines, expected_stdout)):
    assert re.fullmatch(expected_line, result_line), (
      f"Line {idx + 1}\n"
      f"Expected:\n{expected_line!r}\n"
      f"Got:\n{result_line!r}\n"
      f"Full output:\n{result.stdout}"
    )

  if len(cleanup_command or "") > 0:
    subprocess.run(f"cd '{GIT_TMP_DIRPATH_LOCAL}' && {cleanup_command}", shell=True)


def test_cli():
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
      r"                                                               ",
      r"  Origin   Local    Age   <-   ->   Branch     Base        PR  ",
      r" ───────────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                       ",
      r"           \w{5}      0    2   1    branch9                    ",
      r"           \w{5}      0    0   2    branch8    branch7         ",
      r"           \w{5}      0    0   1    branch7                    ",
      r"   \w{5}   \w{5}      0    3   2    branch1                    ",
      r"           \w{5}      0    3   2    branch10   branch1         ",
      r"           \w{5}      0    3   6    branch5    branch3         ",
      r"           \w{5}      0    3   5    branch6    branch3         ",
      r"   \w{5}   \w{5}      0    3   4    branch3    branch2         ",
      r"           \w{5}      0    3   4    branch4    branch3         ",
      r"           \w{5}      0    3   3    branch2    branch1~1       ",
      r"                                                               ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch10 && git rebase branch1 && \\",
      r"git checkout branch2 && git rebase branch1~1 && \\",
      r"git checkout branch3 && git rebase branch2 && git push -f && \\",
      r"git checkout branch4 && git rebase branch3 && \\",
      r"git checkout branch6 && git rebase branch3 && \\",
      r"git checkout branch5 && git rebase branch3 && \\",
      r"git checkout branch9 && git rebase main && \\",
      r"git checkout main",
      r"",
    ],
  )

  run_test(
    None,
    "branches -s",
    [
      r"                                                        ",
      r"  Origin   Local    Age   <-   ->   Branch   Base   PR  ",
      r" ────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                ",
      r"                                                        ",
    ],
  )

  run_test(
    "git checkout branch2",
    "branches -s",
    [
      r"                                                               ",
      r"  Origin   Local    Age   <-   ->   Branch     Base        PR  ",
      r" ───────────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                       ",
      r"           \w{5}      0    3   3    branch2    branch1~1       ",
      r"   \w{5}   \w{5}      0    3   2    branch1                    ",
      r"   \w{5}   \w{5}      0    3   4    branch3    branch2         ",
      r"           \w{5}      0    3   4    branch4    branch3         ",
      r"           \w{5}      0    3   5    branch6    branch3         ",
      r"           \w{5}      0    3   6    branch5    branch3         ",
      r"           \w{5}      0    3   2    branch10   branch1         ",
      r"                                                               ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch10 && git rebase branch1 && \\",
      r"git checkout branch2 && git rebase branch1~1 && \\",
      r"git checkout branch3 && git rebase branch2 && git push -f && \\",
      r"git checkout branch4 && git rebase branch3 && \\",
      r"git checkout branch6 && git rebase branch3 && \\",
      r"git checkout branch5 && git rebase branch3 && \\",
      r"git checkout main",
      r"",
    ],
  )

  run_test(
    "git checkout branch1",
    "branches -s",
    [
      r"                                                               ",
      r"  Origin   Local    Age   <-   ->   Branch     Base        PR  ",
      r" ───────────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                       ",
      r"   \w{5}   \w{5}      0    3   2    branch1                    ",
      r"           \w{5}      0    3   2    branch10   branch1         ",
      r"           \w{5}      0    3   3    branch2    branch1~1       ",
      r"   \w{5}   \w{5}      0    3   4    branch3    branch2         ",
      r"           \w{5}      0    3   4    branch4    branch3         ",
      r"           \w{5}      0    3   5    branch6    branch3         ",
      r"           \w{5}      0    3   6    branch5    branch3         ",
      r"                                                               ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch10 && git rebase branch1 && \\",
      r"git checkout branch2 && git rebase branch1~1 && \\",
      r"git checkout branch3 && git rebase branch2 && git push -f && \\",
      r"git checkout branch4 && git rebase branch3 && \\",
      r"git checkout branch6 && git rebase branch3 && \\",
      r"git checkout branch5 && git rebase branch3 && \\",
      r"git checkout main",
      r"",
    ],
  )

  run_test(
    "git checkout branch10",
    "branches -s",
    [
      r"                                                               ",
      r"  Origin   Local    Age   <-   ->   Branch     Base        PR  ",
      r" ───────────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                       ",
      r"           \w{5}      0    3   2    branch10   branch1         ",
      r"   \w{5}   \w{5}      0    3   2    branch1                    ",
      r"           \w{5}      0    3   3    branch2    branch1~1       ",
      r"   \w{5}   \w{5}      0    3   4    branch3    branch2         ",
      r"           \w{5}      0    3   4    branch4    branch3         ",
      r"           \w{5}      0    3   5    branch6    branch3         ",
      r"           \w{5}      0    3   6    branch5    branch3         ",
      r"                                                               ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch10 && git rebase branch1 && \\",
      r"git checkout branch2 && git rebase branch1~1 && \\",
      r"git checkout branch3 && git rebase branch2 && git push -f && \\",
      r"git checkout branch4 && git rebase branch3 && \\",
      r"git checkout branch6 && git rebase branch3 && \\",
      r"git checkout branch5 && git rebase branch3 && \\",
      r"git checkout main",
      r"",
    ],
  )

  run_test(
    "git checkout branch9",
    "branches -s",
    [
      r"                                                         ",
      r"  Origin   Local    Age   <-   ->   Branch    Base   PR  ",
      r" ─────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                 ",
      r"           \w{5}      0    2   1    branch9              ",
      r"                                                         ",
      r"git checkout branch9 && git rebase main && \\",
      r"git checkout main",
      r"",
    ],
  )
