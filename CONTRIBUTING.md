# Contributing to batchit

Thank you for your interest in contributing!

## Setting up

```bash
git clone https://github.com/Ahmedie-m/batchit.git
cd batchit
pip install -e ".[dev]"
```

## Running tests

```bash
pytest
```

## Submitting changes

1. Fork the repository and create a branch from `main`.
2. Make your changes and add tests.
3. Ensure `pytest` passes.
4. Open a pull request with a clear description of the change.

## Commit style

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add new batching mode
fix: handle empty iterables correctly
docs: improve async example
chore: bump dev dependency
```

## Releasing (maintainers only)

Bump the version in `pyproject.toml`, commit, then push a tag:

```bash
git tag v0.2.0
git push origin v0.2.0
```

The CI workflow will run tests, publish to PyPI, and create a GitHub release automatically.
