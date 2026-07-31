# Copyright (C) 2026 Gregory R. Warnes
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Oboe MCP.
# For commercial licensing, contact greg@warnes-innovations.com

"""
Tests for the obo_ -> oboe_ migration.

``oboe_mcp.migrate`` is the single implementation of the rules.  It is
reachable two ways, both exercised here:

* ``oboe-mcp migrate`` — the packaged console entry point, and the only one
  available to a PyPI install.
* ``python -m oboe_mcp.migrate`` — works against a bare checkout, since the
  module imports nothing outside the standard library.

The migration previously had no test at all, which is how its predecessor —
a shell script that shipped in neither the sdist nor the wheel — came to
depend on ``declare -A``, GNU ``sed -i`` and ``md5sum``, none present on a
stock macOS, aborting after renaming the session directory but before
rewriting any file and leaving projects half-migrated.  That script has been
removed; these tests exist so its replacement cannot rot the same way.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from oboe_mcp.migrate import format_result, migrate_project, rewrite_text

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _build_project(root: Path) -> Path:
    """Create a project fixture using the pre-0.3.0 obo_ names."""
    (root / ".github" / "obo_sessions").mkdir(parents=True)
    (root / ".github" / "prompts").mkdir(parents=True)
    (root / "skills" / "demo").mkdir(parents=True)

    (root / ".github" / "copilot-instructions.md").write_text(
        "Use obo_create to start, then obo_next and obo_mark_complete.\n"
        "Sessions live in .github/obo_sessions/ here.\n"
        "Edge case: xobo_create must NOT change.\n",
        encoding="utf-8",
    )
    (root / ".github" / "prompts" / "review.prompt.md").write_text(
        "Call obo_session_status then obo_list_items.\n", encoding="utf-8"
    )
    (root / "skills" / "demo" / "SKILL.md").write_text(
        "Skill uses obo_mark_blocked.\n", encoding="utf-8"
    )
    (root / ".github" / "AGENTS.md").write_text(
        "no tool references here\n", encoding="utf-8"
    )
    (root / ".github" / "obo_sessions" / "index.json").write_text(
        '{"format_version": 1, "sessions": []}\n', encoding="utf-8"
    )
    return root


@pytest.fixture
def project(tmp_path):
    return _build_project(tmp_path / "proj")


# ---------------------------------------------------------------------------
# Substitution rules
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "source,expected",
    [
        ("obo_create", "oboe_create"),
        ("obo_mark_complete", "oboe_mark_complete"),
        (".github/obo_sessions/", ".github/oboe_sessions/"),
        ("`obo_next`", "`oboe_next`"),
        ("call obo_next.", "call oboe_next."),
    ],
)
def test_rewrite_renames_tools_and_paths(source, expected):
    assert rewrite_text(source) == expected


@pytest.mark.parametrize(
    "source",
    [
        "xobo_create",          # not on a word boundary
        "my_obo_create",        # embedded in a longer identifier
        "oboe_create",          # already migrated
        "obo",                  # bare prefix, no trailing name
        "obo_",                 # prefix with no following letter
        "OBO_CREATE",           # different case is a different token
    ],
)
def test_rewrite_leaves_non_matches_alone(source):
    assert rewrite_text(source) == source


def test_rewrite_is_idempotent():
    once = rewrite_text("obo_create and .github/obo_sessions/")
    assert rewrite_text(once) == once


# ---------------------------------------------------------------------------
# Python migration
# ---------------------------------------------------------------------------

def test_migrate_renames_session_directory(project):
    migrate_project(project)
    assert (project / ".github" / "oboe_sessions").is_dir()
    assert (project / ".github" / "oboe_sessions" / "index.json").is_file()


def test_migrate_leaves_compatibility_symlink(project):
    migrate_project(project)
    old = project / ".github" / "obo_sessions"
    assert old.is_symlink()
    assert (old / "index.json").is_file(), "symlink should resolve"


def test_migrate_rewrites_instruction_files(project):
    migrate_project(project)
    text = (project / ".github" / "copilot-instructions.md").read_text()
    assert "oboe_create" in text
    assert "oboe_next" in text
    assert ".github/oboe_sessions/" in text


def test_migrate_preserves_word_boundary_edge_case(project):
    migrate_project(project)
    text = (project / ".github" / "copilot-instructions.md").read_text()
    assert "xobo_create" in text, "xobo_create must not be rewritten"


def test_migrate_covers_prompts_and_skill_files(project):
    migrate_project(project)
    assert "oboe_session_status" in (
        project / ".github" / "prompts" / "review.prompt.md"
    ).read_text()
    assert "oboe_mark_blocked" in (
        project / "skills" / "demo" / "SKILL.md"
    ).read_text()


def test_migrate_reports_unchanged_files_separately(project):
    result = migrate_project(project)
    assert ".github/AGENTS.md" in result.unchanged
    assert ".github/AGENTS.md" not in result.changed


def test_migrate_leaves_no_unmigrated_names(project):
    migrate_project(project)
    stale = []
    for path in project.rglob("*.md"):
        for num, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            cleaned = line.replace("oboe_", "").replace("xobo_", "")
            if "obo_" in cleaned:
                stale.append(f"{path}:{num}")
    assert not stale, f"unmigrated obo_ references remain: {stale}"


def test_migrate_is_idempotent(project):
    first = migrate_project(project)
    assert first.change_count > 0
    second = migrate_project(project)
    assert second.change_count == 0
    assert not second.changed


def test_dry_run_reports_without_modifying(project):
    before = (project / ".github" / "copilot-instructions.md").read_text()
    result = migrate_project(project, dry_run=True)

    assert result.dry_run
    assert result.change_count > 0, "dry run should still report work"
    assert (project / ".github" / "copilot-instructions.md").read_text() == before
    assert (project / ".github" / "obo_sessions").is_dir()
    assert not (project / ".github" / "oboe_sessions").exists()


def test_migrate_on_clean_project_is_a_no_op(tmp_path):
    root = tmp_path / "clean"
    (root / ".github").mkdir(parents=True)
    (root / ".github" / "AGENTS.md").write_text("nothing here\n")
    result = migrate_project(root)
    assert result.change_count == 0


def test_migrate_rejects_a_missing_root(tmp_path):
    with pytest.raises(FileNotFoundError):
        migrate_project(tmp_path / "does-not-exist")


def test_unreadable_file_is_skipped_not_emptied(project):
    """A file we cannot decode must be left alone, never truncated."""
    binary = project / "skills" / "demo" / "SKILL.md"
    binary.write_bytes(b"\xff\xfe\x00binary obo_create\x00")
    original = binary.read_bytes()

    result = migrate_project(project)

    assert binary.read_bytes() == original, "unreadable file was modified"
    assert any("SKILL.md" in entry for entry in result.unreadable)


def test_excluded_directories_are_not_touched(project):
    hidden = project / ".git" / "hooks"
    hidden.mkdir(parents=True)
    skill = hidden / "SKILL.md"
    skill.write_text("obo_create inside .git\n", encoding="utf-8")

    migrate_project(project)

    assert "obo_create" in skill.read_text(), ".git contents must be skipped"


def test_format_result_is_renderable(project):
    rendered = format_result(migrate_project(project))
    assert "oboe-mcp migration" in rendered
    assert "Migration complete" in rendered


def test_format_result_marks_dry_run(project):
    rendered = format_result(migrate_project(project, dry_run=True))
    assert "DRY RUN" in rendered


# ---------------------------------------------------------------------------
# CLI entry point — `oboe-mcp migrate`
# ---------------------------------------------------------------------------

def test_cli_migrate_runs(project, capsys):
    from oboe_mcp.server import main

    assert main(["migrate", str(project)]) == 0
    assert "Migration complete" in capsys.readouterr().out
    assert (project / ".github" / "oboe_sessions").is_dir()


def test_cli_migrate_dry_run_changes_nothing(project, capsys):
    from oboe_mcp.server import main

    assert main(["migrate", str(project), "--dry-run"]) == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert not (project / ".github" / "oboe_sessions").exists()


def test_cli_migrate_missing_root_exits_nonzero(tmp_path, capsys):
    from oboe_mcp.server import main

    assert main(["migrate", str(tmp_path / "nope")]) == 1
    assert "ERROR" in capsys.readouterr().err


def test_bare_invocation_still_targets_the_server(monkeypatch):
    """`oboe-mcp` with no subcommand must start the stdio server.

    Subcommands must never become required — MCP clients launch the bare
    command, and a parser error there would break every client.
    """
    from oboe_mcp import server

    started = []
    monkeypatch.setattr(server.mcp, "run", lambda: started.append(True))
    assert server.main([]) == 0
    assert started == [True], "bare invocation did not start the server"


# ---------------------------------------------------------------------------
# `python -m oboe_mcp.migrate`
# ---------------------------------------------------------------------------

SRC_DIR = Path(__file__).resolve().parents[1] / "src"


def _module_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def test_module_entry_point_runs(project):
    proc = subprocess.run(
        [sys.executable, "-m", "oboe_mcp.migrate", str(project)],
        capture_output=True, text=True, timeout=120, check=False,
        env=_module_env(),
    )
    assert proc.returncode == 0, proc.stderr
    assert "Migration complete" in proc.stdout
    assert (project / ".github" / "oboe_sessions").is_dir()


def test_module_entry_point_needs_no_third_party_deps(project):
    """The module must import only the standard library.

    That is what lets `python -m oboe_mcp.migrate` run against a bare
    checkout with nothing installed — not even the MCP SDK. `-I` isolates
    the interpreter from user site-packages so a stray dependency shows up
    here rather than in someone's terminal.
    """
    proc = subprocess.run(
        [sys.executable, "-I", "-m", "oboe_mcp.migrate", str(project)],
        capture_output=True, text=True, timeout=120, check=False,
        env=_module_env(),
    )
    assert proc.returncode == 0, (
        f"module pulled in a non-stdlib import:\n{proc.stderr}"
    )


def test_module_defers_annotation_evaluation():
    """`from __future__ import annotations` must stay in migrate.py.

    The package requires Python 3.11+, but this module is what someone runs
    while *repairing* a project, often via whatever `python3` is on PATH —
    which on macOS is still 3.9. Without the future import, `str | Path` is
    evaluated at import time and the module dies with an opaque
    `TypeError: unsupported operand type(s) for |` that says nothing about
    the interpreter version. With it, the module imports and runs on 3.9.

    Asserted against the source rather than by launching an old interpreter,
    so this holds on any machine.
    """
    source = (SRC_DIR / "oboe_mcp" / "migrate.py").read_text(encoding="utf-8")
    assert "from __future__ import annotations" in source


def test_module_entry_point_rejects_missing_root(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "oboe_mcp.migrate", str(tmp_path / "nope")],
        capture_output=True, text=True, timeout=120, check=False,
        env=_module_env(),
    )
    assert proc.returncode == 1
    assert "ERROR" in proc.stderr

