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

**Three** files carry the version, and they have drifted twice:

- `pyproject.toml` → `version`
- `src/oboe_mcp/__init__.py` → `__version__`
- `uv.lock` → the `version` of the `oboe-mcp` package entry itself (it is an
  `editable = "."` source, so the lock records this project's own version)

Update all three in the same commit and confirm they agree before building:

```bash
grep -m1 '^version' pyproject.toml
grep -m1 '__version__' src/oboe_mcp/__init__.py
grep -A 1 '^name = "oboe-mcp"' uv.lock
```

Regenerate the lock with `uv lock` rather than editing it by hand.

This list said *two* files until 0.4.0, and that omission caused the second
drift: 0.4.0 shipped with `uv.lock` still claiming `0.3.0`, because the
instruction it was written to prevent did not name the third file. The
published artifact was unaffected — `uv.lock` is not packaged, and the wheel
correctly reported `0.4.0` — so it needed a follow-up commit rather than a
re-release. The first drift was 0.2.0 shipping `__version__ == "0.1.2"` because
only `pyproject.toml` was bumped; nothing failed, and nobody noticed until
0.3.0.

Both drifts share a cause worth naming: **the check was scoped to a list, and
the list was incomplete.** So assert the three declarations are *equal to the
new version* — do not merely look for the old one:

```bash
NEW=0.5.0   # the version you are bumping TO
got=$( { grep -m1 '^version = ' pyproject.toml
         grep -m1 '^__version__ = ' src/oboe_mcp/__init__.py
         awk '/^name = "oboe-mcp"$/{f=1} f && /^version = /{print; exit}' uv.lock
       } | grep -o '"[^"]*"' | tr -d '"' | sort -u )
[ "$got" = "$NEW" ] || { echo "VERSION DRIFT: $got"; exit 1; }
```

**Assert equality, not the absence of the old string.** A sweep for the old
version cannot see a drift that has already survived a release — which is what
*both* recorded drifts did. At the 0.3.0 bump the old version was `0.2.0`, and
the stale `__version__ = "0.1.2"` left over from the previous release matched
nothing and stayed invisible. The same blindness covers a typo in the new value
(`0.5.O`), which no absence-check can catch either.

Two traps in writing this check, both hit on the first attempt:

- **Do not grep `uv.lock` unanchored.** It contains ~38 `^version = ` lines,
  one per dependency, so any common version number (`1.0.0`, `2.0.0`) produces
  false positives that cannot be told from the real entry. The `awk` above
  anchors to the `oboe-mcp` block. Anchoring with `grep -A 1` is *also* wrong:
  it assumes `version` immediately follows `name`, and if uv ever inserts a
  field between them the check silently reports clean — failing in the
  direction of the defect.
- **Do not match bare mentions.** A plain `git grep "$OLD"` returns a dozen
  legitimate historical references (`migrate.py`, the README migration note,
  `test_migrate.py`). A check that reports twelve false positives on a clean
  tree is one people learn to skip at exactly the moment it matters.

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

### There are TWO publish routes. Use one.

`publish.yml` also triggers on `release: published`, and that path publishes to
the real index too. It is not dead: v0.1.1, v0.1.2, v0.2.0 and v0.3.0 all
shipped that way; only 0.4.0 used a dispatch.

**The dispatch is canonical. Do not also create a GitHub release for the same
version.** Doing both publishes twice: the second run 400s because the version
already exists, and step "verify release workflow status" then reports FAILURE
for a release that published correctly. A verification step that alarms on
success is worse than no verification at all.

If you prefer the release-event route for a given release, use it *instead* of
the dispatch — not as well. Either way the tag must point at a commit on
`main`; see the ordering below.

The dispatch path is additionally guarded: `publish-pypi` requires
`github.ref == 'refs/heads/main'`, so a dispatch from any other branch runs the
build and then does nothing. That guard cannot apply to the release event,
whose `github.ref` is a tag — which is the other reason to tag only after the
merge.

## `main` does not accept a direct push

`main` carries a ruleset requiring a pull request, so `git push origin main`
is refused server-side with `push declined due to repository rule violations`.
This is not the local `pre-push` hook — that is a separate, advisory reminder,
and `--no-verify` silences it without affecting the ruleset at all.

A release therefore reaches `main` the same way everything else does:

**Make the release commit on `devel`, not on `main`.** `main` cannot be pushed
to, and a local `main` silently falls behind `origin/main` after every PR merge
— so a release commit built there produces a non-fast-forward on the first
push. This procedure said `git push origin main:refs/heads/devel` until that
happened.

```bash
git switch devel && git pull --ff-only     # release commit belongs HERE
# ... bump the three version files, update CHANGELOG, commit ...
git push origin devel
gh pr create --base main --head devel --title "release: X.Y.Z"
# merge the PR, then:
git fetch origin
git tag -a vX.Y.Z -m "Release X.Y.Z" origin/main   # tag the MERGED commit
git push origin vX.Y.Z
git push origin origin/main:devel                  # back-merge, immediately
```

**Tag after the merge, not before.** Tagging first leaves the tag pointing at a
commit no branch contains, and — because the `release: published` trigger also
publishes (see below) — creating a GitHub release from such a tag would publish
from an unreachable commit. Tagging `origin/main` after the merge removes that
window entirely.

Confirm reachability afterwards rather than assuming
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
