---
description: "Use when testing, preparing, tagging, releasing, or publishing oboe-mcp package versions. Covers repo-specific release commands, verification steps, and confirmation boundaries for push, tags, GitHub releases, and PyPI publication."
name: "Oboe Release Workflow"
---
# Oboe MCP Release Workflow

- Treat release work in this repository as a staged workflow: inspect repo state, run tests, complete release-prep edits, validate packaging, then handle remote release steps.
- Run the **whole** suite: `uv run pytest tests/ -q`. Do not run a named subset — this instruction used to name `tests/test_session.py tests/test_server.py`, which silently skipped `test_cli.py`, `test_concurrency.py`, and `test_migrate.py` as those were added.
- Keep release edits minimal and targeted. Do not revert unrelated dirty-worktree files unless the user explicitly asks.
- Before any irreversible action, pause for confirmation even if the user's initial request already said to publish.
- The required confirmation boundary includes each of these actions: `git push`, tag creation, GitHub release creation, and PyPI publication.
- When asking for confirmation, summarize the exact action, the version, and the branch or tag involved.
- After a live publish, verify the result end to end: release workflow status, PyPI visibility, and at least one package resolution or install check.
- If clarification, triage, or blocker handling is needed, prefer creating or resuming an OBO session rather than handling it as an unstructured side conversation.

## Version sources must move together

Two files carry the version, and they have drifted before:

- `pyproject.toml` → `version`
- `src/oboe_mcp/__init__.py` → `__version__`

Update both in the same commit and confirm they agree before building. The 0.2.0
release shipped reporting `__version__ == "0.1.2"` because only the first was
bumped; nothing failed, and nobody noticed until 0.3.0.

## Verifying the artifact — always

Before tagging, build and exercise the real artifact. `oboe-mcp` is pure Python
with no compiled extensions, so a local build is equivalent to the one CI
produces, and this catches artifact-level defects while the version number is
still unspent:

```bash
uv build --out-dir dist/
uv run --isolated --no-project \
  --with ./dist/oboe_mcp-<VERSION>-py3-none-any.whl --with 'mcp<3.0' \
  oboe-mcp --help
```

Smoke-test every declared entry point (`oboe-mcp`, `oboe-cli`) **and any command
the release notes tell users to run**. That last part is not optional: the 0.3.0
changelog advertised `uvx oboe-mcp migrate`, a command that did not exist, whose
fallback script shipped in neither the sdist nor the wheel. Running the
advertised command against a clean install is what catches that class of defect.

A PyPI version number is immutable and cannot be reused. A broken `X.Y.Z` means
shipping `X.Y.Z+1`, not replacing it.

## TestPyPI dry run — only when `publish.yml` changed

Dispatch the workflow against TestPyPI **when, and only when,
`.github/workflows/publish.yml` has been modified since the last release**:

```bash
gh workflow run publish.yml --ref main -f repository=testpypi
```

**What it is for:** exercising the CI publish path end to end — the build job,
the artifact hand-off between jobs, action pins, permissions. That is the only
thing it uniquely validates.

**What it does NOT do. Do not treat a result either way as evidence about PyPI:**

- **It does not validate PyPI's trusted publisher configuration.** TestPyPI
  requires a wholly separate registration. On 2026-07-31 a dry run failed with
  `invalid-publisher` while PyPI's own configuration was intact, and the real
  publish then succeeded with the workflow unchanged. A pass would have been
  equally uninformative.
- **It does not catch packaging or metadata errors** beyond what `twine check`
  in the build job and a local `uv build` already surface.
- **Installing from TestPyPI is not a faithful test.** Dependencies such as
  `mcp` are generally absent there, so the install needs `--extra-index-url`
  back to real PyPI, producing a hybrid resolution no real user experiences.

Running it on every release regardless would spend real time on a step that
usually reports nothing — and a check that habitually says nothing is one people
learn to skip at exactly the moment it would have mattered.

## Publish via the workflow, not a local upload

Publication goes through `publish.yml`, dispatched against `main`:

```bash
gh workflow run publish.yml --ref main -f repository=pypi
```

`repository` **defaults to `pypi`**, so `-f repository=pypi` is redundant. It is
written out anyway in the command above, and worth writing out yourself: the
two publish jobs are gated on that value, and a release is a bad moment to be
relying on a default you have not looked at.

For the dry run, the flag is **not** optional:

```bash
gh workflow run publish.yml --ref main -f repository=testpypi
```

This default was `testpypi` until 0.4.0, on the reasoning that a safe default
protects against an accidental real publish. That had the failure backwards.
Publishing is the common dispatch and the dry run is rare — see below, it is
called for only when this workflow file itself has changed — so the old default
made the ordinary action require an extra flag, and omitting it published to
the wrong index **and reported success**. The accidental-publish risk it was
guarding is in any case bounded: `pypa/gh-action-pypi-publish` does not set
`skip-existing`, so PyPI rejects a version that already exists and a stray
dispatch against an unchanged `main` fails instead of shipping.

This is preferred over `twine upload` from a workstation for three reasons: it
authenticates by OIDC rather than a local API token, it attaches **provenance
attestations** to the artifacts (visible as `provenance` entries in
`https://pypi.org/simple/oboe-mcp/`), and it leaves an auditable CI record.
Every action in that workflow is SHA-pinned because the publish jobs hold
`id-token: write`.

## `main` does not accept a direct push

`main` carries a ruleset requiring a pull request, so `git push origin main`
is refused server-side with `push declined due to repository rule violations`.
This is not the local `pre-push` hook — that is a separate, advisory reminder,
and `--no-verify` silences it without affecting the ruleset at all.

A release therefore reaches `main` the same way everything else does:

```bash
git push origin main:refs/heads/devel     # the release commit onto devel
git push origin vX.Y.Z                    # the tag can be pushed directly
gh pr create --base main --head devel --title "release: X.Y.Z"
# merge, then immediately:
git fetch origin && git push origin origin/main:devel
```

Because the tag can be pushed before the PR merges, it will briefly point at a
commit no branch contains. Confirm reachability afterwards rather than assuming
it, and confirm the tree that was tested is the tree that landed:

```bash
git merge-base --is-ancestor vX.Y.Z^{commit} origin/main && echo reachable
[ "$(git rev-parse vX.Y.Z^{tree})" = "$(git rev-parse origin/main^{tree})" ] \
  && echo "artifact matches main"
```

Trusted publisher registrations (both indexes) use:

```
Owner:              Warnes-Innovations
Repository:         oboe-mcp
Workflow filename:  publish.yml
Environment:        (blank)
```

Registration is manual on pypi.org / test.pypi.org and cannot be automated from
a checkout. Because `publish.yml` declares no `environment:`, the OIDC claim is
`MISSING`; a publisher registered *with* an environment name would not match.
