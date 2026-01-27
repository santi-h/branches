# Branches

[![CI](https://github.com/santi-h/branches/actions/workflows/ci.yml/badge.svg)](https://github.com/santi-h/branches/actions/workflows/ci.yml?query=branch%3Amain)

![screenshot](/docs/branches_screenshot.png)

Used for three purposes:

1. [**Getting relevant branches info**](#purpose-1-getting-relevant-branches-info): Alternative to `git branch`. Provides useful information about local branches.
2. [**Keeping branches up to date**](#purpose-2-keeping-branches-up-to-date): Outputs a list of `git` commands that the user can choose to run to catch up their branches to the main branch.
3. [**Helping amend commits while keeping the tree structure intact**](#purpose-3-helping-amend-commits-while-keeping-the-tree-structure-intact): Outputs a list of `git` commands that the user can choose to run to amend the last commit and keep the tree structure of all dependent branches intact.

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
branches --help
```

## Assumptions and requirements

- This script was built on MacOS arm64 and was not tested in any other OS/Chip.
- `git` is installed in the system.
- The main remote is called `origin`. If there is no `origin` set the script will work but some features won't be available.
- `origin` points to GitHub using a SSH shorthand URL. For example `"git@github.com:santi-h/branches.git"` (I.e. no HTTPS)
- The envar `GITHUB_TOKEN` is set. This is needed for github to figure out whether there is a Pull Request for each branch. The token can be created at https://github.com/settings/tokens and needs the `repo` scope.

## Purpose 1: Getting relevant branches info

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

## Purpose 2: Keeping branches up to date

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

## Purpose 3: Helping amend commits while keeping the tree structure intact

Let's say we have a structure like this:

```plain
    D---E   <- branch2
   /
  C         <- branch1
 /
A---B       <- main
```

`branch2` depends on `branch1`.

Let's say you're on `branch1` and realized a line should be moved 3 lines down. You don't want to create another commit for this, so you want to amend `C` with `git commit --amend`.

The process for this can be involved:

- You make the code change while on `branch1` and run `git add . && git commit --amend --no-edit`. Now you have a structure like this:

    ```plain
      D---E <- branch2
     /
    C G     <- branch1
    |/
    A---B   <- main
    ```

    i.e. you created a separate commit `G` and `branch2` not only no longer depends on `branch1`, but it also didn't get the update. So,

- You now have to rebase `branch2`, but this rebase is not super trivial. If you run `git checkout branch2 && git rebase branch1` there's a high likelyhood of a conflict. So, there's a manual step involved. You might be tempted to run `git rebase branch1 -X ours` to automatically resolve the conflict by accepting the change in `branch1`, but this not always results in what you expect. To understand why this sometimes doesn't work try the following in a throwaway new directory:

    ```shell
    git init &&
    echo "line1\nline2\nline3\nline4\nline5\nline7\nline8" > testfile.txt &&
    git add testfile.txt && git commit -m A &&
    git checkout -b branch1

    # ... Replace "line4" in testfile.txt with "line4 changed by branch1"

    git add testfile.txt && git commit -m C &&
    git checkout -b branch2

    # ... Replace "line2" in testfile.txt with "line2 changed by branch2"

    git add testfile.txt && git commit -m D

    # ... Replace "line2 changed by branch2" in testfile.txt with "line2 changed by branch2 again"

    git add testfile.txt && git commit -m E
    ```

    At this point we have our `branch1` and `branch2`. This is what `testfile.txt` looks for each one

    ```plain
    testfile.txt on branch1:                testfile.txt on branch2:
    +--------------------------------+      +--------------------------------+
    | line1                          |      | line1                          |
    | line2                          |      | line2 changed by branch2 again |
    | line3                          |      | line3                          |
    | line4 changed by branch1       |      | line4 changed by branch1       |
    | line5                          |      | line5                          |
    | line7                          |      | line7                          |
    | line8                          |      | line8                          |
    +--------------------------------+      +--------------------------------+

    Our branch structure at the moment:

        D---E   <- branch2
       /
      C         <- branch1
     /
    A           <- main
    ```

    Let's amend our `testfile.txt` in `branch1`

    ```shell
    git checkout branch1

    # ... Replace "line4 changed by branch1" in testfile.txt with "line4"
    # ... Replace "line7" in testfile.txt with "line7 changed by branch1"

    git add testfile.txt && git commit --amend -m "G" # `-m "G"` to show that this creates a separate commit. In practice I usually keep the message with `git commit --amend --no-edit`.
    ```

    The current state now is

    ```plain
    testfile.txt on branch1:                testfile.txt on branch2:
    +--------------------------------+      +--------------------------------+
    | line1                          |      | line1                          |
    | line2                          |      | line2 changed by branch2 again |
    | line3                          |      | line3                          |
    | line4                          |      | line4 changed by branch1       |
    | line5                          |      | line5                          |
    | line7 changed by branch1       |      | line7                          |
    | line8                          |      | line8                          |
    +--------------------------------+      +--------------------------------+

    Our branch structure at the moment:

      D---E   <- branch2
     /
    C G       <- branch1
    |/
    A         <- main
    ```

    If we try to `git checkout branch2 && git rebase branch1` this is what we would get:

    ```plain
    testfile.txt on branch1:                testfile.txt on branch2:
    +--------------------------------+      +--------------------------------+
    | line1                          |      | line1                          |
    | line2                          |      | line2 changed by branch2 again |
    | line3                          |      | line3                          |
    | line4                          |      | line4 changed by branch1       |
    | line5                          |      | line5                          |
    | line7 changed by branch1       |      | line7 changed by branch1       |
    | line8                          |      | line8                          |
    +--------------------------------+      +--------------------------------+

    Our branch structure:

        D---E   <- branch2
       /
      C
      |
      G       <- branch1
     /
    A         <- main
    ```

    Definitely not what we wanted to accomplish

The problem is that doing `git rebase branch1` is going to replay commit `C` on top of `G`. You don't want that. What you want is to ignore commit `C` and replay commits `D` and `E` on top of `G`, and let that be your new `branch2`. One way to do this is a bit more complicated, with `git rebase --onto branch1 branch2~2`. This replays commits `D` and `E` on top of `G` and the result is what you would expect:

```plain
testfile.txt on branch1:                testfile.txt on branch2:
+--------------------------------+      +--------------------------------+
| line1                          |      | line1                          |
| line2                          |      | line2 changed by branch2 again |
| line3                          |      | line3                          |
| line4                          |      | line4                          |
| line5                          |      | line5                          |
| line7 changed by branch1       |      | line7 changed by branch1       |
| line8                          |      | line8                          |
+--------------------------------+      +--------------------------------+

Our branch structure:

    D---E <- branch2
   /
  G       <- branch1
 /
A         <- main
```

This is what `branches` helps with:

```plain
$ branches amend

  Origin   Local    Age   <-   ->   Branch    Base      PR
 ──────────────────────────────────────────────────────────
           a4424      0    0   0    main
           ab2b9      0    0   1    branch1
           ed908      0    0   3    branch2   branch1


git add . && git commit --amend --no-edit && \
git checkout branch2 && git rebase --onto branch1 branch2~2 && \
git checkout branch1

Run update command? [y/N]
```

This is a trivial example. In practice it gets messier, there might be a lot more branches involved, and you might need to push the changes to origin.

## Development: setup

I recommend setting up:

- [`direnv`](https://direnv.net)
- [`pyenv`](https://formulae.brew.sh/formula/pyenv) + [`pyenv-virtualenv`](https://formulae.brew.sh/formula/pyenv-virtualenv)

Steps:

- Create virtualenv:

```shell
pyenv virtualenv `cat .python-version` branches
```

- Set direnv so every time you `cd` into this directory it uses the virtualenv created above:

```shell
echo 'export PYENV_VERSION=branches' > .envrc
```

(allow if prompted)

- Install `pip-tools` with `pip install -U pip-tools`. See [`pip-tools` docs](https://pypi.org/project/pip-tools).

- Install `pypi` dependencies:

```shell
pip-sync requirements-dev.txt
```

## Development: dependencies

To upgrade all dependencies:

```shell
pip-compile --output-file=requirements.txt requirements.in --upgrade &&
pip-compile --output-file=requirements-dev.txt requirements-dev.in --upgrade
```

When adding/removing dependencies to the `.in` files:

```shell
pip-compile --output-file=requirements.txt requirements.in &&
pip-compile --output-file=requirements-dev.txt requirements-dev.in
```

## Development: clean slate

Assuming `.envrc` stays

```shell
pyenv virtualenv-delete -f branches &&
pyenv virtualenv `cat .python-version` branches &&
pip install -U pip-tools
```

## Development: running tests

To run all tests:

```shell
pytest
```

To run a specific file:

```shell
pytest -k test_branches.py
```

To run a specific test:

```shell
pytest -k test_generate_update_commands
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
pyinstaller --onedir --name branches --paths src src/branches/__main__.py && \
rm -rf build/
```

The second to last line could be replaced with `pyinstaller branches.spec`

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
