# Do not run these tests with the -s flag to pytest
# The sleep commands are annoying but needed to ensure the branch order is deterministic.
# This is an improvement opportunity.

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

def run_test(prep_command: str, trigger_command: str, expected_lines: list[str]):
  subprocess.run(
    f"cd '{GIT_TMP_DIRPATH}' && {prep_command}",
    shell=True
  )

  result = subprocess.run(
    f"cd '{GIT_TMP_DIRPATH}' && PYTHONPATH='{SRC_DIRPATH}' {trigger_command}",
    shell=True,
    capture_output=True,
    text=True,
  )

  assert(result.returncode == 0), f"Full output:\n{result.stdout}"

  result_lines = result.stdout.splitlines()

  assert(len(result_lines) == len(expected_lines))
  for idx, (result_line, expected_line) in enumerate(zip(result_lines, expected_lines)):
    assert(re.fullmatch(expected_line, result_line)), \
      f"Line {idx+1}\n" \
      f"Expected:\n{expected_line!r}\n" \
      f"Got:\n{result_line!r}\n" \
      f"Full output:\n{result.stdout}"

def test_cli():
  #                 G      <- branch6
  #                /
  #               | H---I  <- branch5
  #               |/
  #               F        <- branch3, branch4
  #              /
  #         D---E          <- branch2
  #        /
  #       C---J            <- branch1
  #      /
  # A---B---K---L---M      <- *main
  run_test(
    f"git init && " \
    "echo 'A.txt' > A.txt && git add . && git commit -m 'A' && sleep 1.5 && " \
    "echo 'B.txt' > B.txt && git add . && git commit -m 'B' && sleep 1.5 && " \
    "git checkout -b branch1 && " \
    "echo 'C.txt' > C.txt && git add . && git commit -m 'C' && sleep 1.5 && " \
    "git checkout -b branch2 && " \
    "echo 'D.txt' > D.txt && git add . && git commit -m 'D' && sleep 1.5 && " \
    "echo 'E.txt' > E.txt && git add . && git commit -m 'E' && sleep 1.5 && " \
    "git checkout -b branch3 && " \
    "echo 'F.txt' > F.txt && git add . && git commit -m 'F' && sleep 1.5 && " \
    "git checkout -b branch4 && " \
    "git checkout -b branch6 && " \
    "echo 'G.txt' > G.txt && git add . && git commit -m 'G' && sleep 1.5 && " \
    "git checkout branch3 && " \
    "git checkout -b branch5 && " \
    "echo 'H.txt' > H.txt && git add . && git commit -m 'H' && sleep 1.5 && " \
    "echo 'I.txt' > I.txt && git add . && git commit -m 'I' && sleep 1.5 && " \
    "git checkout branch1 && " \
    "echo 'J.txt' > J.txt && git add . && git commit -m 'J' && sleep 1.5 && " \
    "git checkout main && " \
    "echo 'K.txt' > K.txt && git add . && git commit -m 'K' && sleep 1.5 && " \
    "echo 'L.txt' > L.txt && git add . && git commit -m 'L' && sleep 1.5 && " \
    "echo 'M.txt' > M.txt && git add . && git commit -m 'M' && sleep 1.5",
    f"python -m branches",
    [
      r"                                                              ",
      r"  Origin   Local    Age   <-   ->   Branch    Base        PR  ",
      r" ─* ",
      r"           \w{5}      0    0   0    main                      ",
      r"           \w{5}      0    3   2    branch1                   ",
      r"           \w{5}      0    3   6    branch5   branch3         ",
      r"           \w{5}      0    3   5    branch6   branch3         ",
      r"           \w{5}      0    3   4    branch3   branch2         ",
      r"           \w{5}      0    3   4    branch4   branch3         ",
      r"           \w{5}      0    3   3    branch2   branch1~1       ",
      r"                                                              ",
      r"git checkout branch1 && git rebase main && \\",
      r"git checkout branch2 && git rebase branch1~1 && \\",
      r"git checkout branch3 && git rebase branch2 && \\",
      r"git checkout branch4 && git rebase branch3 && \\",
      r"git checkout branch6 && git rebase branch3 && \\",
      r"git checkout branch5 && git rebase branch3 && \\",
      r"git checkout main",
      r"",
    ]
  )
