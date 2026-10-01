# Contributing

Thanks for your interest in cso-insight.

1. Install dev dependencies: `pip install -r requirements-lock.txt
pip install --no-deps -e .`.
2. Run tests: `python -m pytest --cov=cso_insight --cov-fail-under=90`.
3. Run linters: `ruff check src tests scripts`, `mypy src`, `pyright`.
4. Regenerate results: `cso-insight run --root .`

Do not commit raw downloads, secrets, or absolute home-directory paths.
