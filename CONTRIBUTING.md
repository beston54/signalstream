# Contributing to Signalstream

## Getting Started

```bash
git clone https://github.com/signalstream/signalstream.git
cd signalstream
python -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

## Development Workflow

1. Create a branch from `main`
2. Write tests first (TDD encouraged)
3. Implement your changes
4. Run the test suite: `pytest`
5. Run the linter: `ruff check .`
6. Submit a pull request

## Code Style

- **Linter:** ruff (configured in pyproject.toml)
- **Type hints:** Encouraged but not enforced in v0.1.0
- **Docstrings:** Required for all public functions and classes
- **Line length:** 100 characters

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=signalstream

# Run a specific test file
pytest signalstream/tests/test_app/test_routes_api.py -v
```

## Architecture Guidelines

- **No circular imports.** `jobs/` depends on `collectors/`, `analyzers/`, `llm/`, `reports/`. It never depends on `app/`.
- **All SQL in `db/repositories.py`.** No raw queries anywhere else.
- **Parameterized queries only.** No f-strings with user input in SQL.
- **Security middleware is not optional.** All responses must include security headers.

## Pull Request Process

1. Ensure all tests pass
2. Ensure ruff reports no issues
3. Update CHANGELOG.md if applicable
4. PR description should explain *why*, not just *what*
5. One approval required for merge
