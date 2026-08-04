# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""
Migrate a project from the ``obo_`` tool names to ``oboe_`` (v0.3.0+).

The 0.3.0 release renamed every MCP tool from ``obo_*`` to ``oboe_*`` and the
session directory from ``.github/obo_sessions/`` to ``.github/oboe_sessions/``.
This module rewrites a consuming project to match.

This is the only implementation.  It replaced a shell script,
``inst/migrate-to-oboe.sh``, which shipped in neither the sdist nor the wheel
— so nobody installing from PyPI had it — and which had rotted into
depending on ``declare -A``, GNU ``sed -i`` and ``md5sum``, none of which
exist on a stock macOS.  The script was removed rather than repaired: a
second implementation of the same rewrite rules can only drift, and anyone
able to run oboe-mcp already has Python.

Deliberately imports nothing beyond the standard library, and nothing from
the rest of this package.  ``python -m oboe_mcp.migrate`` therefore works
against a bare source checkout with no dependencies installed at all — not
even the MCP SDK.

The operation is idempotent: running it twice is safe and the second run
reports nothing to change.

Entry points:
    oboe-mcp migrate [PROJECT_ROOT] [--dry-run]
    python -m oboe_mcp.migrate [PROJECT_ROOT] [--dry-run]
"""

# Deferred annotation evaluation, so `str | Path` and `list[str]` stay strings
# at runtime.  The package requires Python 3.11+, but this module is the one a
# user reaches for while *repairing* a project, and it may well be run by
# whatever `python3` is on PATH — which on macOS is still 3.9.  Without this,
# the import dies with `TypeError: unsupported operand type(s) for |` and the
# reader has no idea their interpreter is the problem.  With it, the module
# imports and runs on 3.9.
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "MigrationResult",
    "build_parser",
    "format_result",
    "main",
    "migrate_project",
    "rewrite_text",
]


# ``\bobo_`` rather than a bare ``obo_`` so that an identifier which merely
# ends in those characters — ``xobo_create`` — is left alone.
_TOOL_RE = re.compile(r"\bobo_([A-Za-z])")
_SESSIONS_RE = re.compile(r"\bobo_sessions\b")

_EXCLUDED_DIRS = {".git", "node_modules", "renv", ".venv", "__pycache__"}


@dataclass
class MigrationResult:
    """What a migration run did, or would do under ``dry_run``."""

    root: Path
    dry_run: bool = False
    actions: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def change_count(self) -> int:
        """Total number of distinct changes applied (or that would be)."""
        return len(self.actions) + len(self.changed)


def rewrite_text(text: str) -> str:
    """Return *text* with obo_ tool names and session paths renamed.

    Pure and side-effect free, so the substitution rules can be tested
    directly without touching the filesystem.
    """
    text = _TOOL_RE.sub(r"oboe_\1", text)
    return _SESSIONS_RE.sub("oboe_sessions", text)


def _candidate_files(root: Path) -> list[Path]:
    """Collect the agent instruction files worth rewriting.

    Three well-known files under
    ``.github/``, any markdown under a ``prompts/`` directory, and any
    ``SKILL.md`` anywhere in the project.
    """
    github = root / ".github"
    found: list[Path] = []

    for name in ("copilot-instructions.md", "CLAUDE.md", "AGENTS.md"):
        candidate = github / name
        if candidate.is_file():
            found.append(candidate)

    if github.is_dir():
        for path in github.rglob("*.md"):
            if "prompts" in path.parts and path.is_file():
                found.append(path)

    for path in root.rglob("SKILL.md"):
        if _EXCLUDED_DIRS.isdisjoint(path.parts) and path.is_file():
            found.append(path)

    # Stable, de-duplicated order so output is reproducible.
    return sorted(set(found))


def _atomic_write_text(path: Path, text: str) -> None:
    """Replace *path*'s contents via a temp file and ``os.replace``.

    ``Path.write_text`` truncates in place, so a crash — or a reader — between
    the truncate and the write sees an empty or partial file.  These are the
    user's own instruction files, which this module did not create and cannot
    reconstruct, and a migration is precisely when someone is already repairing
    something.  The directory is fsynced afterwards so the rename is durable
    and not merely atomic.

    Duplicated from ``locking.atomic_write_text`` rather than imported, and
    that is deliberate: this module is documented to run on the stock macOS
    ``python3`` (3.9), while ``locking`` evaluates ``float | None`` annotations
    at runtime and therefore needs 3.10+.  Importing it would break the repair
    tool on exactly the interpreter it was written to survive.
    """
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(
        dir=str(directory), prefix="." + path.name + ".", suffix=".tmp"
    )
    tmp_path: "str | None" = tmp_name
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        shutil.copymode(str(path), tmp_name)
        os.replace(tmp_name, str(path))
        tmp_path = None  # ownership transferred to the destination
        try:  # best effort: not supported on Windows or every filesystem
            flags = getattr(os, "O_DIRECTORY", os.O_RDONLY)
            dir_fd = os.open(str(directory), flags)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _migrate_sessions_dir(root: Path, result: MigrationResult) -> None:
    """Rename the session directory and leave a compatibility symlink."""
    github = root / ".github"
    old_dir = github / "obo_sessions"
    new_dir = github / "oboe_sessions"

    old_is_symlink = old_dir.is_symlink()

    if new_dir.is_dir() and not new_dir.is_symlink():
        result.notes.append(".github/oboe_sessions/ already exists")
    elif old_dir.is_dir() and not old_is_symlink:
        if not result.dry_run:
            old_dir.rename(new_dir)
        result.actions.append(
            "Renamed .github/obo_sessions/ -> .github/oboe_sessions/"
        )
    else:
        result.notes.append(
            ".github/obo_sessions/ not found (nothing to rename)"
        )

    if old_is_symlink:
        result.notes.append(
            "Symlink .github/obo_sessions -> oboe_sessions already exists"
        )
        return

    # The directory may have just been renamed, so re-test rather than reusing
    # the value read above.
    will_exist = new_dir.is_dir() or (result.dry_run and old_dir.is_dir())
    if not will_exist or old_dir.exists():
        return

    if result.dry_run:
        result.actions.append(
            "Would create symlink .github/obo_sessions -> oboe_sessions"
        )
        return

    try:
        os.symlink("oboe_sessions", old_dir)
    except (OSError, NotImplementedError) as exc:
        # Windows without Developer Mode cannot create symlinks unprivileged.
        # This is a compatibility nicety, not the migration itself, so report
        # it and carry on rather than aborting a half-done run.
        result.notes.append(
            f"Could not create .github/obo_sessions compatibility symlink "
            f"({exc}). Tooling hard-coding the old path will not resolve; "
            "update it to .github/oboe_sessions/."
        )
    else:
        result.actions.append(
            "Created symlink .github/obo_sessions -> oboe_sessions"
        )


def migrate_project(
    root: str | Path,
    dry_run: bool = False,
) -> MigrationResult:
    """Migrate the project rooted at *root* from ``obo_`` to ``oboe_``.

    Args:
        root: Project root directory.
        dry_run: Report what would change without modifying anything.

    Returns:
        A :class:`MigrationResult` describing every action, change, and
        skipped file.

    Raises:
        FileNotFoundError: if *root* does not exist or is not a directory.
    """
    root = Path(root).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"Project root not found: {root}")
    root = root.resolve()

    result = MigrationResult(root=root, dry_run=dry_run)
    _migrate_sessions_dir(root, result)

    for path in _candidate_files(root):
        rel = str(path.relative_to(root))
        try:
            original = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # Deliberately NOT treated as empty content: rewriting a file we
            # could not read would destroy it.  Record and skip.
            result.unreadable.append(f"{rel} ({exc.__class__.__name__})")
            continue

        updated = rewrite_text(original)
        if updated == original:
            result.unchanged.append(rel)
            continue

        if not dry_run:
            _atomic_write_text(path, updated)
        result.changed.append(rel)

    return result


def format_result(result: MigrationResult) -> str:
    """Render a human-readable summary of a migration run."""
    lines = [
        "",
        "=== oboe-mcp migration: obo_ -> oboe_ ===",
        f"    Project root: {result.root}",
    ]
    if result.dry_run:
        lines.append("    DRY RUN - no files will be modified")
    lines.append("")

    lines.append("[ Session directory ]")
    for action in result.actions:
        lines.append(f"  * {action}")
    for note in result.notes:
        lines.append(f"  - {note}")
    lines.append("")

    lines.append("[ Agent instruction files ]")
    for rel in result.changed:
        lines.append(f"  * {rel}")
    for rel in result.unchanged:
        lines.append(f"  - {rel} (no changes needed)")
    for rel in result.unreadable:
        lines.append(f"  ! {rel} - could not read, left untouched")
    lines.append("")

    if result.change_count:
        verb = "would be applied" if result.dry_run else "applied"
        lines.append(
            f"=== Migration complete: {result.change_count} change(s) "
            f"{verb}. ==="
        )
    else:
        lines.append(
            "=== Migration complete: nothing to change "
            "(already up to date). ==="
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def build_parser(prog: str | None = None) -> argparse.ArgumentParser:
    """Build the argument parser shared by every entry point."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Rewrite a project's agent instruction files and session "
            "directory from the pre-0.3.0 obo_ names to oboe_. Safe to run "
            "more than once."
        ),
    )
    parser.add_argument(
        "project_root",
        nargs="?",
        default=".",
        help="Project root to migrate (default: current directory)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without modifying anything",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the migration as a standalone command.

    Reached via ``python -m oboe_mcp.migrate`` and by the
    ``oboe-mcp migrate`` calls
    :func:`migrate_project` directly through the server's own parser.
    """
    args = build_parser("oboe-mcp-migrate").parse_args(argv)
    try:
        result = migrate_project(args.project_root, dry_run=args.dry_run)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(format_result(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
