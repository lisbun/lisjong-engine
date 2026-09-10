from __future__ import annotations

import importlib.util
import shlex
import sys
from pathlib import Path
from types import ModuleType

GUARD_PATH = Path(__file__).with_name("workflow_guard.py")
ACTIONS = {"direct-main-push", "commit-artifacts"}
GIT_GLOBAL_OPTIONS_WITH_VALUE = {
    "-C",
    "-c",
    "--attr-source",
    "--config-env",
    "--git-dir",
    "--namespace",
    "--super-prefix",
    "--work-tree",
}
GIT_GLOBAL_FLAG_OPTIONS = {
    "-p",
    "-P",
    "--bare",
    "--glob-pathspecs",
    "--icase-pathspecs",
    "--literal-pathspecs",
    "--no-lazy-fetch",
    "--no-optional-locks",
    "--no-pager",
    "--no-replace-objects",
    "--noglob-pathspecs",
    "--paginate",
}


def _load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("claude_workflow_guard", GUARD_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load workflow_guard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


def normalize_global_git_subcommand(command: str, subcommand: str) -> str | None:
    """Strip Git global options before a protected subcommand.

    This helper is used only by supplemental Hook matchers for commands whose
    first Git argument starts with '-'. Unknown global-option forms fail closed
    rather than silently bypassing a protected operation.
    """

    for segment in guard.SHELL_SEPARATORS.split(command):
        try:
            tokens = shlex.split(segment.strip(), posix=True)
        except ValueError as exc:
            raise guard.GuardError("Cannot safely parse Git global options.") from exc

        for git_index, token in enumerate(tokens):
            if token.lower() != "git":
                continue

            cursor = git_index + 1
            while cursor < len(tokens):
                token = tokens[cursor]
                lowered = token.lower()
                if lowered == subcommand:
                    return shlex.join(["git", subcommand, *tokens[cursor + 1 :]])
                if not token.startswith("-"):
                    break
                if token in GIT_GLOBAL_OPTIONS_WITH_VALUE:
                    if cursor + 1 >= len(tokens):
                        raise guard.GuardError(
                            "Git global option is missing its value."
                        )
                    cursor += 2
                    continue
                if token in GIT_GLOBAL_FLAG_OPTIONS:
                    cursor += 1
                    continue
                if "=" in token or token.startswith(("-C", "-c")):
                    cursor += 1
                    continue
                raise guard.GuardError(
                    f"Cannot safely classify Git global option before {subcommand}: {token}"
                )

    return None


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or args[0] not in ACTIONS:
        print(
            "usage: git_global_option_guard.py <direct-main-push|commit-artifacts>",
            file=sys.stderr,
        )
        return 2

    action = args[0]
    subcommand = "push" if action == "direct-main-push" else "commit"
    try:
        _tool_name, command, cwd = guard._read_hook_input()
        normalized = normalize_global_git_subcommand(command, subcommand)
        if normalized is None:
            return 0
        if action == "direct-main-push":
            guard._guard_direct_main_push(normalized, cwd)
        else:
            guard._guard_commit_artifacts(normalized, cwd)
    except guard.GuardError as exc:
        guard._deny(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
