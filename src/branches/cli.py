# Example usage:
# python branches.py
import argparse
import sys
from .utils.git_utils import GitUtils
import requests
import os
from urllib.parse import urlencode
from rich.console import Console
from rich import box
from rich.live import Live
from rich.table import Table
from datetime import datetime, timezone
import re

console = Console(highlight=False)

LOCAL_SHA_COLOR = 'blue'
CURRENT_BRANCH_COLOR = 'green'

# Starting with Python 3.7, dictionaries officially maintain the order in which keys were inserted
# The logic in this script assumes this is the case.
COLUMNS = {
  'origin': {
    'column_name': 'Origin',
    'column_props': { 'no_wrap': True, 'justify': 'right' }
  },
  'local': {
    'column_name': 'Local',
    'column_props': { 'no_wrap': True, 'justify': 'left', 'style': f'{LOCAL_SHA_COLOR}', 'header_style': f'{LOCAL_SHA_COLOR}' }
  },
  'age': {
    'column_name': 'Age',
    'column_props': { 'justify': 'right', 'style': f'{LOCAL_SHA_COLOR}', 'header_style': f'{LOCAL_SHA_COLOR}' }
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

def main():
  parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
  parser.add_argument('-s', '--short', action='store_true', default=False, help='Show a short list only')
  parser.add_argument('--no-push', action='store_true', default=False, help='Do not add push commands')
  sys.exit(branches(parser.parse_args()))

def branches(args):
  # header_style="" removes the bold which makes assigning a yellow header not work
  table = Table(box=box.SIMPLE_HEAD, header_style="")
  for _column_key, column_attr in COLUMNS.items():
    table.add_column(column_attr['column_name'], **(column_attr['column_props'] or {}))

  print(f'Current user email: {GitUtils().current_user_email()}')
  with Live(table, console=console, refresh_per_second=20):
    update_commands_params = print_table(args, table)

  update_commands = generate_update_commands(**update_commands_params)
  if len(update_commands) > 0:
    print('')
    print(' && \\\n'.join(update_commands))

'''
Prints out on a table the state of all local branches
Outputs a dictionary with the required arguments to generate an update command
'''
def print_table(args, table):
  git_utils = GitUtils()
  owner, repo = git_utils.owner_and_repo()
  main_branch = git_utils.main_branch()
  # TODO: handle case when `main_branch` is not a local branch. Should exit right away
  if args.short:
    branches = [main_branch]
    if git_utils.current_branch() not in branches:
      branches.append(git_utils.current_branch())
  else:
    branches = git_utils.branches()
    # Always keep the main branch first and the current branch second

    branches.remove(git_utils.current_branch())
    branches.insert(0, git_utils.current_branch())

    if main_branch in branches:
      branches.remove(main_branch)
      branches.insert(0, main_branch)

  ret = {
    'branches': branches,
    'main_branch': main_branch,
    'no_push': args.no_push,
    'branches_deletable': [],
    'unsynced_main': False,
    'branches_behind': [],
    'branches_ahead_shas': {},
    'branches_safely_pushable': []
  }

  # Calculate branch_dependencies_chains
  for branch in branches:
    if branch != main_branch and int(git_utils.distance(branch, main_branch)[0]) > 0:
      ret['branches_ahead_shas'][branch] = [
        sha[:5] for sha in git_utils.shas_ahead_of(main_branch, branch)]

  base_branches = base_branches_from_branches_ahead_refs(
    branches_ahead_shas_to_refs(ret['branches_ahead_shas']))

  remote_shas = git_utils.remote_shas(branches)
  for branch in branches:
    row_dict = {} # valid keys are those of `COLUMNS``

    sync_status = 'not_pushed'

    local_commit = git_utils.local_commit_from_branch(branch)
    local_sha = str(local_commit)
    local_sha_short = local_sha[:5]
    local_author_email = git_utils.commit_author_email(local_sha)

    remote_commit = None
    remote_sha = remote_shas.get(branch)
    remote_sha_short = '     '
    remote_author_email = None

    if remote_sha is not None:
      remote_sha_short = remote_sha[:5]
      if remote_sha == local_sha:
        sync_status = 'synced'
      else:
        remote_commit = git_utils.local_commit_from_sha(remote_sha)
        if remote_commit is None:
          remote_commit = git_utils.fetch_sigle_sha(remote_sha)

        sync_status = 'unsynced'
        if branch == main_branch:
          ret['unsynced_main'] = True

      remote_author_email = git_utils.commit_author_email(remote_sha)

    if branch in base_branches:
      row_dict['base'] = base_branches[branch]

    pr = pull_request(branch)
    if pr is not None and branch != main_branch:
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

      row_dict['pr'] = f'[link={pr['html_url']}][{PR_STATUS_COLORS[pr_status]}]#{pr['number']}[/{PR_STATUS_COLORS[pr_status]}][/link] ({pr_sha}) by {pr['user']['login']}'

      if pr_status == 'merged' and pr_sha_status == 'synced' and sync_status == 'not_pushed':
        # Only delete if all of these are true:
        # - This is not the main branch
        # - The PR was merged
        # - The merged code is exactly the same as our local branch
        # - The branch was deleted in origin
        ret['branches_deletable'].append(branch)

    ahead, behind = git_utils.distance(branch, main_branch)

    ###########################################################################
    # Populate different_author_flag, and message_remote_sha
    ###########################################################################
    different_author_flag = ' '
    if sync_status == 'synced':
      message_remote_sha = f'[{LOCAL_SHA_COLOR}]{remote_sha_short}[/{LOCAL_SHA_COLOR}]'
    elif sync_status == 'unsynced':
      if remote_commit.committed_date < local_commit.committed_date:
        message_remote_sha = f'[dim]{remote_sha_short}[/dim]'
      else:
        message_remote_sha = f'[bold]{remote_sha_short}[/bold]'

      if git_utils.commit_author_email(remote_sha) != git_utils.current_user_email():
        different_author_flag = '[yellow]![/yellow]'
    else:
      message_remote_sha = remote_sha_short

    if sync_status in ['synced', 'unsynced'] and branch != main_branch:
      message_remote_sha = f'[link=https://github.com/{owner}/{repo}/compare/{main_branch}...{branch}]{message_remote_sha}[/link]'

    row_dict['origin'] = message_remote_sha
    row_dict['local'] = local_sha_short
    row_dict['age'] = str((datetime.now(timezone.utc) - git_utils.date_authored(local_sha)).days)
    if branch == git_utils.current_branch():
      row_dict['branch'] = f'[{CURRENT_BRANCH_COLOR}]{branch}[/{CURRENT_BRANCH_COLOR}]'
      row_dict['ahead'] = f'[{CURRENT_BRANCH_COLOR}]{ahead}[/{CURRENT_BRANCH_COLOR}]'
      row_dict['behind'] = f'[{CURRENT_BRANCH_COLOR}]{behind}[/{CURRENT_BRANCH_COLOR}]'
    else:
      row_dict['branch'] = branch
      row_dict['ahead'] = ahead
      row_dict['behind'] = behind

    if int(behind) > 0:
      ret['branches_behind'].append(branch)

    if sync_status == 'synced' and git_utils.current_user_email() == git_utils.commit_author_email(local_sha):
      ret['branches_safely_pushable'].append(branch)

    table.add_row(*[row_dict.get(column_key) for column_key in COLUMNS.keys()])

  return ret

def generate_update_commands(branches_deletable, main_branch, unsynced_main, branches,
                             branches_behind, branches_ahead_shas, branches_safely_pushable,
                             no_push):
  update_commands = []

  if unsynced_main:
    update_commands.append(f'git checkout {main_branch} && git pull')
    branches_to_rebase = [branch for branch in branches if branch != main_branch and branch not in branches_deletable]
  else:
    if len(branches_deletable) > 0:
      update_commands.append(f'git checkout {main_branch}')
    branches_to_rebase = [branch for branch in branches_behind if branch not in branches_deletable]

  for branch_to_delete in branches_deletable:
    update_commands.append(f'git branch -D {branch_to_delete}')

  if len(branches_to_rebase) > 0:
    for branch in branches_deletable:
      branches_ahead_shas.pop(branch, None)

    base_branches = base_branches_from_branches_ahead_refs(
      branches_ahead_shas_to_refs(branches_ahead_shas))

    rebased_branches = []

    for branch_to_rebase in rebase_order(base_branches) + branches_to_rebase:
      if branch_to_rebase in rebased_branches:
        continue
      base_branch = base_branches.get(branch_to_rebase, main_branch)
      cmd = rebase_command(branch_to_rebase, base_branch, branches_safely_pushable, no_push)
      update_commands.append(cmd)
      rebased_branches.append(branch_to_rebase)

  if len(update_commands) > 0:
    update_commands.append(f'git checkout {main_branch}')

  return update_commands

def rebase_command(branch_to_rebase, base_branch, branches_safely_pushable = [], no_push = False):
  ret = f'git checkout {branch_to_rebase} && git rebase {base_branch}'

  if branch_to_rebase in branches_safely_pushable and not no_push:
    ret += ' && git push -f'

  return ret

'''
{
  "b2": ["38089"],
  "b3": ["38089", "42d83", "21d67"],
  "b4": ["38089", "42d83", "1f95c"],
  "b5": ["b4a32", "31b9b"],
  "b6": ["b4a32", "31b9b", "975a7"],
  "b7": ["b4a32", "31b9b", "975a7", "3d1a4"],
  "b8": ["b4a32", "a2582"],
  "b9": ["b4a32", "a2582"]
}

[
  [ "b2", ["b2"] ],
  [ "b5", ["b5~1", "b5"] ],
  [ "b8", ["b5~1", "b8"] ],
  [ "b9", ["b5~1", "b8"] ],
  [ "b3", ["b2", "b3~1", "b3"] ],
  [ "b4", ["b2", "b3~1", "b4"] ],
  [ "b6", ["b5~1", "b5", "b6"] ],
  [ "b7", ["b5~1", "b5", "b6", "b7"] ]
]
'''
def branches_ahead_shas_to_refs(branches_ahead_shas):
  branches_ahead_refs = []
  sha_to_ref = {}

  for branch, shas in sorted(branches_ahead_shas.items(), key=lambda x: (len(x[1]), x[0])):
    to_append = [branch, []]

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

'''
Sample format of `base_branches`:
{
  "b8": "b5~1",
  "b9": "b8",
  "b3": "b2",
  "b4": "b3~1",
  "b6": "b5",
  "b7": "b6"
}

Sample format of return:
["b5", "b8", "b9", "b2", "b3", "b4", "b6", "b7"]
'''
def rebase_order(base_branches):
  ret = []

  for branch in base_branches.keys():
    for branch_to_rebase in rebase_order_for(branch, base_branches):
      if branch_to_rebase not in ret:
        ret.append(branch_to_rebase)

  return ret

'''
Sample format of `base_branches`:
{
  "b8": "b5~1",
  "b9": "b8",
  "b3": "b2",
  "b4": "b3~1",
  "b6": "b5",
  "b7": "b6"
}

Sample `branch`: "b4"

Sample return:
["b2", "b3", "b4"]
'''
def rebase_order_for(branch, base_branches):
  if branch in base_branches:
    parent_branch = re.search(r'^\s*(.*?)(?:~\d+)?\s*$', base_branches[branch]).group(1)
    ret = rebase_order_for(parent_branch, base_branches)
    ret.append(branch)
    return ret
  else:
    return [branch]

'''
Sample format of `branches_ahead_refs`
[
  [ "b2", ["b2"] ],
  [ "b5", ["b5~1", "b5"] ],
  [ "b8", ["b5~1", "b8"] ],
  [ "b9", ["b5~1", "b8"] ],
  [ "b3", ["b2", "b3~1", "b3"] ],
  [ "b4", ["b2", "b3~1", "b4"] ],
  [ "b6", ["b5~1", "b5", "b6"] ],
  [ "b7", ["b5~1", "b5", "b6", "b7"] ]
]

Sample format return:
{
  "b8": "b5~1",
  "b9": "b8",
  "b3": "b2",
  "b4": "b3~1",
  "b6": "b5",
  "b7": "b6"
}
'''
def base_branches_from_branches_ahead_refs(branches_ahead_refs):
  ret = {}

  for branch, refs in branches_ahead_refs:
    for ref in reversed(refs):
      parent_branch = re.search(r'^\s*(.*?)(?:~\d+)?\s*$', ref).group(1)
      if parent_branch != branch:
        ret[branch] = ref
        break

  return ret

# https://docs.github.com/en/rest/pulls/pulls?apiVersion=2022-11-28#list-pull-requests
def pull_request(branch):
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

if __name__ == "__main__":
  main()
