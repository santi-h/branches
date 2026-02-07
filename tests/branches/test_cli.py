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
      r"git add . && git commit --amend --no-edit && \\",
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
      r"git add . && git commit --amend --no-edit && \\",
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

  run_test(
    "git checkout branch9 && echo test >> Q.txt && git add Q.txt",
    "branches amend",
    [
      r"                                                         ",
      r"  Origin   Local    Age   <-   ->   Branch    Base   PR  ",
      r" ─────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                 ",
      r"           \w{5}      0    2   1    branch9              ",
      r"                                                         ",
      r"git add . && git commit --amend --no-edit",
      r"",
    ],
    cleanup_command="git reset HEAD && git checkout .",
  )

  run_test(
    "git checkout branch9",
    "branches amend",
    [
      r"                                                         ",
      r"  Origin   Local    Age   <-   ->   Branch    Base   PR  ",
      r" ─────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                 ",
      r"           \w{5}      0    2   1    branch9              ",
      r"                                                         ",
      r"No changes to amend with.",
      r"",
    ],
    expected_returncode=1,
  )

  run_test(
    "git checkout main && echo test >> A.txt && git add A.txt",
    "branches amend",
    [
      r"                                                        ",
      r"  Origin   Local    Age   <-   ->   Branch   Base   PR  ",
      r" ────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                ",
      r"                                                        ",
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
      r"                                                               ",
      r"  Origin   Local    Age   <-   ->   Branch     Base        PR  ",
      r" ───────────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                       ",
      r"           \w{5}      0    0   1    branch9                    ",
      r"           \w{5}      0    0   2    branch8    branch7         ",
      r"           \w{5}      0    0   1    branch7                    ",
      r"   \w{5}   \w{5}      0    0   2    branch1                    ",
      r"           \w{5}      0    0   2    branch10   branch1         ",
      r"           \w{5}      0    0   6    branch5    branch3         ",
      r"           \w{5}      0    0   5    branch6    branch3         ",
      r"   \w{5}   \w{5}      0    0   4    branch3    branch2         ",
      r"           \w{5}      0    0   4    branch4    branch3         ",
      r"           \w{5}      0    0   3    branch2    branch1~1       ",
      r"                                                               ",
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
      r"                                                            ",
      r"  Origin   Local    Age   <-   ->   Branch    Base      PR  ",
      r" ────────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                    ",
      r"           \w{5}      0    0   1    branch1                 ",
      r"           \w{5}      0    0   3    branch2   branch1       ",
      r"                                                            ",
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
      r"                                                            ",
      r"  Origin   Local    Age   <-   ->   Branch    Base      PR  ",
      r" ────────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                    ",
      r"           \w{5}      0    0   1    branch1                 ",
      r"           \w{5}      0    0   3    branch2   branch1       ",
      r"                                                            ",
      r"git add . && git commit --amend --no-edit && \\",
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
      r"                                                            ",
      r"  Origin   Local    Age   <-   ->   Branch    Base      PR  ",
      r" ────────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                    ",
      r"           \w{5}      0    0   1    branch1                 ",
      r"           \w{5}      0    0   3    branch2   branch1       ",
      r"                                                            ",
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
      r"                                                            ",
      r"  Origin   Local    Age   <-   ->   Branch    Base      PR  ",
      r" ────────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                    ",
      r"   \w{5}   \w{5}      0    0   1    branch1                 ",
      r"           \w{5}      0    0   3    branch2   branch1       ",
      r"                                                            ",
      r"git add . && git commit --amend --no-edit && git push -f && \\",
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
      r"                                                          ",
      r"  Origin   Local    Age   <-   ->    Branch    Base   PR  ",
      r" ──────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0     main                 ",
      r"   \w{5}   \w{5}      0    0   5 M   branch2              ",
      r"                                                          ",
      r"Tool limitation: cannot amend or update branches with merge commits.",
    ],
    expected_returncode=1,
  )

  run_test(
    None,
    "branches amend -y",
    [
      r"                                                          ",
      r"  Origin   Local    Age   <-   ->    Branch    Base   PR  ",
      r" ──────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0     main                 ",
      r"   \w{5}   \w{5}      0    0   5 M   branch2              ",
      r"                                                          ",
      r"Tool limitation: cannot amend or update branches with merge commits.",
    ],
    expected_returncode=1,
    cleanup_command="git clean -fd",
  )

  run_test(
    "git checkout branch1 && git push && echo 'file5' > file5.txt",
    "branches amend",
    [
      r"                                                         ",
      r"  Origin   Local    Age   <-   ->   Branch    Base   PR  ",
      r" ─────────────────────────────────────────────────────── ",
      r"           \w{5}      0    0   0    main                 ",
      r"   \w{5}   \w{5}      0    0   1    branch1              ",
      r"                                                         ",
      r"git add . && git commit --amend --no-edit && git push -f",
      r"",
    ],
  )
