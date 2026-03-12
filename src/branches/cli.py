# Example usage:
# python branches.py
from . import VERSION
import argparse
from .utils.git_utils import GitUtils
from git import Commit
import requests
import os
import subprocess
import sys
from urllib.parse import urlencode
from rich.console import Console
from rich import box
from rich.live import Live
from rich.table import Table
from datetime import datetime, timezone
import re
from typing import TypeAlias
from pydash import get
import copy
from textwrap import dedent

# Using some TypeAliases just for readability / documentation
StrBranchName: TypeAlias = str
StrSha: TypeAlias = str
StrShaShort: TypeAlias = str
StrShaRef: TypeAlias = str  # Examples: "branch1", "branch1~3", "branch2~1".
StrCommand: TypeAlias = str
DictUpdateParams: TypeAlias = dict
DictTableRow: TypeAlias = dict

console = Console(highlight=False)

LOCAL_SHA_COLOR = "blue"
CURRENT_BRANCH_COLOR = "green"
MERGE_COMMIT_COLOR = "dark_orange3"

# Starting with Python 3.7, dictionaries officially maintain the order in which keys were inserted
# The logic in this script assumes this is the case.
COLUMNS = {
  "origin": {
    "column_name": "Origin",
    "column_props": {
      "no_wrap": True,
      "justify": "right",
    },
  },
  "relationship": {
    "column_name": "-",
    "column_props": {
      "justify": "center",
    },
  },
  "local": {
    "column_name": "Local",
    "column_props": {
      "no_wrap": True,
      "justify": "left",
      "style": f"{LOCAL_SHA_COLOR}",
      "header_style": f"{LOCAL_SHA_COLOR}",
    },
  },
  "age": {
    "column_name": "Age",
    "column_props": {
      "justify": "right",
      "style": f"{LOCAL_SHA_COLOR}",
      "header_style": f"{LOCAL_SHA_COLOR}",
    },
  },
  "behind": {
    "column_name": "<-",
    "column_props": {"justify": "right"},
  },
  "ahead": {
    "column_name": "->",
    "column_props": {"justify": "left"},
  },
  "branch": {
    "column_name": "Branch",
    "column_props": None,
  },
  "base": {
    "column_name": "Base",
    "column_props": None,
  },
  "pr": {
    "column_name": "PR",
    "column_props": None,
  },
}

PR_STATUS_COLORS = {"open": "green", "closed": "red", "merged": "medium_purple1"}


class GitHubApiError(Exception):
  pass


def main() -> int:
  """Entry point for the CLI."""
  parser = argparse.ArgumentParser(
    prog="branches",
    formatter_class=argparse.RawTextHelpFormatter,
    description=dedent("""\
      A tool to manage git branches

      This tool displays a table of local git branches with their status relative to
      the main branch and their remote counterparts. It also suggests commands to
      keep branches up-to-date. These are "udpate commands". You decide whether to
      run them or not. The tool will never execute any write commands on its own
      unless you use the -y flag or you agree at the prompt. You shouldn't blindly
      run git commands. Always read them first.

      This tool also supports operations. The only operation available at the moment
      is "amend". Run `branches amend -h` for more information.
    """),
    epilog=dedent("""\
      The table displays the following information:
      - Origin: SHA of the branch on the remote. Links to the GitHub compare page.
      - Local: SHA of the local branch.
      - Age: Age of the branch in days since last commit.
      - <-: Number of commits the branch is behind the main branch.
      - ->: Number of commits the branch is ahead of the main branch.
      - Branch: Name of the branch.
      - Base: Base branch that this branch is based on.
      - PR: Status of the associated Pull Request on GitHub, if any.

      For PR information, a GITHUB_TOKEN environment variable with repo access is
      required.

      Example usage:
        branches
        branches -s
        branches -s -q
    """),
  )

  parser.add_argument(
    "--no-push", action="store_true", default=False, help="Do not suggest push commands"
  )

  parser.add_argument(
    "-q", "--quiet", action="store_true", default=False, help="Do not suggest update commands"
  )

  parser.add_argument(
    "-v", "--version", action="store_true", default=False, help="Print version and exit"
  )

  parser.add_argument("-C", "--path", type=str, help="Path to the git repository")

  parser.add_argument(
    "-n",
    "--no",
    action="store_true",
    default=False,
    help="Automatically decline to update commands",
  )

  parser.add_argument(
    "-y",
    "--yes",
    action="store_true",
    default=False,
    help="Automatically run update commands. THIS IS DANGEROUS!",
  )

  parser.add_argument(
    "-s", "--short", action="store_true", default=False, help="Show a short list only"
  )

  parser.add_argument("operation", nargs="?", choices=["amend"], help="Operation")

  # subparser = parser.add_subparsers(
  #   dest="operation",
  #   metavar="operation",
  # )

  # subparser.add_parser(
  #   "amend",
  #   formatter_class=argparse.RawTextHelpFormatter,
  #   help="Amend operation. More info with `branches amend -h`.",
  #   description=dedent("""\
  #     Amend operation

  #     This operation gives you "update commands" that you can run to amend the last
  #     commit of a branch and ensure all dependant branches also receive this update,
  #     keeping the commit tree structure intact.
  #   """),
  #   epilog=dedent("""\
  #     When using the "amend" operation, the tool generates "update commands" to:
  #     - Update the last commit with new, unstaged, and staged changes.
  #     - Rebase all branches that depend on this commit
  #     - Force-push branches after rebasing if they were in sync with origin before
  #       the rebase and there's no other authors.

  #     Example usage:
  #       branches amend
  #   """),
  # )

  ret = 1
  try:
    ret = branches(parser.parse_args())
  except KeyboardInterrupt:
    print("Interrupted")

  return ret


