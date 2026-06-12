.PHONY: test serve serve-reload check

test:
	.venv/bin/python -m pytest -q

serve:
	.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

serve-reload:
	.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

check:
	.venv/bin/python -m compileall app hello_agents -q
