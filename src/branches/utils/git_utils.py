import os
import git
from git import Commit
import re

class GitUtils:
  def __init__(self, repo_path = os.getcwd()):
    while True:
      try:
        self._repo = git.Repo(repo_path)
        break
      except git.exc.InvalidGitRepositoryError as e:
        if len(repo_path) > 1:
          repo_path = os.path.dirname(repo_path)
        else:
          raise e

    self._repo_path = repo_path
    self._cmd = git.cmd.Git(repo_path)
    self._git = self._repo.git
    self._current_branch = None
    self._owner_name = None
    self._repo_name = None

  def owner_and_repo(self):
    if self._owner_name and self._repo_name:
      return self._owner_name, self._repo_name

    remotes = self._cmd.execute(['git', 'remote', '-v'])
    match = re.search(r'github\.com(?::|\/)([\w\-]+)\/([\w\-]+)\.git \(fetch\)', remotes)
    if match is not None:
      self._owner_name = match.group(1)
      self._repo_name = match.group(2)

    return self._owner_name, self._repo_name

  def current_branch(self):
    if self._current_branch:
      return self._current_branch

    if self._repo.head.is_detached:
      return None

    self._current_branch = str(self._repo.active_branch)

    return self._current_branch

  def branches(self):
    branches = self._cmd.execute(['git', 'branch']).split('\n')
    return [branch.replace('*', '').strip() for branch in branches if branch]

  def local_sha_from_branch(self, branch: str | None = None) -> str:
    return str(self.local_commit_from_branch(branch))

  def local_commit_from_branch(self, branch: str) -> Commit:
    return self._repo.branches[branch].commit

  def local_commit_from_sha(self, sha):
    ret = None

    try:
     ret = self._repo.commit(sha)
    except ValueError as exception:
      # Sha doesn't exist locally. Ignore and return None
      pass

    return ret

  def fetch_sigle_sha(self, sha):
    self._repo.remotes.origin.fetch(sha)
    return self.local_commit_from_sha(sha)

  def remote_shas(self, branches) -> dict[str, str]:
    ret = {}

    try:
      ls_remote_output = self._cmd.execute(['git', 'ls-remote', 'origin', *branches])
    except git.exc.GitCommandError as exception:
      # origin doesn't exist
      return {}

    for line in ls_remote_output.split('\n'):
      result = re.search(r'^(\w+)\s+refs\/heads\/(.*)$', line)
      if result is not None:
        ret[result.group(2)] = result.group(1)

    return ret

  def distance(self, branch_from, branch_to) -> tuple[int, int]:
    result = self._cmd.execute(['git', 'rev-list', '--left-right', '--count', f'{branch_from}...{branch_to}'])
    result = re.split(r'\s+', result.strip())
    return (int(result[0]), int(result[1]))

  def parent_shas_of_ref(self, ref: str, n: int = 1) -> list[list[str]]:
    """Returns the parent shas of `ref`, going at most `n` levels deep

    Returns a list. Each element in the list is a level. Each level is a list of strings where each
    string is a sha. The first element in a level is always the sha itself, and the rest of the
    elements are the parents of that sha.
    """
    ret = []

    command = ['git', 'rev-list', '--parents', f'-n{n}', ref, '--']
    for line in self._cmd.execute(command).split('\n'):
      ret.append(re.split(r'\s+', line.strip()))

    return ret

  def main_branch(self):
    try:
      origin_ref = self._repo.refs['origin/HEAD']
    except IndexError as exception:
      for branch in ['main', 'release', 'master']:
        if branch in self._repo.branches:
          return branch

      raise exception

    origin_head = origin_ref.reference.name
    return re.search(r'\/([^\/]+?)\s*$', origin_head).group(1)

  def shas_ahead_of(self, branch_from, branch_to) -> list[str]:
    result = self._cmd.execute(['git', 'log', f'{branch_from}..{branch_to}', '--format=%H', '--reverse'])
    return [sha for sha in re.split(r'\s+', result.strip()) if sha.strip()]

  def current_user_email(self) -> str:
    return self._cmd.execute(['git', 'config', 'user.email']).strip()

  def commit_author_email(self, sha):
    return self._cmd.execute(['git', 'show', '--format=%ae', '--no-patch', sha]).strip()

  def date_authored(self, sha):
    return self.local_commit_from_sha(sha).authored_datetime

  def date_committed(self, sha):
    return self.local_commit_from_sha(sha).committed_datetime