def branches(args: argparse.Namespace) -> int:
  """Main function to display the branches table and update commands.

  Instantiates the table and prints out the update commands.

  Returns:
    int: Exit code (0 for success).
  """
  # `header_style=""`` removes the bold which makes assigning a yellow header not work.
  ret = 0

  if args.version:
    print(VERSION)
    return ret

  if args.path:
    if not os.path.isdir(args.path) or not os.path.exists(args.path):
      print(f"Path '{args.path}' does not exist or is not a directory.")
      return 1
    repo = GitUtils.repo_from_path(args.path)
  else:
    repo = GitUtils.repo_from_path()
  if repo is None:
    print("Not a git repository.")
    return 1

  git_utils = GitUtils(repo=repo)
  table = Table(padding=(0, 0), box=box.SIMPLE_HEAD, header_style="")
  for _column_key, column_attr in COLUMNS.items():
    table.add_column(column_attr["column_name"], **(column_attr["column_props"] or {}))

  if args.operation == "amend":
    args.short = True

  with Live(table, console=console, refresh_per_second=20):
    db = print_table(args, table, git_utils)

  print("")

  if args.operation is None:
    update_commands = generate_update_commands(db, git_utils, args.no_push)
  elif args.operation == "amend":
    if len(git_utils.current_branch() or "") <= 0:
      print("Cannot run amend on a detached HEAD. Check out a branch first.\n")
      return 1

    if git_utils.main_branch() == git_utils.current_branch():
      print("Cannot run amend on the main branch. Checkout a different branch.\n")
      return 1

    changes_to_add = (
      git_utils.staged_changes_filepaths()
      + git_utils.unstaged_changes_filepaths()
      + git_utils.untracked_filepaths()
    )

    if len(changes_to_add) <= 0:
      print("No changes to amend with.\n")
      return 1

    err, update_commands = generate_amend_commands(db, git_utils, args.no_push)
    if len(err or "") > 0:
      print(err)
      return 1
  else:
    update_commands = []  # Unexpected

  if len(update_commands) > 0 and not args.quiet:
    print(" && \\\n".join(update_commands))
    print("")
    if not args.no and (
      args.yes or ("PYTEST_CURRENT_TEST" not in os.environ and prompt("Run update command?"))
    ):
      sys.stdout.flush()
      ret = subprocess.run(
        " && ".join(update_commands), shell=True, stderr=subprocess.STDOUT
      ).returncode

  return ret


def print_table(args: argparse.Namespace, table: Table, git_utils: GitUtils) -> dict:
  """Prints out the state of all local branches in a table.

  Returns:
    A dict with the required arguments to generate update commands. The keys of this dict must be
    the arguments to the function that outputs the update commands.
  """
  db = create_db(git_utils, short=args.short)
  show_warnings = True
  for branch in db["local"]:
    row_dict = table_row(db, branch, git_utils, show_warnings)
    show_warnings = False
    table.add_row(*[row_dict.get(column_key) for column_key in COLUMNS.keys()])

  return db


