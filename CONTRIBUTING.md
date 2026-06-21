# Contributing to Synapse Memory

First off, thank you for considering contributing to Synapse Memory! We welcome contributions from everyone, whether it's a bug report, feature suggestion, documentation improvement, or code pull request.

## Table of Contents

- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Coding Standards](#coding-standards)
- [Pull Request Workflow](#pull-request-workflow)
- [Commit Convention](#commit-convention)
- [Testing](#testing)
- [Documentation](#documentation)

## Development Setup

### Prerequisites

- Python 3.12+
- PostgreSQL 16+ with pgvector extension
- Redis 7+
- Docker & Docker Compose (optional but recommended)
- [uv](https://docs.astral.sh/uv/) package manager

### Local Development

```bash
# Clone the repository
git clone https://github.com/dylanmarriner/synapse-memory.git
cd synapse-memory

# Create virtual environment with uv
uv venv
source .venv/bin/activate

# Install dependencies
uv pip install -e ".[dev]"

# Copy environment file
cp .env.example .env

# Start infrastructure services
docker compose up -d db redis

# Run database migrations
alembic upgrade head

# Start the development server
uvicorn app.main:app --reload
```

## Project Structure

```
synapse-memory/
├── app/                    # Application code
│   ├── api/               # Route handlers / endpoints
│   ├── core/              # Configuration, dependencies
│   ├── models/            # SQLAlchemy / Pydantic models
│   ├── services/          # Business logic
│   └── db/                # Database connections, migrations
├── tests/                 # Test suite
├── docker/                # Docker-related files
├── docs/                  # Documentation
├── scripts/               # Utility scripts
└── .github/               # GitHub templates and workflows
```

## Coding Standards

### Python

- **Formatter**: We use [ruff](https://docs.astral.sh/ruff/) with the provided `pyproject.toml` config.
  ```bash
  ruff check .
  ruff format --check .
  ```
- **Type hints**: All functions must have type annotations. Run `mypy .` to verify.
- **Imports**: Group imports as: standard library → third-party → local; alphabetically sorted.
- **Docstrings**: Use Google-style docstrings for public functions and classes.
- **Line length**: 100 characters maximum.
- **Naming**: `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_CASE` for constants.

### Database

- Use Alembic for all schema migrations.
- Never modify existing migrations; create new ones.
- All models should inherit from the shared `Base` and include `__tablename__`.

### API Design

- Follow RESTful conventions.
- Use Pydantic v2 models for request/response schemas.
- Return consistent error responses with `HTTPException` or custom error handlers.
- Version API endpoints via URL prefix (e.g., `/api/v1/`).

## Pull Request Workflow

1. **Fork** the repository and create a feature branch from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```

2. **Make your changes** following the coding standards above.

3. **Run the full test suite** locally:
   ```bash
   pytest
   ```

4. **Run linting and type checking**:
   ```bash
   ruff check .
   mypy .
   ```

5. **Commit** using conventional commit messages (see below).

6. **Push** and open a Pull Request against `main`:
   ```bash
   git push origin feat/my-feature
   ```

7. **Ensure CI passes**. All checks must be green before review.

8. **Address review feedback** by pushing additional commits. Keep the branch up to date with `main`.

### PR Checklist

Before submitting, confirm:
- [ ] Code follows the project's coding standards
- [ ] All new functions have type annotations
- [ ] Tests added/updated for new functionality
- [ ] All existing tests pass
- [ ] Linting (ruff) passes with no warnings
- [ ] Type checking (mypy) passes
- [ ] Documentation updated (docstrings, README, etc.)
- [ ] Changes are backward compatible or migration plan is documented
- [ ] No new dependencies without discussion

## Commit Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`, `ci`, `build`.

Examples:
```
feat(api): add memory search by similarity threshold
fix(db): handle null embedding in vector search
docs(readme): update quick-start instructions
```

## Testing

We use `pytest` with `pytest-asyncio` for async tests.

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=term-missing

# Run specific test file
pytest tests/test_memories.py -v

# Run tests matching a keyword
pytest -k "vector_search"
```

Test infrastructure (PostgreSQL, Redis) is managed via `docker compose` or testcontainers.

## Documentation

- Keep the `README.md` up to date with any configuration or usage changes.
- Document new API endpoints in the OpenAPI schema via Pydantic model descriptions.
- For significant features, add a section to `docs/`.

## Questions?

If you have questions about contributing, open a [Discussion](https://github.com/dylanmarriner/synapse-memory/discussions) or reach out to the maintainer.

Thank you for helping improve Synapse Memory!
