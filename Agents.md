# AGENTS Guide For Rover

This file tells coding agents how to work safely and consistently in this repo.

## 1) Repository Context

- Rover has two runtime targets:
  - ESP32 firmware: `code/esp32/main.py` (MicroPython).
  - Raspberry Pi service: `code/raspberry/` (FastAPI + serial + camera + UI).
- Safety behavior is critical: loss of control input must end in `0,0` output.

## 2) Mandatory Workflow (Local -> Push -> Pi Pull -> Validate)

For every code change, follow this sequence:

1. Edit and validate locally in this repo.
2. Commit locally.
3. Push to remote.
4. SSH into Raspberry Pi.
5. Pull latest in `~/develop/Rover`.
6. Re-run validation checks on Pi.
7. Report what was verified and what was not.

Do not skip Pi validation for runtime-affecting changes.

## 3) Rules Files Check

Searched these locations:

- `.cursor/rules/`
- `.cursorrules`
- `.github/copilot-instructions.md`

Current state: none of these files exist in the repository.
If added later, merge their guidance into this document.

## 4) Build / Run / Validation Commands

### Local quick checks

- Compile Raspberry Python sources:
  - `python -m compileall code/raspberry`
- Syntax check ESP32 script:
  - `python -m py_compile code/esp32/main.py`

### Raspberry Pi setup (first run)

- `cd ~/develop/Rover/code/raspberry`
- `python3 -m venv .venv`
- `source .venv/bin/activate`
- `python -m pip install --upgrade pip`
- `python -m pip install -r requirements.txt`

### Run server on Pi

- `cd ~/develop/Rover/code/raspberry`
- `source .venv/bin/activate`
- `ROVER_SERIAL_PORT=/dev/ttyUSB0 uvicorn app:app --host 0.0.0.0 --port 8000`

### Background restart on Pi

- `pkill -f "uvicorn app:app" || true`
- `cd ~/develop/Rover/code/raspberry`
- `source .venv/bin/activate`
- `ROVER_SERIAL_PORT=/dev/ttyUSB0 nohup uvicorn app:app --host 0.0.0.0 --port 8000 >/tmp/rover-uvicorn.log 2>&1 < /dev/null &`

### Core runtime smoke checks

- Health/status:
  - `curl -sS http://127.0.0.1:8000/api/status`
- Emergency stop:
  - `curl -sS -X POST http://127.0.0.1:8000/api/stop`
- HTTP control path:
  - `curl -sS -X POST http://127.0.0.1:8000/api/control -H "Content-Type: application/json" -d '{"throttle":0.2,"steer":0.0,"deadman":true}'`

## 5) Linting / Formatting

There is no enforced formatter/linter config in repo yet.
Minimum required checks before push:

- `python -m compileall code/raspberry`
- `python -m py_compile code/esp32/main.py`

If maintainers request linting/formatting, preferred tools are:

- `ruff check .`
- `ruff format .`

Do not introduce new tooling without explicit agreement.

## 6) Test Guidance (Including Single Test)

Current state:

- No committed `tests/` suite exists yet.
- Use smoke tests above for now.

When pytest tests are added, default commands should be:

- Full test run:
  - `pytest -q`
- Single file:
  - `pytest tests/test_serial_bridge.py -q`
- Single test case:
  - `pytest tests/test_serial_bridge.py::test_reconnect_on_write_error -q`

Agents should prefer single-test iteration before full-suite runs.

## 7) Code Style: Python (Raspberry)

- Follow PEP 8 and readable line lengths (about 100 chars target).
- Use type hints on public APIs and non-trivial internals.
- Keep imports ordered: stdlib, third-party, local.
- Avoid wildcard imports.
- Favor explicit names over short/ambiguous names.
- Use dataclasses for compact state bundles where useful.
- Keep concurrency safe (`threading.Lock` around shared mutable state).
- Keep startup/shutdown side effects inside FastAPI lifespan hooks.
- Ensure clamping and safe defaults at API boundaries.

## 8) Code Style: MicroPython (ESP32)

- Keep loop logic deterministic and lightweight.
- Preserve watchdog and stop-on-timeout behavior.
- Avoid large allocations in hot loops.
- Keep serial protocol stable (`left,right\n`, `ACK:*`) unless coordinated.
- Any parse failure should fail safe (ignore input, keep safe state).

## 9) Code Style: Frontend Control UI

- Use plain HTML/CSS/JS unless explicitly asked for frameworks.
- Keep controls mobile-friendly (`pointer*` events, touch-safe behavior).
- Dead-man and E-stop semantics must stay intact.
- Control transport failures must degrade safely (`0,0`).
- Keep status badges accurate (`ws/http fallback/serial/camera`).

## 10) Naming Conventions

- Python files/functions/variables: `snake_case`.
- Python classes: `PascalCase`.
- Constants and env vars: `UPPER_SNAKE_CASE`.
- JavaScript vars/functions: `camelCase`.
- HTML ids: short descriptive lowercase names.

## 11) Error Handling + Safety Rules

- Never remove safety-stop paths without explicit instruction.
- Treat serial or camera faults as non-fatal service errors.
- Keep app responsive even when hardware is missing/unavailable.
- Avoid broad `except` unless narrowed and justified.
- If suppressing an exception, keep scope tiny and intentional.

## 12) Git + Artifacts Hygiene

- Never commit `__pycache__` or `.pyc` files.
- Keep commits focused and clearly named by intent.
- Review `git diff` before committing.
- Do not rewrite history unless explicitly asked.

## 13) Minimum Done Checklist

1. Local compile checks pass.
2. Changes committed and pushed.
3. Pi checkout pulled latest commit.
4. Pi service starts without crash.
5. `/api/status` returns healthy JSON.
6. Drive/stop safety path validated.
7. Final report lists verified vs not verified behavior.