def create_db(
  git_utils: GitUtils,
  default: str | None = None,
  branches: list[str] | None = None,
  ignore_behind: bool = False,
  short=False,
  remote: dict[StrBranchName, dict] = None,
):
  if not default:
    default = git_utils.main_branch()

  db = {
    "email": git_utils.current_user_email(),
    "default": default,
    "current": git_utils.current_branch(),
    "local": {},
    "remote": {},
  }

  local: dict[str, dict] = {
    default: {
      "sha": git_utils.local_sha_from_branch(default),
      "pr_status": None,
      "pr_sha": None,
      "distance_default": (0, 0),
      "distance_base": (0, 0),
      "base": default,
      "has_merge_commits": False,
      "shas_ahead_default": [],
      "shas_ahead_default_other_authors": set(),
      "default": True,
    }
  }

  if branches is None:
    branches = git_utils.branches()

  for branch in branches:
    if branch == default:
      continue

    distance_default = git_utils.distance(default, branch)
    if ignore_behind and distance_default[0]:
      continue

    local[branch] = {
      "sha": git_utils.local_sha_from_branch(branch),
      "pr_status": None,  # one of [None, "open", "merged", "closed"]
      "pr_sha": None,
      "distance_default": distance_default,
      "distance_base": distance_default,
      "base": default,
      "has_merge_commits": False,
      "shas_ahead_default": [],
      "shas_ahead_default_other_authors": set(),
      "default": False,
    }

  refresh_distances(local, default, db["email"], git_utils)

  for branch in local_branches_order(local, short, db["current"], db["default"]):
    if branch not in db["local"]:
      db["local"][branch] = local[branch]

  if remote is None:
    for branch, remote_sha in git_utils.remote_shas(list(db["local"].keys())).items():
      db["remote"][branch] = construct_empty_remote(remote_sha)
  else:
    for branch in remote.keys() & db["local"].keys():
      db["remote"][branch] = construct_remote(
        remote[branch]["sha"],
        db["email"],
        branch,
        default,
        git_utils,
        get(remote, [default, "sha"]),
      )

  return db


