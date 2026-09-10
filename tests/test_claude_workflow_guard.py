from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / ".claude" / "hooks" / "workflow_guard.py"
SPEC = importlib.util.spec_from_file_location("claude_workflow_guard", GUARD_PATH)
assert SPEC is not None and SPEC.loader is not None
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class DirectMainPushTests(unittest.TestCase):
    def test_allows_feature_branch_push(self) -> None:
        self.assertFalse(
            guard.is_direct_main_push(
                "git push -u origin issue-58-claude-workflow-rollout",
                "issue-58-claude-workflow-rollout",
            )
        )

    def test_blocks_default_push_from_main(self) -> None:
        self.assertTrue(guard.is_direct_main_push("git push", "main"))

    def test_blocks_explicit_main_refspecs(self) -> None:
        commands = [
            "git push origin main",
            "git push origin HEAD:main",
            "git push origin HEAD:refs/heads/main",
            "git push --repo origin main",
            "git push --repo=origin HEAD:main",
            "git push origin :main",
            "git push origin --delete main",
            "git push --all origin",
            "git push --mirror origin",
            "echo ok && git push origin main",
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(
                    guard.is_direct_main_push(
                        command,
                        "issue-58-claude-workflow-rollout",
                    )
                )

    def test_blocks_head_alias_pushes_from_main(self) -> None:
        for command in ("git push origin HEAD", "git push origin @"):
            with self.subTest(command=command):
                self.assertTrue(guard.is_direct_main_push(command, "main"))

    def test_does_not_treat_remote_named_main_as_main_ref(self) -> None:
        self.assertFalse(
            guard.is_direct_main_push(
                "git push main",
                "issue-58-claude-workflow-rollout",
            )
        )

    def test_allows_non_updating_push_modes_from_main(self) -> None:
        for command in ("git push --dry-run origin main", "git push --tags origin"):
            with self.subTest(command=command):
                self.assertFalse(guard.is_direct_main_push(command, "main"))

    def test_ignores_non_push_command(self) -> None:
        self.assertFalse(guard.is_direct_main_push("git status", "main"))


class ForbiddenPathTests(unittest.TestCase):
    def test_rejects_credential_and_model_artifact_classes(self) -> None:
        paths = [
            ".env",
            ".envrc",
            ".pypirc",
            "config/.env.production",
            "keys/id_ed25519",
            "keys/private.key",
            "certs/client.pem",
            "model/checkpoint.ckpt",
            "model/policy.pt",
            "model/policy.pth",
            "model/policy.onnx",
            "model/policy.safetensors",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(guard.is_forbidden_path(path))

    def test_allows_documented_env_templates_and_normal_source(self) -> None:
        paths = [
            ".env.example",
            ".env.sample",
            ".env.template",
            "src/lisjong_engine/game.py",
            "tests/test_game.py",
            "docs/architecture.md",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertFalse(guard.is_forbidden_path(path))


class GitInspectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp_dir.name)
        subprocess.run(["git", "init"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.invalid"],
            cwd=self.repo,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=self.repo,
            check=True,
        )
        (self.repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        (self.repo / ".env.example").write_text("TOKEN=\n", encoding="utf-8")
        subprocess.run(["git", "add", "."], cwd=self.repo, check=True)
        subprocess.run(
            ["git", "commit", "-m", "base"],
            cwd=self.repo,
            check=True,
            capture_output=True,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_candidate_commit_paths_include_staged_files(self) -> None:
        secret = self.repo / ".env.production"
        secret.write_text("not-a-real-secret\n", encoding="utf-8")
        subprocess.run(
            ["git", "add", "-f", ".env.production"],
            cwd=self.repo,
            check=True,
        )

        paths = guard._candidate_commit_paths(self.repo, "git commit -m test")

        self.assertIn(".env.production", paths)

    def test_commit_all_also_inspects_tracked_worktree_changes(self) -> None:
        tracked = self.repo / "tracked.txt"
        tracked.write_text("changed\n", encoding="utf-8")

        paths = guard._candidate_commit_paths(self.repo, "git commit -am test")

        self.assertIn("tracked.txt", paths)


class PrePrGateTests(unittest.TestCase):
    def test_pre_pr_gate_uses_lightweight_checks_only(self) -> None:
        with (
            mock.patch.object(guard, "_find_base_ref", return_value="main"),
            mock.patch.object(guard, "_git_output", return_value="abc123\n"),
            mock.patch.object(guard, "_branch_changed_paths", return_value=[]),
            mock.patch.object(guard, "_run_check") as run_check,
        ):
            guard._guard_pre_pr(Path("."))

        commands = [call.args[1] for call in run_check.call_args_list]
        self.assertIn(["git", "diff", "--check", "abc123..HEAD"], commands)
        self.assertIn(
            [sys.executable, "-m", "ruff", "format", "--check", "."],
            commands,
        )
        self.assertIn([sys.executable, "-m", "ruff", "check", "."], commands)
        flattened = " ".join(" ".join(command) for command in commands)
        self.assertNotIn("unittest", flattened)
        self.assertNotIn("pytest", flattened)


class HookInputTests(unittest.TestCase):
    def test_malformed_input_denies_protected_operation(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(GUARD_PATH), "direct-main-push"],
            input="{not-json",
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, completed.returncode)
        payload = json.loads(completed.stdout)
        output = payload["hookSpecificOutput"]
        self.assertEqual("PreToolUse", output["hookEventName"])
        self.assertEqual("deny", output["permissionDecision"])


if __name__ == "__main__":
    unittest.main()
