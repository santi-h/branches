# Do not run these tests with the -s flag to pytest

import pytest
import os
import shutil
import subprocess
from pathlib import Path
import re

GIT_TMP_DIRPATH = os.path.join(os.path.dirname(__file__), "test_cli")
SRC_DIRPATH = os.path.join(Path(__file__).resolve().parents[2], "src")


@pytest.fixture(autouse=True)
def around_each():
  shutil.rmtree(GIT_TMP_DIRPATH, ignore_errors=True)
  os.makedirs(GIT_TMP_DIRPATH)
  yield
  shutil.rmtree(GIT_TMP_DIRPATH, ignore_errors=True)


def run_test(
  prep_command: str | None,
  trigger_command: str,
  expected_stdout: str | list[str],
  expected_returncode=0,
  cleanup_command: str | None = None,
):
  if len(prep_command or "") > 0:
    subprocess.run(f"cd '{GIT_TMP_DIRPATH}' && {prep_command}", shell=True)

  result = subprocess.run(
    f"cd '{GIT_TMP_DIRPATH}' && PYTHONPATH='{SRC_DIRPATH}' {trigger_command}",
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
    subprocess.run(f"cd '{GIT_TMP_DIRPATH}' && {cleanup_command}", shell=True)


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
  prep_command = " && ".join(
    [
      "git init",
      "echo 'A.txt' > A.txt && git add . && git commit -m 'A' --date='2026-01-31T18:13:29-0500'",
      "echo 'B.txt' > B.txt && git add . && git commit -m 'B' --date='2026-01-31T18:13:30-0500'",
      "git checkout -b branch1",
      "echo 'C.txt' > C.txt && git add . && git commit -m 'C' --date='2026-01-31T18:13:31-0500'",
      "git checkout -b branch2",
      "echo 'D.txt' > D.txt && git add . && git commit -m 'D' --date='2026-01-31T18:13:32-0500'",
      "echo 'E.txt' > E.txt && git add . && git commit -m 'E' --date='2026-01-31T18:13:33-0500'",
      "git checkout -b branch3",
      "echo 'F.txt' > F.txt && git add . && git commit -m 'F' --date='2026-01-31T18:13:34-0500'",
      "git checkout -b branch4",
      "git checkout -b branch6",
      "echo 'G.txt' > G.txt && git add . && git commit -m 'G' --date='2026-01-31T18:13:35-0500'",
      "git checkout branch3",
      "git checkout -b branch5",
      "echo 'H.txt' > H.txt && git add . && git commit -m 'H' --date='2026-01-31T18:13:36-0500'",
      "echo 'I.txt' > I.txt && git add . && git commit -m 'I' --date='2026-01-31T18:13:37-0500'",
      "git checkout branch1",
      "echo 'J.txt' > J.txt && git add . && git commit -m 'J' --date='2026-01-31T18:13:38-0500'",
      "git checkout -b branch10",
      "git checkout main",
      "echo 'K.txt' > K.txt && git add . && git commit -m 'K' --date='2026-01-31T18:13:39-0500'",
      "echo 'L.txt' > L.txt && git add . && git commit -m 'L' --date='2026-01-31T18:13:40-0500'",
      "echo 'M.txt' > M.txt && git add . && git commit -m 'M' --date='2026-01-31T18:13:41-0500'",
      "git checkout -b branch7",
      "echo 'O.txt' > O.txt && git add . && git commit -m 'O' --date='2026-01-31T18:13:42-0500'",
      "git checkout -b branch8",
      "echo 'P.txt' > P.txt && git add . && git commit -m 'P' --date='2026-01-31T18:13:43-0500'",
      "git checkout main~2",
      "git checkout -b branch9",
      "echo 'Q.txt' > Q.txt && git add . && git commit -m 'Q' --date='2026-01-31T18:13:44-0500'",
      "git checkout main",
    ]
  )

  run_test(
    prep_command,
    "python -m branches",
    [
      r"                                                               ",
      r"  Origin   Local    Age   <-   ->   Branch     Base        PR  ",
      r" ───────────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                       ",
      r"           \w{5}      0    2   1    branch9                    ",
      r"           \w{5}      0    0   2    branch8    branch7         ",
      r"           \w{5}      0    0   1    branch7                    ",
      r"           \w{5}      0    3   2    branch1                    ",
      r"           \w{5}      0    3   2    branch10   branch1         ",
      r"           \w{5}      0    3   6    branch5    branch3         ",
      r"           \w{5}      0    3   5    branch6    branch3         ",
      r"           \w{5}      0    3   4    branch3    branch2         ",
      r"           \w{5}      0    3   4    branch4    branch3         ",
      r"           \w{5}      0    3   3    branch2    branch1~1       ",
      r"                                                               ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch10 && git rebase branch1 && \\",
      r"git checkout branch2 && git rebase branch1~1 && \\",
      r"git checkout branch3 && git rebase branch2 && \\",
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
    "python -m branches -s",
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
    "python -m branches -s",
    [
      r"                                                               ",
      r"  Origin   Local    Age   <-   ->   Branch     Base        PR  ",
      r" ───────────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                       ",
      r"           \w{5}      0    3   3    branch2    branch1~1       ",
      r"           \w{5}      0    3   2    branch1                    ",
      r"           \w{5}      0    3   4    branch3    branch2         ",
      r"           \w{5}      0    3   4    branch4    branch3         ",
      r"           \w{5}      0    3   5    branch6    branch3         ",
      r"           \w{5}      0    3   6    branch5    branch3         ",
      r"           \w{5}      0    3   2    branch10   branch1         ",
      r"                                                               ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch10 && git rebase branch1 && \\",
      r"git checkout branch2 && git rebase branch1~1 && \\",
      r"git checkout branch3 && git rebase branch2 && \\",
      r"git checkout branch4 && git rebase branch3 && \\",
      r"git checkout branch6 && git rebase branch3 && \\",
      r"git checkout branch5 && git rebase branch3 && \\",
      r"git checkout main",
      r"",
    ],
  )

  run_test(
    "git checkout branch1",
    "python -m branches -s",
    [
      r"                                                               ",
      r"  Origin   Local    Age   <-   ->   Branch     Base        PR  ",
      r" ───────────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                       ",
      r"           \w{5}      0    3   2    branch1                    ",
      r"           \w{5}      0    3   2    branch10   branch1         ",
      r"           \w{5}      0    3   3    branch2    branch1~1       ",
      r"           \w{5}      0    3   4    branch3    branch2         ",
      r"           \w{5}      0    3   4    branch4    branch3         ",
      r"           \w{5}      0    3   5    branch6    branch3         ",
      r"           \w{5}      0    3   6    branch5    branch3         ",
      r"                                                               ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch10 && git rebase branch1 && \\",
      r"git checkout branch2 && git rebase branch1~1 && \\",
      r"git checkout branch3 && git rebase branch2 && \\",
      r"git checkout branch4 && git rebase branch3 && \\",
      r"git checkout branch6 && git rebase branch3 && \\",
      r"git checkout branch5 && git rebase branch3 && \\",
      r"git checkout main",
      r"",
    ],
  )

  run_test(
    "git checkout branch10",
    "python -m branches -s",
    [
      r"                                                               ",
      r"  Origin   Local    Age   <-   ->   Branch     Base        PR  ",
      r" ───────────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                       ",
      r"           \w{5}      0    3   2    branch10   branch1         ",
      r"           \w{5}      0    3   2    branch1                    ",
      r"           \w{5}      0    3   3    branch2    branch1~1       ",
      r"           \w{5}      0    3   4    branch3    branch2         ",
      r"           \w{5}      0    3   4    branch4    branch3         ",
      r"           \w{5}      0    3   5    branch6    branch3         ",
      r"           \w{5}      0    3   6    branch5    branch3         ",
      r"                                                               ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch10 && git rebase branch1 && \\",
      r"git checkout branch2 && git rebase branch1~1 && \\",
      r"git checkout branch3 && git rebase branch2 && \\",
      r"git checkout branch4 && git rebase branch3 && \\",
      r"git checkout branch6 && git rebase branch3 && \\",
      r"git checkout branch5 && git rebase branch3 && \\",
      r"git checkout main",
      r"",
    ],
  )

  run_test(
    "git checkout branch9",
    "python -m branches -s",
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
