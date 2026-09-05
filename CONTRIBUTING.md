# Contributing to Claude Window Starter

Thank you for considering contributing! This document outlines the guidelines for contributing to the project.

## Code of Conduct

By participating, you agree to maintain a respectful and inclusive environment for everyone.

## How to Contribute

### Reporting Bugs

1. Check existing [issues](https://github.com/aetsr/claude-window-starter/issues) for duplicates
2. Use the bug report template when creating a new issue
3. Include: macOS version, Python version, Claude CLI version, and relevant logs

### Suggesting Features

1. Open a feature request issue describing the motivation and use case
2. Explain how the feature fits the project's scope (macOS, Claude Code window scheduling, Python standard-library backend)

### Pull Requests

1. Fork the repository
2. Create a feature branch from `main`
3. Follow the coding standards below
4. Add or update tests as needed
5. Run the full test suite before submitting
6. Keep PRs focused on a single change

### Development Setup

```bash
git clone https://github.com/aetsr/claude-window-starter.git
cd claude-window-starter

# Install dev tools in an isolated environment
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements-dev.lock

# Run tests
PYTHONPATH=backend python3 -m unittest discover -s tests -p 'test_*.py'
swift test --package-path macos-app

# Lint and type-check
ruff format --check backend tests scripts/security_scan.py
ruff check backend tests scripts/security_scan.py
mypy backend/claude_starter

# Security scan
python3 scripts/security_scan.py
```

## Coding Standards

- **Python**: 3.10+ with full type annotations (`disallow_untyped_defs = true`)
- **Swift**: 6.0+ toolchain and macOS SDK, macOS 13+ deployment target
- **Style**: Ruff (line length 100), SwiftFormat-compatible
- **Imports**: Standard library first, then third-party, then local
- **Security**: No `shell=True`, no secret logging, no hardcoded credentials
- **Tests**: Add relevant coverage for features; run the Python and Swift commands above before pushing

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add window calibration command
fix: resolve Telegram markdown escape issue
docs: update README with new badges
refactor: extract service action into shared module
test: add end-to-end tests for rate-limit checking
```

## Security

See [SECURITY.md](SECURITY.md) for the full security model.
