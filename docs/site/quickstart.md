# Quick start

## Install

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements-lock.txt
pip install --no-deps -e .
```

## Run the pipeline

```bash
cso-insight run --root .
```

Outputs:

| Path | Description |
|------|-------------|
| `results/report.html` | Engineer summary (10-minute read) |
| `RESULTS.md` | Headline metrics |
| `results/evaluation.json` | Machine-readable metrics |
| `results/figures/` | Charts |

## Python API

```python
from pathlib import Path
from cso_insight.config import PipelineConfig
from cso_insight.pipeline import run_pipeline

config = PipelineConfig.from_root(Path("."))
run_pipeline(config)
```

## Tests

```bash
python -m pytest --cov=cso_insight --cov-fail-under=90
```
