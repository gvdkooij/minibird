# Development installation (Ubuntu 24.04)

Install Python 3.12, Python venv and git. Clone the repository, then:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest -q
uvicorn minibird.main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000/health on the same machine.

This is a development server, not a production deployment. Do not expose it publicly or use real financial data yet.
