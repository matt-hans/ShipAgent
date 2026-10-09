#!/usr/bin/env bash
# Local synthetic proof only. No dependency install, public endpoint or live APIs.
set -euo pipefail
umask 077
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${SHIPAGENT_TEST_PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  printf '%s\n' 'Missing project Python. Prepare it with: uv sync --locked --extra dev' >&2
  printf '%s\n' 'Or set SHIPAGENT_TEST_PYTHON to an already prepared project interpreter.' >&2
  exit 2
fi
OUTPUT="${SHIPAGENT_TEST_ACCEPTANCE_OUTPUT:-$ROOT/.cache/mcp-acceptance-$(date -u +%Y%m%dT%H%M%SZ)-$$}"
LOCK="${SHIPAGENT_TEST_HEAVY_LOCK:-$ROOT/../development-heavy.lock}"
TESTS=(tests/integration/test_mcp_runtime_acceptance.py tests/services/agent_runs/test_mcp_tracer.py tests/services/agent_runs/test_process_recovery.py tests/services/agent_runs/test_mcp_cancellation.py tests/services/agent_runs/test_cancellation_process_recovery.py tests/services/agent_runs/test_mcp_continuation.py tests/services/agent_runs/test_continuation_recovery.py tests/services/agent_runs/test_continuation_migration.py)
if [[ "${1:-}" == --self-test ]]; then
  shift
  TESTS=(tests/integration/test_validation_runner.py)
fi
exec "$PYTHON" "$ROOT/scripts/validation/run_bounded.py" \
  --name acceptance --cwd "$ROOT" --output-dir "$OUTPUT" --lock-file "$LOCK" \
  --seconds 90 --rss-mib 768 -- \
  "$PYTHON" -c '
import pathlib, sys
try:
    import fastmcp, pytest, src, shipagent_offline_guard
except ImportError:
    raise SystemExit("Missing acceptance dependencies; prepare with uv sync --locked --extra dev") from None
assert pathlib.Path(src.__file__).resolve().parent.parent == pathlib.Path.cwd(), "src resolved outside the selected checkout"
raise SystemExit(pytest.main(sys.argv[1:]))
' -q -p shipagent_offline_pytest --tb=short --junitxml="$OUTPUT/pytest.xml" "${TESTS[@]}" "$@"