def table_row(
  db: dict,
  branch: StrBranchName,
  git_utils: GitUtils,
  show_warnings: bool,
) -> DictTableRow:
  """Populates `ret` and returns a dictionary with `COLUMNS` values to add to the table

  The main two purposes of this function are:
    1. Create a dict with column information about this `branch`. Caller should use this dict to
       add a row to the table that is being printed out to the screen.
    2. Populate/modify `ret`. As it gains more information about `branch` to display out to the
       screen, if this information is relevant to the later fuction that creates the update commands
       it will populate `ret` with this information.

  Args:
    branch: Branch for this row.
    git_utils: `git` facade instance.
    remote_shas: Remote sha (values) for each branch (keys).
    base_branch: The branch this `branch` is based off of.
    branch_distances: the ahead/behind distances (values) for each branch (keys).
    ret: The keys of this dict must be the arguments to the function that outputs the update
      commands.
  """
  row_dict = {}  # See `COLUMNS` for valid keys.
  default = db["default"]
  sync_status = "not_pushed"  # means this branch is not in origin
  # 'synced'       means this branch is in origin and is the same as local
  # 'unsynced'     means this branch is in origin but is not the same as local

  local_commit = git_utils.local_commit_from_sha(db["local"][branch]["sha"])
  local_sha = str(local_commit)
  local_sha_short = local_sha[:5]

  remote_commit: Commit | None = None
  remote_sha = get(db, ["remote", branch, "sha"])
  remote_sha_short = ""

  if remote_sha is not None:
    remote_sha_short = remote_sha[:5]
    if remote_sha == local_sha:
      sync_status = "synced"
    else:
      sync_status = "unsynced"
      remote_commit = git_utils.local_commit_from_sha(remote_sha)
      if remote_commit is None:
        remote_commit = git_utils.fetch_single_sha(remote_sha)

    db["remote"][branch] = construct_remote(
      remote_sha,
      db["email"],
      branch,
      default,
      git_utils,
      get(db, ["remote", default, "sha"]),
    )

  try:
    pr = None
    if "GITHUB_TOKEN" in os.environ:
      pr = pull_request(branch, os.environ["GITHUB_TOKEN"], git_utils)
    elif show_warnings and "PYTEST_CURRENT_TEST" not in os.environ:
      print("WARNING: GITHUB_TOKEN envar is not set.")
  except requests.exceptions.ConnectionError:
    pr = None
    if show_warnings:
      print("WARNING: there is internet connection issues.")
      print("Network dependent functionality will not work.")
  except GitHubApiError as exception:
    pr = None
    if show_warnings:
      print(f"WARNING: {exception}")

  # TODO: only consider the PR if it's against the db["default"] ?
  if pr is not None and branch != default:
    if pr.get("state") == "open":
      pr_status = "open"
    elif pr.get("merged_at"):
      pr_status = "merged"
    else:
      pr_status = "closed"

    db["local"][branch]["pr_status"] = pr_status
    db["local"][branch]["pr_sha"] = pr["head"]["sha"]

    pr_short_sha = pr["head"]["sha"][:5]
    if pr["head"]["sha"] == local_sha:
      pr_short_sha = f"[{LOCAL_SHA_COLOR}]{pr_short_sha}[/{LOCAL_SHA_COLOR}]"

    row_dict["pr"] = (
      f"[link={pr['html_url']}][{PR_STATUS_COLORS[pr_status]}]#{pr['number']}"
      f"[/{PR_STATUS_COLORS[pr_status]}][/link] ({pr_short_sha}) by " + pr["user"]["login"]
    )

  message_remote_sha = remote_sha_short
  if sync_status == "synced":
    message_remote_sha = f"[{LOCAL_SHA_COLOR}]{remote_sha_short}[/{LOCAL_SHA_COLOR}]"
  elif sync_status == "unsynced":
    if remote_commit.committed_date < local_commit.committed_date:
      message_remote_sha = f"[dim]{remote_sha_short}[/dim]"
    else:
      message_remote_sha = f"[bold]{remote_sha_short}[/bold]"

    row_dict["relationship"] = db["remote"][branch]["relationship"]
    if row_dict["relationship"] == "Y":
      row_dict["relationship"] = "[yellow]" + row_dict["relationship"] + "[/yellow]"

  if sync_status in ["synced", "unsynced"] and branch != default:
    owner, repo = git_utils.owner_and_repo()
    url = f"https://github.com/{owner}/{repo}/tree/{branch}"
    message_remote_sha = f"[link={url}]{message_remote_sha}[/link]"

  behind, ahead = db["local"][branch]["distance_default"]
  row_dict["ahead"] = str(ahead)
  row_dict["behind"] = str(behind)

  if (
    sync_status in ["synced"]
    and branch != default
    and default in db["remote"]
    and db["remote"][default]["sha"] == db["local"][default]["sha"]
  ):
    if ahead > 0:
      url = f"https://github.com/{owner}/{repo}/compare/{default}...{branch}"
      row_dict["ahead"] = f"[link={url}]{row_dict['ahead']}[/link]"

    if behind > 0:
      url = f"https://github.com/{owner}/{repo}/compare/{branch}...{default}"
      row_dict["behind"] = f"[link={url}]{row_dict['behind']}[/link]"

  if db["email"] is None and show_warnings:
    print("WARNING: No user email configured in git.")
    print("Set it with git config --global user.email 'first.last@example.com'")

  if get(db, ["remote", branch, "shas_ahead_default_other_authors"], []):
    message_remote_sha = f"[red]![/red]{message_remote_sha}"
  else:
    message_remote_sha = f" {message_remote_sha}"

  if db["local"][branch]["shas_ahead_default_other_authors"]:
    message_local_sha = f"{local_sha_short}[red]![/red]"
  else:
    message_local_sha = f"{local_sha_short} "

  base_branch = ""
  if db["local"][branch]["base"] != default:
    base_branch = db["local"][branch]["base"]
    if db["local"][branch]["distance_base"][0]:
      base_branch += f"~{db['local'][branch]['distance_base'][0]}"

  row_dict["base"] = base_branch
  row_dict["origin"] = message_remote_sha
  row_dict["local"] = message_local_sha
  row_dict["age"] = str((datetime.now(timezone.utc) - git_utils.date_authored(local_sha)).days)
  row_dict["branch"] = branch

  if branch == git_utils.current_branch():
    row_dict["branch"] = f"[{CURRENT_BRANCH_COLOR}]{row_dict['branch']}[/{CURRENT_BRANCH_COLOR}]"
    row_dict["ahead"] = f"[{CURRENT_BRANCH_COLOR}]{row_dict['ahead']}[/{CURRENT_BRANCH_COLOR}]"
    row_dict["behind"] = f"[{CURRENT_BRANCH_COLOR}]{row_dict['behind']}[/{CURRENT_BRANCH_COLOR}]"

  if db["local"][branch]["has_merge_commits"]:
    row_dict["ahead"] = f"{row_dict['ahead']} [{MERGE_COMMIT_COLOR}]M[/{MERGE_COMMIT_COLOR}]"

  return row_dict


