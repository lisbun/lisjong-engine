from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / ".claude" / "hooks" / "git_global_option_guard.py"
SPEC = importlib.util.spec_from_file_location(
    "claude_git_global_option_guard", HELPER_PATH
)
assert SPEC is not None and SPEC.loader is not None
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


class GitGlobalOptionGuardTests(unittest.TestCase):
    def test_normalizes_global_options_before_push(self) -> None:
        commands = {
            "git --no-pager push origin main": "git push origin main",
            "git -c push.default=simple push origin main": "git push origin main",
            "echo ok && git -C repo push origin HEAD:main": "git push origin HEAD:main",
        }
        for command, expected in commands.items():
            with self.subTest(command=command):
                self.assertEqual(
                    expected,
                    helper.normalize_global_git_subcommand(command, "push"),
                )

    def test_normalizes_global_options_before_commit(self) -> None:
        self.assertEqual(
            "git commit -am test",
            helper.normalize_global_git_subcommand(
                "git -c user.name=test commit -am test",
                "commit",
            ),
        )

    def test_does_not_reclassify_another_git_subcommand(self) -> None:
        self.assertIsNone(
            helper.normalize_global_git_subcommand(
                "git --no-pager log push",
                "push",
            )
        )

    def test_normalized_global_option_push_is_blocked(self) -> None:
        normalized = helper.normalize_global_git_subcommand(
            "git --no-pager push origin main",
            "push",
        )
        assert normalized is not None
        self.assertTrue(
            helper.guard.is_direct_main_push(
                normalized,
                "issue-58-claude-workflow-rollout",
            )
        )

    def test_unknown_global_option_fails_closed(self) -> None:
        with self.assertRaises(helper.guard.GuardError):
            helper.normalize_global_git_subcommand(
                "git --future-option push origin main",
                "push",
            )


if __name__ == "__main__":
    unittest.main()
