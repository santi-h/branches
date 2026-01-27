# Example usage:
# python branches.py
import argparse
from .utils.git_utils import GitUtils
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
import copy
from typing import TypeAlias

# Using some TypeAliases just for readability / documentation
StrBranchName: TypeAlias = str
StrSha: TypeAlias = str
StrShaShort: TypeAlias = str
StrShaRef: TypeAlias = str # Examples: "branch1", "branch1~3", "branch2~1".
StrCommand: TypeAlias = str
DictUpdateParams: TypeAlias = dict
DictTableRow: TypeAlias = dict

console = Console(highlight=False)

LOCAL_SHA_COLOR = 'blue'
CURRENT_BRANCH_COLOR = 'green'
MERGE_COMMIT_COLOR = 'dark_orange3'

# Starting with Python 3.7, dictionaries officially maintain the order in which keys were inserted
# The logic in this script assumes this is the case.
COLUMNS = {
  'origin': {
    'column_name': 'Origin',
    'column_props': { 'no_wrap': True, 'justify': 'right' }
  },
  'local': {
    'column_name': 'Local',
    'column_props': {
      'no_wrap': True,
      'justify': 'left',
      'style': f'{LOCAL_SHA_COLOR}',
      'header_style': f'{LOCAL_SHA_COLOR}'
    }
  },
  'age': {
    'column_name': 'Age',
    'column_props': {
      'justify': 'right',
      'style': f'{LOCAL_SHA_COLOR}',
      'header_style': f'{LOCAL_SHA_COLOR}'
    }
  },
  'behind': {
    'column_name': '<-',
    'column_props': { 'justify': 'right' }
  },
  'ahead': {
    'column_name': '->',
    'column_props': { 'justify': 'left' }
  },
  'branch': {
    'column_name': 'Branch',
    'column_props': None
  },
  'base': {
    'column_name': 'Base',
    'column_props': None
  },
  'pr': {
    'column_name': 'PR',
    'column_props': None
  }
}

PR_STATUS_COLORS = {
  'open': 'green',
  'closed': 'red',
  'merged': 'medium_purple1'
}

def main() -> int:
  """Entry point for the CLI."""
  parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  parser.add_argument('--no-push', action='store_true', default=False,
                      help='Do not suggest push commands')

  group = parser.add_mutually_exclusive_group()
  group.add_argument('operation', nargs='?', choices=['amend'], help='Operation')
  group.add_argument('-s', '--short', action='store_true', default=False,
                    help='Show a short list only')

  return branches(parser.parse_args())

def branches(args: argparse.Namespace) -> int:
  """Main function to display the branches table and update commands.

  Instantiates the table and prints out the update commands.

  Returns:
    int: Exit code (0 for success).
  """
  # `header_style=""`` removes the bold which makes assigning a yellow header not work.
  ret = 0

  table = Table(box=box.SIMPLE_HEAD, header_style="")
  for _column_key, column_attr in COLUMNS.items():
    table.add_column(column_attr['column_name'], **(column_attr['column_props'] or {}))

  if args.operation == 'amend':
    # TODO: make sure we're looking at a branch, if not, raise error here
    args.short = True

  with Live(table, console=console, refresh_per_second=20):
    update_commands_params = print_table(args, table)

  if args.operation is None:
    update_commands = generate_update_commands(**update_commands_params)
  elif args.operation == 'amend':
    update_commands = generate_amend_commands(**update_commands_params)
  else:
    update_commands = [] # Unexpected

  if len(update_commands) > 0:
    print('')
    print(' && \\\n'.join(update_commands))
    print('')
    if prompt('Run update command?'):
      ret = subprocess.run(' && '.join(update_commands), shell=True).returncode

  return ret