def local_branches_order(
  local: dict[str, dict],
  short: bool,
  current: StrBranchName,
  default: StrBranchName,
) -> list[StrBranchName]:
  """Defines what branches will be output in the table.

  Returns:
    An array of branch names. The first branch is guaranteed to be the main branch. The second
    branch is the current branch, unless the current branch is the main branch.
  """
  all_branches = list(local.keys())

  if short:
    # maps base branches to the branches that depend on those base branches
    dependent_branches: dict[StrBranchName, list[StrBranchName]] = {}
    # maps a branch to its base branch
    base_branches: dict[StrBranchName, tuple[StrShaRef, int, int]] = {}
    for branch in sorted(
      local.keys(),
      key=lambda branch_name: (
        local[branch_name]["distance_base"][1],
        branch_name,
      ),
    ):
      branchd = local[branch]
      if default in [branch, branchd["base"]]:
        continue

      dependent_branches[branchd["base"]] = dependent_branches.get(branchd["base"], [])
      dependent_branches[branchd["base"]].append(branch)
      base_branches[branch] = (branchd["base"], *branchd["distance_base"])

    queue: list[StrBranchName] = []
    queue_saw: set[StrBranchName] = set()
    ret = [default]
    if current != default:
      ret.append(current)
      queue.append(current)
      queue_saw.add(current)

    while len(queue) > 0:
      branch = queue.pop()

      # if this branch has a base branch, add the base branch to ret and to the queue
      if branch in base_branches:
        branch_to_add = base_branches[branch][0]
        if branch_to_add not in queue_saw:
          ret.append(branch_to_add)
          queue.append(branch_to_add)
          queue_saw.add(branch_to_add)

      # if this is a base branch, add all the branches that depend on it to ret and to the queue
      if branch in dependent_branches:
        for branch_to_add in dependent_branches[branch]:
          if branch_to_add not in queue_saw:
            ret.append(branch_to_add)
            queue.append(branch_to_add)
            queue_saw.add(branch_to_add)
  else:
    ret = all_branches

    ret.remove(current)
    ret.insert(0, current)

    if default in ret:
      ret.remove(default)
      ret.insert(0, default)

  return ret


def construct_empty_remote(remote_sha: StrSha) -> dict:
  return {
    "sha": remote_sha,
    "distance_local": None,
    "relationship": None,  # one of [None, ">", "<", "Y"]
    "distance_default": None,
    "shas_ahead_default": [],
    "shas_ahead_default_other_authors": set(),
    "distance_default_local": None,
    "shas_ahead_default_local": [],
    "shas_ahead_default_local_other_authors": set(),
  }


def refresh_distances(
  local: dict[StrBranchName, dict], default: StrBranchName, local_email: str, git_utils: GitUtils
) -> dict[StrBranchName, dict]:
  """
  For each branch except the default one in local, it updates:
  - distance_default
  - has_merge_commits
  - shas_ahead_default
  - shas_ahead_default_other_authors

  To do this, it uses local[default]["sha"], and the "sha" field for each branch in local

  Additionally, it calls `refresh_bases` so it updates all fields that refresh_bases updates
  """
  default_sha = local[default]["sha"]
  for branch, branchd in local.items():
    if branch == default:
      continue

    branchd["distance_default"] = git_utils.distance(default_sha, branchd["sha"])

    for parents in git_utils.parent_shas_of_ref(branchd["sha"], branchd["distance_default"][1]):
      if len(parents) > 2:
        branchd["has_merge_commits"] = True
        continue

    branchd["shas_ahead_default"] = []
    branchd["shas_ahead_default_other_authors"] = set()

    for sha in git_utils.shas_ahead_of(default_sha, branchd["sha"]):
      if branchd["has_merge_commits"]:
        continue
      email = git_utils.commit_author_email(sha)
      branchd["shas_ahead_default"].append({"sha": sha, "email": email})
      if git_utils.commit_author_email(sha) != local_email:
        branchd["shas_ahead_default_other_authors"].add(email)

    local[branch] = branchd

  refresh_bases(local, default)
  return local


