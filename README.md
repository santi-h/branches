# Branches

![screenshot](/docs/branches_screenshot.png)

Outputs two things:

1. **Branches info**: Alternative to `git branch`. Provides useful information about local branches.
2. **Branches update** operations: Outputs a list of `git` commands that the user can choose to run to get their branches up to date.

## Branches info

For each branch, `branches` outputs information that is usaully handy to have:

- Whether this branch is in `origin` or not
- If the branch is in `origin`, is it in sync or something needs to be pulled or pushed?
- If the branch is in `origin`, a handy link to the changes in github
- Whether there's commits authored by someone else other than the current git user
- Branch's last commit authored age in days
- Commits ahead/behind with respect to the main branch. Main branch = branch referenced by `git symbolic-ref refs/remotes/origin/HEAD`
- Base branch, in case the current branch branched off another one
- Whether this branch has a pull request
- If there is a pull request, the status of it
- If there is a pull request, a link to it

## Branches update operations

The script does not run any write `git` command. It only outputs suggested `git` operations. The user can decide to run the suggested operations. The goal of these commands is to keep branches up to date. More specifically:

- Clean up merged branches that are already on the main branch.
- Get all branches up to date (via `rebase`), respecting the tree structure.
    ```plain
                     branches
                     operations
                         ↓

                  N      >            N     <- branch3
                 /                   /
            K---L---M    >      K---L---M   <- branch2
           /                   /
          I---J          >    I---J         <- branch1
         /                   /
    A---B---C---E---F---G---H               <- main
    ```
- Push the branches that are currently in sync with `origin` and the current user is the only author.
- Safely pull updates that exist in `origin` but not locally

All suggestions are meant to be as safe as possible. For example, in order for it to suggest a branch to be deleted, all these conditions need to be satisfied:

- It is not the main branch
- A PR existed and was merged
- The merged sha is exactly the same as the local branch sha
- The branch was deleted in origin

The command that it outputs is a suggestion and the user makes the call whether to run it as is, change it and run it, or ignore it.

The update commands follow a no-merge approach. All update suggestions are `rebase` operations. If a branch contains merge commits, no rebase operation will ever be suggested for that branch.

## Assumptions and requirements

- This script was built on MacOS arm64 and was not tested in any other OS/Chip.
- `git` is installed in the system.
- The main remote is called `origin`. If there is no `origin` set the script will work but some features won't be available.
- `origin` points to GitHub using a SSH shorthand URL. For example `"git@github.com:santi-h/branches.git"` (I.e. no HTTPS)
- The envar `GITHUB_TOKEN` is set. This is needed for github to figure out whether there is a Pull Request for each branch. The token can be created at https://github.com/settings/tokens and needs the `repo` scope.

## Installation

```shell
/usr/bin/env bash -c "$(curl -fsSL https://raw.githubusercontent.com/santi-h/branches/main/scripts/install.sh)"
```

(see [installation script](/scripts/install.sh) for details)

## Uninstall

The installer only creates one persisted directory and a symbolic link pointing to a file in that persisted directory. So, to uninstall `branches` you can just remove both with:

```shell
rm "$HOME/.local/bin/branches"; rm -rf "$HOME/.local/opt/branches"
```

## Usage

In a git repo, just run `branches`

```shell
branches
```

## TODOs

- [ ] When main is ahead locally the cleanup command is suggesting to "git pull" main. In these cases a warning should be displayed and no update commands should be suggested. The user would have to either push their main branch changes first, or branch off them and drop the ahead commits.
- [ ] Test case when main is merged onto the local feature branch. When main moves on, should `branches` suggest rebase commands for the local feature branch?
- [ ] If multiple people added commits to a local feature branch, don't suggest rebasing.
- [ ] If the local feature branch can be fast forwarded to the remote sha, then suggest a `git pull` on that local feature branch. Then suggest a rebase if one needed. Handle edge case when local feature branch is 0 commits ahead.
- [ ] If local and remote have diverged, consider suggesting a `git rebase origin/feature-branch`.
- [ ] Investiage usage of [advanced search](https://docs.github.com/en/issues/tracking-your-work-with-issues/using-issues/filtering-and-searching-issues-and-pull-requests#building-advanced-filters-for-issues) to load PRs in bulk.

## Distribution Step 1: Create executable

```shell
rm -rf dist/ build/ && \
pip freeze | xargs pip uninstall -y && \
pip install -r requirements_lock.txt && \
pip install pyinstaller && \
pyinstaller --onedir --name branches --paths src src/branches/__main__.py && \
rm -rf build/
```

The last line could be replaced with `pyinstaller branches.spec`

## Distribution Step 2: Create Github Release

```shell
# from repo root after build
cd dist

VERSION=0.1.0

BASENAME=branches-macos-arm64-$VERSION && \
tar -czf $BASENAME.tar.gz -C branches . && \
shasum -a 256 $BASENAME.tar.gz > $BASENAME.sha256 && \
git tag v$VERSION && git push origin v$VERSION && \
open 'https://github.com/santi-h/branches/releases/new' && \
open .
```

Then on GitHub, go to [New Release](https://github.com/santi-h/branches/releases/new) and fill out the fields. Remember to upload the `.tar.gz` and `.sha256`.

For pre-releases, use versions with the following format examples:

- `VERSION=0.1.0-alpha`
- `VERSION=0.1.0-alpha.1`
- `VERSION=0.1.0-beta.3`
- `VERSION=0.1.0-rc.1`

Remember the precedence:
`0.1.0-alpha`< `0.1.0-alpha.1`< `0.1.0-beta.3`< `0.1.0-rc.1` < `0.1.0`

The first four are considered "pre-releases". For those, select the "Set as a pre-release" option in the Github UI.

If this is not a pre-release, move the `stable` branch to point to this release:

```shell
git checkout v$VERSION; git branch -D stable;
git checkout -b stable; git push origin stable -f
```
