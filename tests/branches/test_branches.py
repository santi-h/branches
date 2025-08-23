import unittest
from src.branches.cli import (
  branches_ahead_shas_to_refs,
  rebase_order,
  base_branches_from_branches_ahead_refs,
  generate_update_commands
)

class TestBranches(unittest.TestCase):
  def test_branches_ahead_shas_to_refs(self):
    self.assertEqual(branches_ahead_shas_to_refs({
      'b2': ['38089'],
      'b3': ['38089', '42d83', '21d67'],
      'b4': ['38089', '42d83', '1f95c'],
      'b5': ['b4a32', '31b9b'],
      'b6': ['b4a32', '31b9b', '975a7'],
      'b7': ['b4a32', '31b9b', '975a7', '3d1a4'],
      'b8': ['b4a32', 'a2582'],
      'b9': ['b4a32', 'a2582']
    }), [
      ['b2', ['b2']],
      ['b5', ['b5~1', 'b5']],
      ['b8', ['b5~1', 'b8']],
      ['b9', ['b5~1', 'b8']],
      ['b3', ['b2', 'b3~1', 'b3']],
      ['b4', ['b2', 'b3~1', 'b4']],
      ['b6', ['b5~1', 'b5', 'b6']],
      ['b7', ['b5~1', 'b5', 'b6', 'b7']]
    ])

  def test_rebase_order(self):
    self.assertEqual(rebase_order({
      'b8': 'b5~1',
      'b9': 'b8',
      'b3': 'b2',
      'b4': 'b3~1',
      'b6': 'b5',
      'b7': 'b6'
    }), ['b5', 'b8', 'b9', 'b2', 'b3', 'b4', 'b6', 'b7'])

  def test_base_branches_from_branches_ahead_refs(self):
    self.assertEqual(base_branches_from_branches_ahead_refs([
      [ 'b2', ['b2'] ],
      [ 'b5', ['b5~1', 'b5'] ],
      [ 'b8', ['b5~1', 'b8'] ],
      [ 'b9', ['b5~1', 'b8'] ],
      [ 'b3', ['b2', 'b3~1', 'b3'] ],
      [ 'b4', ['b2', 'b3~1', 'b4'] ],
      [ 'b6', ['b5~1', 'b5', 'b6'] ],
      [ 'b7', ['b5~1', 'b5', 'b6', 'b7'] ]
    ]), {
      'b8': 'b5~1',
      'b9': 'b8',
      'b3': 'b2',
      'b4': 'b3~1',
      'b6': 'b5',
      'b7': 'b6'
    })

  def test_generate_update_commands(self):
    test_cases = [
      [
        {
          'branches': ['main', 'b5', 'b7', 'b6', 'test-branch-4', 'test-branch-1', 'test-branch-2', 'test-branch-3'],
          'main_branch': 'main',
          'no_push': False,
          'branches_deletable': ['test-branch-3'],
          'unsynced_main': False,
          'branches_behind': ['test-branch-1', 'test-branch-2', 'test-branch-3'],
          'branches_ahead_shas': {
            'b5': ['42792', 'd208f', 'dee9e', '48865', '3569e', '51348', '9e021', '69b22'],
            'b7': ['42792', '51348'],
            'b6': ['42792', '48865', '3569e'],
            'test-branch-4': ['c0022', '0893c'],
            'test-branch-1': ['d6833', 'd4a74', '912aa'],
            'test-branch-2': ['c20eb', 'e3480', '71e6e', '36ddf'],
            'test-branch-3': ['17e5e']
          },
          'branches_safely_pushable': ['main']
        }, [
          'git checkout main',
          'git branch -D test-branch-3',
          'git checkout b7 && git rebase main',
          'git checkout b6 && git rebase b7~1',
          'git checkout b5 && git rebase b7',
          'git checkout test-branch-1 && git rebase main',
          'git checkout test-branch-2 && git rebase main',
          'git checkout main'
        ]
      ], [
        {
          'branches': ['main', 'b8', 'b2', 'b3', 'b4', 'b5', 'b6', 'b7', 'b9', 'b1'],
          'main_branch': 'main',
          'no_push': False,
          'branches_deletable': [],
          'unsynced_main': False,
          'branches_behind': ['b8', 'b5', 'b6', 'b7', 'b9'],
          'branches_ahead_shas': {
            'b8': ['b4a32', 'a2582'],
            'b2': ['38089'],
            'b3': ['38089', '42d83', '21d67'],
            'b4': ['38089', '42d83', '1f95c'],
            'b5': ['b4a32', '31b9b'],
            'b6': ['b4a32', '31b9b', '975a7'],
            'b7': ['b4a32', '31b9b', '975a7', '3d1a4'],
            'b9': ['b4a32', 'a2582']
          },
          'branches_safely_pushable': []
        }, [
          'git checkout b5 && git rebase main',
          'git checkout b8 && git rebase b5~1',
          'git checkout b9 && git rebase b8',
          'git checkout b2 && git rebase main',
          'git checkout b3 && git rebase b2',
          'git checkout b4 && git rebase b3~1',
          'git checkout b6 && git rebase b5',
          'git checkout b7 && git rebase b6',
          'git checkout main'
        ]
      ]
    ]

    for test_case in test_cases:
      self.assertEqual(generate_update_commands(**test_case[0]), test_case[1])