def construct_remote(
  remote_sha: StrSha,
  local_email: str,
  branch: StrBranchName,
  default: StrBranchName,
  git_utils: GitUtils,
  remote_default_sha: StrSha | None = None,
):
  ret = construct_empty_remote(remote_sha)

  local_sha = git_utils.local_commit_from_branch(branch).hexsha
  default_sha = git_utils.local_commit_from_branch(default).hexsha
  behind, ahead = git_utils.distance(local_sha, remote_sha)

  ret["distance_local"] = (behind, ahead)
  if behind == 0 and ahead:
    ret["relationship"] = ">"
  elif behind and ahead == 0:
    ret["relationship"] = "<"
  elif behind and ahead:
    ret["relationship"] = "Y"
  else:
    ret["relationship"] = "="

  if remote_default_sha:
    ret["distance_default"] = git_utils.distance(remote_default_sha, remote_sha)
    for sha in git_utils.shas_ahead_of(remote_default_sha, remote_sha):
      email = git_utils.commit_author_email(sha)
      ret["shas_ahead_default"].append({"sha": sha, "email": email})
      if email != local_email:
        ret["shas_ahead_default_other_authors"].add(email)

  default_sha = default_sha
  ret["distance_default_local"] = git_utils.distance(default_sha, remote_sha)
  for sha in git_utils.shas_ahead_of(default_sha, remote_sha):
    email = git_utils.commit_author_email(sha)
    ret["shas_ahead_default_local"].append({"sha": sha, "email": email})
    if email != local_email and branch != default:
      ret["shas_ahead_default_local_other_authors"].add(email)

  return ret


def generate_amend_commands(
  db: dict, git_utils: GitUtils, no_push: bool = False
) -> tuple[str | None, list[StrCommand] | None]:
  """Returns a list of commands to run to amend the current commit and maintain tree structure

  Returns:
    Tuple with two values:
    1. If an error occurs, this will be the message string, otherwise None.
    2. A list of commands to run
  """
  if db["local"][db["current"]]["has_merge_commits"]:
    return ("Tool limitation: cannot amend or update branches with merge commits.", None)
  remote = copy.deepcopy(db["remote"])
  db = create_db(
    git_utils,
    default=db["current"],
    branches=db["local"].keys() - {db["default"]},
    ignore_behind=True,
    remote=db["remote"],
  )
  for branch, branchd in db["local"].items():
    branchd["distance_default"] = (
      branchd["distance_default"][0] + 1,
      branchd["distance_default"][1],
    )
    if branchd["has_merge_commits"]:
      return ("Tool limitation: cannot amend or update branches with merge commits.", None)
  db["remote"] = remote
  amend_commands = ["git add -A && git commit --amend --no-edit"]
  other_authors = db["local"][db["current"]]["shas_ahead_default_other_authors"]
  if get(db, ["remote", db["current"], "relationship"]) == "=" and not other_authors:
    amend_commands[0] += " && git push -f"
  return (None, amend_commands + generate_update_commands(db, git_utils, no_push, True))


def generate_update_commands(
  db: dict, git_utils: GitUtils, no_push: bool = False, is_amend: bool = False
) -> list[StrCommand]:
  """Creates and returns the list of git commands to run to update the branches."""
  update_commands = []
  default = db["default"]
  current_original = db["current"]
  current = db["current"]

  #
  # Populate branches_to_delete
  #

  branches_to_delete: set[StrBranchName] = set()
  for branch, branchd in db["local"].items():
    if branch == default:
      continue
    if (
      branchd["pr_status"] == "merged"
      and branchd["pr_sha"] == branchd["sha"]
      and branch not in db["remote"]
    ):
      branches_to_delete.add(branch)
  if branches_to_delete and current != default:
    update_commands.append(f"git checkout {default}")
    current = default
  for branch in branches_to_delete:
    update_commands.append(f"git branch -D {branch}")

  for branch in branches_to_delete:
    del db["local"][branch]

  #
  # Pull default
  #

  branches_behind: set[StrBranchName] = set()
  if not is_amend and get(db, ["remote", default, "relationship"]) == ">":
    update_commands.append("git pull")
    if current != default:
      update_commands[-1] = f"git checkout {default} && " + update_commands[-1]
      current = default
    db["local"][default]["sha"] = db["remote"][default]["sha"]
    refresh_distances(db["local"], default, db["email"], git_utils)

  #
  # Populate branches_pulled
  #

  branches_pulled: set[StrBranchName] = set()
  if not is_amend:
    for branch in sorted(db["remote"].keys() - branches_to_delete - {default}):
      branchd = db["remote"][branch]
      if branchd["relationship"] == ">" and not branchd["shas_ahead_default_local_other_authors"]:
        update_commands.append(f"git checkout {branch} && git pull")
        current = branch
        branches_pulled.add(branch)
        db["local"][branch]["sha"] = branchd["sha"]

  if branches_pulled:
    refresh_distances(db["local"], default, db["email"], git_utils)

  #
  # Populate branches_behind
  #

  for branch, branchd in db["local"].items():
    if branchd["distance_default"][0]:
      branches_behind.add(branch)
  branches_behind.discard(default)

  #
  # Populate branches_to_rebase
  #

  branches_to_rebase: set[StrBranchName] = set()
  for branch in branches_behind:
    if not db["local"][branch]["has_merge_commits"]:
      branches_to_rebase.add(branch)

  #
  # Populate safe_to_push
  #

  safe_to_push: set[StrBranchName] = set()
  if not no_push:
    for branch in branches_to_rebase & db["remote"].keys():
      other_authors = len(db["local"][branch]["shas_ahead_default_other_authors"])
      if db["remote"][branch]["relationship"] == "=" and not other_authors:
        safe_to_push.add(branch)

  #
  # Perform rebase operations
  #

  if branches_to_rebase:
    base_branches = refresh_bases(db["local"], db["default"])
    rebased_branches: set[StrBranchName] = set()

    for branch in rebase_order(base_branches) + list(branches_to_rebase):
      if branch not in branches_to_rebase or branch in rebased_branches:
        continue

      base_branch = db["local"][branch]["base"]
      behind, ahead = db["local"][branch]["distance_base"]
      if base_branch == default:
        if not is_amend:
          ahead = None
      elif behind:
        base_branch += f"~{behind}"

      update_commands.append(rebase_command(branch, base_branch, safe_to_push, ahead))
      current = branch

      rebased_branches.add(branch)

  if current_original in branches_to_delete and current != default:
    update_commands.append(f"git checkout {default}")
  elif current_original not in branches_to_delete and current != current_original:
    update_commands.append(f"git checkout {current_original}")

  return update_commands