def print_table(args: argparse.Namespace, table: Table) -> DictUpdateParams:
  """Prints out the state of all local branches in a table.

  Returns:
    A dict with the required arguments to generate update commands. The keys of this dict must be
    the arguments to the function that outputs the update commands.
  """
  ret = {
    'branches': None,
    'main_branch': None,
    'no_push': args.no_push,
    'branches_deletable': [],
    'unsynced_main': False,
    'branches_behind': [],
    'branches_ahead_shas': {},
    'branches_with_merge_commits': [],
    'branches_safe_to_push': [],
  }

  git_utils = GitUtils()
  main_branch = git_utils.main_branch()
  all_branches = git_utils.branches()

  ret['main_branch'] = main_branch
  ret['current_branch'] = git_utils.current_branch()

  branch_distances = {}
  for branch in all_branches:
    branch_distances[branch] = git_utils.distance(branch, main_branch)

    if branch == main_branch or branch_distances[branch][0] <= 0:
      continue

    for parents in git_utils.parent_shas_of_ref(branch, branch_distances[branch][0]):
      if len(parents) > 2:
        ret['branches_with_merge_commits'].append(branch)
        break

    if branch not in ret['branches_with_merge_commits']:
      ret['branches_ahead_shas'][branch] = [
        sha[:5] for sha in git_utils.shas_ahead_of(main_branch, branch)]

  base_branches = base_branches_from_branches_ahead_refs(
    branches_ahead_shas_to_refs(ret['branches_ahead_shas']))

  ret['branches'] = local_branches_order(
    all_branches,
    main_branch,
    ret['current_branch'],
    base_branches,
    args.short
  )

  remote_shas = git_utils.remote_shas(ret['branches'])
  show_warnings = True
  for branch in ret['branches']:
    base_branch = base_branches.get(branch, [None, None])[0]
    row_dict = table_row(
      branch,
      git_utils,
      remote_shas,
      base_branch,
      branch_distances,
      ret,
      show_warnings
    )
    show_warnings = False
    table.add_row(*[row_dict.get(column_key) for column_key in COLUMNS.keys()])

  return ret

