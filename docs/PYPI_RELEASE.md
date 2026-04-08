# Publishing To PyPI

This repository is configured for Trusted Publishing from GitHub Actions via [.github/workflows/publish.yml](../.github/workflows/publish.yml).

## One-Time Setup

1. Create the `oboe-mcp` project on TestPyPI and PyPI, or create a pending publisher for each service.
2. In TestPyPI, add a Trusted Publisher with these values:
   - Owner: `Warnes-Innovations`
   - Repository name: `oboe-mcp`
   - Workflow name: `publish.yml`
3. In PyPI, add a Trusted Publisher with these values:
   - Owner: `Warnes-Innovations`
   - Repository name: `oboe-mcp`
   - Workflow name: `publish.yml`

## Local Verification

From the repository root:

```bash
/Users/warnes/src/oboe-mcp/.venv/bin/python -m pip install --upgrade build twine
/Users/warnes/src/oboe-mcp/.venv/bin/python -m build
/Users/warnes/src/oboe-mcp/.venv/bin/python -m twine check dist/*
```

Optionally run the project test suite before publishing:

```bash
/Users/warnes/src/oboe-mcp/.venv/bin/python -m pytest tests/test_session.py tests/test_server.py
```

## Release Flow

### TestPyPI

1. Run the `Publish Python Package` workflow manually.
2. Choose `testpypi` for the `repository` input.
3. Verify install and execution with `uvx --index-url https://test.pypi.org/simple --extra-index-url https://pypi.org/simple oboe-mcp`.

### PyPI

1. Update the version in [pyproject.toml](../pyproject.toml) and [src/oboe_mcp/__init__.py](../src/oboe_mcp/__init__.py).
2. Update [CHANGELOG.md](../CHANGELOG.md) for the release.
3. Create a GitHub release for the version tag, for example `v0.1.0`.
4. The release event triggers the same workflow and publishes to PyPI.

## Post-Publish Install

Once published, the simplest MCP configuration uses the PyPI package directly:

```json
"oboe-mcp": {
  "type": "stdio",
  "command": "uvx",
  "args": ["oboe-mcp"]
}
```

That keeps clients pinned to the released package rather than a repository checkout.