def rebase_command(
  branch_to_rebase: StrBranchName,
  base_branch: StrShaRef,
  branches_safe_to_push: list[StrBranchName] = [],
  starting_from: int | None = None,
) -> StrCommand:
  """Returns the rebase command for `branch_to_rebase`."""
  ret = f"git checkout {branch_to_rebase}"

  if starting_from is None:
    ret += f" && git rebase {base_branch}"
  elif starting_from == 0:
    ret += f" && git reset --hard {base_branch}"
  else:
    ret += f" && git rebase --onto {base_branch} {branch_to_rebase}~{starting_from}"

  if branch_to_rebase in branches_safe_to_push:
    ret += " && git push -f"

  return ret


def branches_ahead_shas_to_refs(
  local: dict[StrBranchName:dict],
) -> list[tuple[StrBranchName, list[StrShaRef]]]:
  """Returns a list of branch refs for each branch

  It bases the computation on "shas_ahead_default"

  Args:
    db: database

  Returns:
    list: List of [branch, refs] pairs. For example:
      [
        ("b2", ["b2"]),
        ("b5", ["b5~1", "b5"]),
        ("b3", ["b2", "b3~1", "b3"]),
        ("b6", ["b5~1", "b5", "b6"])
      ]
  """
  branches_ahead_shas: dict[str, list[str]] = {}

  for branch, branchd in local.items():
    for shad in branchd["shas_ahead_default"]:
      branches_ahead_shas[branch] = branches_ahead_shas.get(branch, [])
      branches_ahead_shas[branch].append(shad["sha"])

  branches_ahead_refs = []
  sha_to_ref = {}

  for branch, shas in sorted(branches_ahead_shas.items(), key=lambda x: (len(x[1]), x[0])):
    to_append = (branch, [])

    for idx, sha in enumerate(shas):
      if sha not in sha_to_ref:
        distance = len(shas) - idx - 1

        if distance <= 0:
          ref = branch
        else:
          ref = f"{branch}~{distance}"

        sha_to_ref[sha] = ref

      to_append[1].append(sha_to_ref[sha])

    branches_ahead_refs.append(to_append)

  return branches_ahead_refs


def rebase_order(
  base_branches: dict[StrBranchName, tuple[StrShaRef, int, int]],
) -> list[StrBranchName]:
  """
  Determines the order in which branches should be rebased based on their base branches.

  Args:
    base_branches (dict): Mapping of branch names to their base branch refs.

  Returns:
    list: Ordered list of branches for rebasing.
  """
  ret = []

  for branch in base_branches.keys():
    for branch_to_rebase in rebase_order_for(branch, base_branches):
      if branch_to_rebase not in ret:
        ret.append(branch_to_rebase)

  return ret