def table_row(
  branch: StrBranchName,
  git_utils: GitUtils,
  remote_shas: dict[StrBranchName, StrSha],
  base_branch: StrBranchName | None,
  branch_distances: dict[StrBranchName, list[int]],
  ret: DictUpdateParams,
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
  row_dict = {} # See `COLUMNS` for valid keys.

  sync_status = 'not_pushed' # means this branch is not in origin
              # 'synced'       means this branch is in origin and is the same as local
              # 'unsynced'     means this branch is in origin but is not the same as local

  local_commit = git_utils.local_commit_from_branch(branch)
  local_sha = str(local_commit)
  local_sha_short = local_sha[:5]
  local_author_emails: set[str] = set()

  remote_commit = None
  remote_sha = remote_shas.get(branch)
  remote_sha_short = ''
  remote_author_emails: set[str] = set()

  for sha in git_utils.shas_ahead_of(ret['main_branch'], branch):
    local_author_emails.add(git_utils.commit_author_email(sha))

  if remote_sha is not None:
    remote_sha_short = remote_sha[:5]
    if remote_sha == local_sha:
      sync_status = 'synced'
    else:
      sync_status = 'unsynced'
      remote_commit = git_utils.local_commit_from_sha(remote_sha)
      if remote_commit is None:
        remote_commit = git_utils.fetch_sigle_sha(remote_sha)

      if branch == ret['main_branch']:
        ret['unsynced_main'] = True

  try:
    pr = pull_request(branch)
  except requests.exceptions.ConnectionError as exception:
    pr = None
    if show_warnings:
      print('WARNING: there is internet connection issues.')
      print('Network dependent functionality will not work.')

  if pr is not None and branch != ret['main_branch']:
    if pr.get('state') == 'open':
      pr_status = 'open'
    elif len(pr.get('merged_at', '') or '') > 0:
      pr_status = 'merged'
    else:
      pr_status = 'closed'

    pr_sha = f'{pr['head']['sha'][:5]}'
    if pr['head']['sha'] == local_sha:
      pr_sha_status = 'synced'
      pr_sha = f'[{LOCAL_SHA_COLOR}]{pr_sha}[/{LOCAL_SHA_COLOR}]'
    else:
      pr_sha_status = 'unsynced'

    row_dict['pr'] = f'[link={pr['html_url']}][{PR_STATUS_COLORS[pr_status]}]#{pr['number']}' \
                      f'[/{PR_STATUS_COLORS[pr_status]}][/link] ({pr_sha}) by ' \
                      f'{pr['user']['login']}'

    if pr_status == 'merged' and pr_sha_status == 'synced' and sync_status == 'not_pushed':
      # Only delete if all of these are true:
      # - This is not the main branch
      # - The PR was merged
      # - The merged code is exactly the same as our local branch
      # - The branch was deleted in origin
      ret['branches_deletable'].append(branch)

  if sync_status == 'synced':
    message_remote_sha = f'[{LOCAL_SHA_COLOR}]{remote_sha_short}[/{LOCAL_SHA_COLOR}]'
  elif sync_status == 'unsynced':
    if remote_commit.committed_date < local_commit.committed_date:
      message_remote_sha = f'[dim]{remote_sha_short}[/dim]'
    else:
      message_remote_sha = f'[bold]{remote_sha_short}[/bold]'
  else:
    message_remote_sha = remote_sha_short

  if sync_status in ['synced', 'unsynced'] and branch != ret['main_branch']:
    owner, repo = git_utils.owner_and_repo()
    url = f'https://github.com/{owner}/{repo}/compare/{ret['main_branch']}...{branch}'
    message_remote_sha = f'[link={url}]{message_remote_sha}[/link]'
    for sha in git_utils.shas_ahead_of(ret['main_branch'], remote_sha):
      remote_author_emails.add(git_utils.commit_author_email(sha))

  has_different_author = False

  if any(email != git_utils.current_user_email() for email in remote_author_emails):
    has_different_author = True
    message_remote_sha = f'[red]![/red]{message_remote_sha}'
  else:
    message_remote_sha = f' {message_remote_sha}'

  if any(email != git_utils.current_user_email() for email in local_author_emails):
    has_different_author = True
    message_local_sha = f'{local_sha_short}[red]![/red]'
  else:
    message_local_sha = f'{local_sha_short} '

  if sync_status == 'synced' and not has_different_author:
    ret['branches_safe_to_push'].append(branch)

  ahead, behind = branch_distances[branch]
  row_dict['base'] = base_branch
  row_dict['origin'] = message_remote_sha
  row_dict['local'] = message_local_sha
  row_dict['age'] = str((datetime.now(timezone.utc) - git_utils.date_authored(local_sha)).days)
  row_dict['branch'] = branch
  row_dict['ahead'] = str(ahead)
  row_dict['behind'] = str(behind)

  if branch == git_utils.current_branch():
    row_dict['branch'] = f'[{CURRENT_BRANCH_COLOR}]{row_dict['branch']}[/{CURRENT_BRANCH_COLOR}]'
    row_dict['ahead'] = f'[{CURRENT_BRANCH_COLOR}]{row_dict['ahead']}[/{CURRENT_BRANCH_COLOR}]'
    row_dict['behind'] = f'[{CURRENT_BRANCH_COLOR}]{row_dict['behind']}[/{CURRENT_BRANCH_COLOR}]'

  if branch in ret['branches_with_merge_commits']:
    row_dict['ahead'] = f'{row_dict['ahead']} [{MERGE_COMMIT_COLOR}]M[/{MERGE_COMMIT_COLOR}]'

  if behind > 0:
    ret['branches_behind'].append(branch)

  return row_dict

def branch_name_from_sha_ref(sha_ref: StrShaRef) -> StrBranchName:
  """Returns the branch name sha_ref references"""
  return re.search(r'^\s*(.*?)(?:~\d+)?\s*$', sha_ref).group(1)

def local_branches_order(
  all_branches: list[StrBranchName],
  main_branch: StrBranchName,
  current_branch: StrBranchName,
  base_branches: dict[StrBranchName, tuple[StrShaRef, int]],
  short: bool
) -> list[StrBranchName]:
  """Defines what branches will be output in the table.

  Returns:
    An array of branch names. The first branch is guaranteed to be the main branch. The second
    branch is the current branch, unless the current branch is the main branch.
  """
  if short:
    dependent_branches: dict[StrBranchName, list[StrBranchName]] = {}
    for dependent_branch, (base_branch_ref, commit_count) in base_branches.items():
      base_branch = branch_name_from_sha_ref(base_branch_ref)
      dependent_branches[base_branch] = dependent_branches.get(base_branch, [])
      dependent_branches[base_branch].append(dependent_branch)

    queue: list[StrBranchName] = []
    queue_saw: set[StrBranchName] = set()
    ret = [main_branch]
    if current_branch not in ret:
      ret.append(current_branch)
      queue.append(current_branch)
      queue_saw.add(current_branch)

    while len(queue) > 0:
      branch = queue.pop()

      if branch in base_branches:
        branch_to_add = branch_name_from_sha_ref(base_branches[branch][0])
        if branch_to_add not in queue_saw:
          ret.append(branch_to_add)
          queue.append(branch_to_add)
          queue_saw.add(branch_to_add)

      if branch in dependent_branches:
        for branch_to_add in dependent_branches[branch]:
          if branch_to_add not in queue_saw:
            ret.append(branch_to_add)
            queue.append(branch_to_add)
            queue_saw.add(branch_to_add)
  else:
    ret = copy.deepcopy(all_branches)

    ret.remove(current_branch)
    ret.insert(0, current_branch)

    if main_branch in ret:
      ret.remove(main_branch)
      ret.insert(0, main_branch)

  return ret

def generate_amend_commands(
  current_branch: StrBranchName,
  no_push: bool,
  branches_deletable: list[StrBranchName],
  branches_ahead_shas: dict[StrBranchName, list[StrShaShort]],
  branches_with_merge_commits: list[StrBranchName],
  branches_safe_to_push: list[StrBranchName],
  **kwargs,
) -> list[StrCommand]:
  relevant_branches_ahead_shas: dict[StrBranchName, list[StrShaShort]] = {}
  for branch, shas in branches_ahead_shas.items():
    if branch == current_branch:
      continue

    if shas[:len(branches_ahead_shas[current_branch])] == branches_ahead_shas[current_branch]:
      relevant_branches_ahead_shas[branch] = shas[len(branches_ahead_shas[current_branch]):]

  return ['git commit --amend --no-edit'] + generate_update_commands(
    relevant_branches_ahead_shas.keys(),
    current_branch,
    no_push,
    branches_deletable,
    False,
    relevant_branches_ahead_shas.keys(),
    relevant_branches_ahead_shas,
    branches_with_merge_commits, # TODO: this probably needs to be recomputed
    branches_safe_to_push,
    True,
  )

def generate_update_commands(
  branches: list[StrBranchName],
  main_branch: StrBranchName,
  no_push: bool,
  branches_deletable: list[StrBranchName],
  unsynced_main: bool,
  branches_behind: list[StrBranchName],
  branches_ahead_shas: dict[StrBranchName, list[StrShaShort]],
  branches_with_merge_commits: list[StrBranchName],
  branches_safe_to_push: list[StrBranchName],
  main_branch_is_a_base_branch: bool = False,
  **kwargs,
) -> list[StrCommand]:
  """Creates and returns the list of git commands to run to update the branches."""
  update_commands = []

  branches_ahead_shas = copy.deepcopy(branches_ahead_shas)
  branches_to_rebase = []
  if unsynced_main:
    update_commands.append(f'git checkout {main_branch} && git pull')
    branches_behind = branches
  else:
    if len(branches_deletable) > 0:
      update_commands.append(f'git checkout {main_branch}')

  for branch in branches:
    if branch in branches_with_merge_commits:
      branches_ahead_shas.pop(branch, None)
      continue

    if branch in branches_behind and branch not in branches_deletable and branch != main_branch:
      branches_to_rebase.append(branch)

  for branch_to_delete in branches_deletable:
    update_commands.append(f'git branch -D {branch_to_delete}')

  if len(branches_to_rebase) > 0:
    for branch in branches_deletable:
      branches_ahead_shas.pop(branch, None)

    base_branches = base_branches_from_branches_ahead_refs(
      branches_ahead_shas_to_refs(branches_ahead_shas))

    rebased_branches = []

    for branch_to_rebase in rebase_order(base_branches) + branches_to_rebase:
      if branch_to_rebase not in branches_to_rebase or branch_to_rebase in rebased_branches:
        continue

      if branch_to_rebase in base_branches:
        base_branch, starting_from = base_branches[branch_to_rebase]
      elif main_branch_is_a_base_branch:
        base_branch = main_branch
        starting_from = len(branches_ahead_shas.get(branch_to_rebase, []))
      else:
        base_branch = main_branch
        starting_from = None

      update_commands.append(rebase_command(
        branch_to_rebase,
        base_branch,
        branches_safe_to_push,
        no_push,
        starting_from
      ))

      rebased_branches.append(branch_to_rebase)

  if len(update_commands) > 0:
    update_commands.append(f'git checkout {main_branch}')

  return update_commands

def rebase_command(
  branch_to_rebase: StrBranchName,
  base_branch: StrShaRef,
  branches_safe_to_push: list[StrBranchName] = [],
  no_push: bool = False,
  starting_from: int | None = None,
) -> StrCommand:
  """Returns the rebase command for `branch_to_rebase`."""
  ret = f'git checkout {branch_to_rebase}'

  if starting_from is None:
    ret += f' && git rebase {base_branch}'
  elif starting_from == 0:
    ret += f' && git reset --hard {base_branch}'
  else:
    ret += f' && git rebase --onto {base_branch} {branch_to_rebase}~{starting_from}'

  if branch_to_rebase in branches_safe_to_push and not no_push:
    ret += ' && git push -f'

  return ret

def branches_ahead_shas_to_refs(
  branches_ahead_shas: dict[StrBranchName, list[StrShaShort]]
) -> list[tuple[StrBranchName, list[StrShaRef]]]:
  """Converts a dictionary of branches and their ahead SHAs to a list of branch refs.

  Args:
    branches_ahead_shas (dict): Dictionary mapping branch names to lists of SHAs. For example:
      {
        'b2': ['38089'],
        'b3': ['38089', '42d83', '21d67'],
        'b5': ['b4a32', '31b9b'],
        'b6': ['b4a32', '31b9b', '975a7']
      }

  Returns:
    list: List of [branch, refs] pairs. For example:
      [
        ('b2', ['b2']),
        ('b5', ['b5~1', 'b5']),
        ('b3', ['b2', 'b3~1', 'b3']),
        ('b6', ['b5~1', 'b5', 'b6'])
      ]
  """
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
          ref = f'{branch}~{distance}'

        sha_to_ref[sha] = ref

      to_append[1].append(sha_to_ref[sha])

    branches_ahead_refs.append(to_append)

  return branches_ahead_refs

def rebase_order(base_branches: dict[StrBranchName, tuple[StrShaRef, int]]) -> list[StrBranchName]:
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
  branch: StrBranchName,
  base_branches: dict[StrBranchName, tuple[StrShaRef, int]]
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
    parent_branch = branch_name_from_sha_ref(base_branches[branch][0])
    ret = rebase_order_for(parent_branch, base_branches)
    ret.append(branch)
    return ret
  else:
    return [branch]

def base_branches_from_branches_ahead_refs(
  branches_ahead_refs: list[tuple[StrBranchName, list[StrShaRef]]]
) -> dict[StrBranchName, tuple[StrShaRef, int]]:
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
        "b3": ("b2", 2),
        "b6": ("b5", 1)
      }
  """
  ret = {}

  for branch, refs in branches_ahead_refs:
    commit_count = 0
    for ref in reversed(refs):
      parent_branch = re.search(r'^\s*(.*?)(?:~\d+)?\s*$', ref).group(1)
      if parent_branch != branch:
        ret[branch] = (ref, commit_count)
        break
      commit_count += 1

  return ret

def pull_request(branch: StrBranchName) -> dict | None:
  """Fetches the pull request for a given branch from the GitHub API.

  Assumes the envar `GITHUB_TOKEN` is set.

  See API documentation here:
  https://docs.github.com/en/rest/pulls/pulls?apiVersion=2022-11-28#list-pull-requests

  Args:
    branch (str): Branch name to look up.

  Returns:
    Pull request data if found, otherwise None.
  """
  git_utils = GitUtils()
  owner, repo = git_utils.owner_and_repo()

  if owner is None or repo is None:
    return None

  github_token = os.environ['GITHUB_TOKEN']
  params = urlencode({
    'head': f'{owner}:{branch}',
    'state': 'all'
  })

  response = requests.get(f'https://api.github.com/repos/{owner}/{repo}/pulls?{params}', headers = {
    'Accept': 'application/vnd.github+json',
    'Authorization': f'Bearer {github_token}',
    'X-GitHub-Api-Version': '2022-11-28'
  })

  pull_requests = response.json()
  if len(pull_requests) > 0:
    return pull_requests[0]
  else:
    return None

def prompt(question: str, default: bool | None = False) -> bool | None:
  valid = { 'yes': True, 'y': True, 'ye': True, 'no': False, 'n': False }

  while True:
    sys.stdout.write(question + { None: ' [y/n] ', True: ' [Y/n] ', False: ' [y/N] ' }[default])

    try:
      choice = input().lower().strip()
    except KeyboardInterrupt as exception:
      choice = 'no'

    if choice in valid:
      return valid[choice]
    elif choice == '' and default is not None:
      return default
    else:
      sys.stdout.write("Please respond with 'yes' or 'no' (or 'y' or 'n').\n")

if __name__ == "__main__":
  raise SystemExit(main())
