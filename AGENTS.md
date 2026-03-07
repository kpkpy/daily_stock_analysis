# AGENTS.md

This file defines unified behavioral guidelines for development, issue analysis, and PR review in this repository.

## 1. Build/Lint/Test Commands

### Backend Commands

```bash
# Install dependencies
pip install -r requirements.txt
pip install flake8 pytest black isort

# Syntax check
python -m py_compile main.py src/*.py data_provider/*.py

# Lint (critical errors only)
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics

# Lint (full check, line-length 120)
flake8 main.py src/ data_provider/ --max-line-length=120

# Format code
black . --line-length=120
isort . --profile black --line-length 120

# Run all backend gate checks (recommended before commit)
./scripts/ci_gate.sh
```

### Test Commands

```bash
# Run all offline tests (unit + integration, no network)
python -m pytest -m "not network"

# Run single test file
python -m pytest tests/test_storage.py -v

# Run single test function
python -m pytest tests/test_storage.py::TestStorage::test_parse_sniper_value -v

# Run tests by marker
python -m pytest -m unit          # Fast offline unit tests
python -m pytest -m integration   # Integration tests
python -m pytest -m network       # Tests requiring external network

# Test scenarios (via test.sh)
./test.sh quick      # Quick single-stock test
./test.sh syntax     # Python syntax check
./test.sh code       # Stock code recognition test
./test.sh yfinance   # YFinance conversion test
./test.sh all        # Run all tests
```

### Frontend Commands (apps/dsa-web)

```bash
cd apps/dsa-web
npm ci
npm run lint
npm run build
```

## 2. Code Style Guidelines

### Formatting

- Line width: 120 characters
- Formatter: `black` with `--line-length=120`
- Import sorter: `isort` with `profile=black`
- Target Python: 3.10+

### Imports

```python
# Standard library
import os
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

# Third-party
import pandas as pd
from sqlalchemy import Column, String
from tenacity import retry, stop_after_attempt

# Local modules
from src.config import get_config
from data_provider.base import BaseFetcher
```

### Type Hints

- Use type hints for function parameters and return values
- Use `Optional[T]` for nullable types
- Use `List[T]`, `Dict[K, V]` instead of `list[T]`, `dict[K, V]` for Python 3.9 compatibility
- Use `Literal` for restricted string values

```python
def fetch_data(
    code: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    ...

def get_config() -> "Config":
    ...
```

### Naming Conventions

- Functions/variables: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private methods: `_leading_underscore`
- File names: `snake_case.py`

### Docstrings

```python
def function_name(param1: str, param2: int) -> bool:
    """
    Brief description of function.

    Args:
        param1: Description of param1.
        param2: Description of param2.

    Returns:
        Description of return value.

    Raises:
        ValueError: When param1 is empty.
    """
```

### Error Handling

- Use specific exception types
- Log errors with context using `logging` module
- Use `tenacity` for retry with exponential backoff
- Never expose secrets/keys in logs or error messages

```python
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def fetch_with_retry(url: str) -> dict:
    try:
        # ... fetch logic
        pass
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {url}: {e}")
        raise
```

### Comments

- All new or modified code comments must be in English
- Use `# TODO:` for future improvements
- Use `# NOTE:` for important clarifications
- Use `# FIXME:` for known issues

## 3. Project Structure

```
├── main.py              # Entry point
├── server.py            # API server
├── src/                 # Core modules
│   ├── config.py        # Configuration management (singleton)
│   ├── storage.py       # Database layer (SQLAlchemy ORM)
│   ├── analyzer.py      # AI analysis logic
│   ├── notification.py  # Notification dispatch
│   └── ...
├── data_provider/       # Data fetcher implementations
│   ├── base.py          # Abstract base class + manager
│   ├── akshare_fetcher.py
│   ├── yfinance_fetcher.py
│   └── ...
├── api/                 # FastAPI endpoints
├── bot/                 # Bot platform handlers
├── tests/               # Test files
└── apps/dsa-web/        # Frontend (Vue.js)
```

## 4. Configuration

- Use `.env` file for secrets and config (see `.env.example`)
- Never commit `.env` or secrets
- Use `python-dotenv` to load environment variables
- Access config via `get_config()` singleton

## 5. Git Conventions

- Do NOT commit without explicit user confirmation
- Do NOT add `Co-Authored-By` to commit messages
- All commit messages must be in English
- Follow Conventional Commits: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`

## 6. Issue Analysis Principles

Each issue must answer:

1. **Reasonable**: Does it describe real impact with verifiable evidence?
2. **Valid Issue**: Is it a bug/feature/docs issue, not a usage question?
3. **Solvability**: Can it be reproduced? Are dependencies controllable?

### Issue Verdict Template

- Conclusion: `Valid / Partially Valid / Invalid`
- Category: `bug / feature / docs / question / external`
- Priority: `P0 / P1 / P2 / P3`
- Difficulty: `easy / medium / hard`
- Action: `Fix Now / Schedule / Document / Close`

## 7. PR Review Principles

Review in order:

1. **Necessity**: Does it solve a real problem?
2. **Traceability**: Is there an issue linked (`Fixes #xxx`)?
3. **Type**: `fix / feat / refactor / docs / chore / test`
4. **Description**: Background, changes, verification, rollback plan
5. **Merge Readiness**: Tests passed, no breaking risks

### PR Verdict Template

- Necessity: `Pass / Fail`
- Linked Issue: `Yes (#xxx) / No`
- Type: `fix/feat/...`
- Description: `Complete / Incomplete (missing items)`
- Merge Ready: `Yes / No (required changes)`

## 8. Documentation Sync

After feature development or bug fixes, update:
- `README.md` (user-facing changes)
- `docs/CHANGELOG.md` (version history)

## 9. Quick Reference

```bash
# Before committing
./scripts/ci_gate.sh

# Format changed files
black . --line-length=120
isort . --profile black

# Run specific test
python -m pytest tests/test_storage.py::TestStorage::test_parse_sniper_value -v
```