def rebase_order_for(
  branch: StrBranchName, base_branches: dict[StrBranchName, tuple[StrShaRef, int, int]]
) -> list[StrBranchName]:
  """
  Recursively determines the rebase order for a given branch.

  Args:
    branch (str): Branch name to determine order for.
    base_branches (dict): Mapping of branch names to their base branch refs.

  Returns:
    list: Ordered list of branches for rebasing.
  """
  if branch in base_branches:
    ret = rebase_order_for(base_branches[branch][0], base_branches)
    ret.append(branch)
    return ret
  else:
    return [branch]


def refresh_bases(
  local: dict[StrBranchName:dict], default: StrBranchName
) -> dict[StrBranchName, tuple[StrShaRef, int, int]]:
  """
  For each branch in local, it updates:
  - base
  - distance_base
  """
  ret = base_branches_from_branches_ahead_refs(branches_ahead_shas_to_refs(local))

  for branch, branchd in local.items():
    if branch in ret:
      branchd["base"] = ret[branch][0]
      branchd["distance_base"] = (ret[branch][1], ret[branch][2])
    else:
      branchd["base"] = default
      branchd["distance_base"] = branchd["distance_default"]

  return ret


def base_branches_from_branches_ahead_refs(
  branches_ahead_refs: list[tuple[StrBranchName, list[StrShaRef]]],
) -> dict[StrBranchName, tuple[StrShaRef, int, int]]:
  """Determines the base branch for each branch from a list of ahead refs.

  Args:
    List of [branch, refs] pairs. For example:
      [
        ('b2', ['b2']),
        ('b5', ['b5~1', 'b5']),
        ('b3', ['b2', 'b3~1', 'b3']),
        ('b6', ['b5~1', 'b5', 'b6'])
      ]

  Returns:
    A dict mapping of branch names to their base branch refs and how many commits on top of their
    base branch they have. For example:
      {
        "b3": ("b2", 0, 2),
        "b6": ("b5", 0, 1)
      }
  """
  ret = {}

  for branch, refs in branches_ahead_refs:
    commit_count = 0
    for ref in reversed(refs):
      result = re.search(r"^\s*(.*?)(?:~(\d+))?\s*$", ref)
      parent_branch = result.group(1)
      if parent_branch != branch:
        if result.group(2) is None:
          behind = 0
        else:
          behind = int(result.group(2))
        ret[branch] = (parent_branch, behind, commit_count)
        break
      commit_count += 1

  return ret


def pull_request(branch: StrBranchName, github_token: str, git_utils: GitUtils) -> dict | None:
  """Fetches the pull request for a given branch from the GitHub API.

  Assumes the envar `GITHUB_TOKEN` is set.

  See API documentation here:
  https://docs.github.com/en/rest/pulls/pulls?apiVersion=2022-11-28#list-pull-requests

  Args:
    branch (str): Branch name to look up.

  Returns:
    Pull request data if found, otherwise None.
  """
  owner, repo = git_utils.owner_and_repo()

  if owner is None or repo is None:
    return None

  proto = "https"
  domain = "api.github.com"
  if "PYTEST_CURRENT_TEST" in os.environ:
    if "GITHUB_PROTO" in os.environ and "GITHUB_DOMAIN" in os.environ:
      proto = os.environ.get("GITHUB_PROTO", proto)
      domain = os.environ.get("GITHUB_DOMAIN", "localhost")
    else:
      return None

  params = urlencode({"head": f"{owner}:{branch}", "state": "all"})

  response = requests.get(
    f"{proto}://{domain}/repos/{owner}/{repo}/pulls?{params}",
    headers={
      "Accept": "application/vnd.github+json",
      "Authorization": f"Bearer {github_token}",
      "X-GitHub-Api-Version": "2022-11-28",
    },
  )

  if response.status_code != 200:
    raise GitHubApiError(f"GitHub returned a {response.status_code}: {response.text}")

  pull_requests = response.json()
  if len(pull_requests) > 0:
    return pull_requests[0]
  else:
    return None


def prompt(question: str, default: bool | None = False) -> bool | None:
  valid = {"yes": True, "y": True, "ye": True, "no": False, "n": False}

  while True:
    sys.stdout.write(question + {None: " [y/n] ", True: " [Y/n] ", False: " [y/N] "}[default])

    try:
      choice = input().lower().strip()
    except KeyboardInterrupt:
      choice = "no"

    if choice in valid:
      return valid[choice]
    elif choice == "" and default is not None:
      return default
    else:
      sys.stdout.write("Please respond with 'yes' or 'no' (or 'y' or 'n').\n")


if __name__ == "__main__":
  raise SystemExit(main())
