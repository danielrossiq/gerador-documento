#!/usr/bin/env bash
# Stack local de TESTE, sem Docker: IA falsa + API (SQLite, jobs em thread) + front (next dev --webpack).
#
#   scripts/stack_local.sh up [--fresh] [--no-web] [--no-seed] [--ai "--latency-ms 2000 --rate-429 0.1"]
#   scripts/stack_local.sh down | status | seed | env | restart-api | logs [ai|api|web|seed]
#
# Portas pelo ambiente: API_PORT=8150 WEB_PORT=3350 AI_PORT=8151 (as do agente de testes). Detalhes em
# scripts/stack_local.py. Usa o venv da pasta principal do repositório (as worktrees não têm venv próprio);
# para outro Python, defina PY=/caminho/python.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MAIN="$(cd "$(git -C "$ROOT" rev-parse --git-common-dir)/.." && pwd)"
if [[ -z "${PY:-}" ]]; then
  if [[ -x "$MAIN/backend/.venv/Scripts/python.exe" ]]; then PY="$MAIN/backend/.venv/Scripts/python.exe"
  elif [[ -x "$MAIN/backend/.venv/bin/python" ]]; then PY="$MAIN/backend/.venv/bin/python"
  else PY="python3"; fi
fi
exec "$PY" "$ROOT/scripts/stack_local.py" "$@"
