#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose_project="${E2E_COMPOSE_PROJECT:-tasko-workspace-e2e}"
if [[ ! "${compose_project}" =~ ^tasko-workspace-e2e(-[a-z0-9][a-z0-9_-]*)?$ ]]; then
  echo "E2E_COMPOSE_PROJECT must be tasko-workspace-e2e or use the tasko-workspace-e2e-* namespace." >&2
  exit 2
fi

export API_PORT="${API_PORT:-18000}"
export WEB_PORT="${WEB_PORT:-13000}"
export POSTGRES_PORT="${POSTGRES_PORT:-15432}"
export REDIS_PORT="${REDIS_PORT:-16379}"
export E2E_API_URL="http://127.0.0.1:${API_PORT}"
export E2E_WEB_URL="http://127.0.0.1:${WEB_PORT}"
export E2E_COMPOSE_PROJECT="${compose_project}"
export E2E_REPO_ROOT="${repo_root}"

compose=(
  docker compose
  --project-name "${compose_project}"
  --file "${repo_root}/compose.yaml"
  --file "${repo_root}/tests/e2e/compose.e2e.yaml"
)

cleanup() {
  status=$?
  if [[ ${status} -ne 0 ]]; then
    "${compose[@]}" logs --no-color api web postgres || true
  fi
  "${compose[@]}" down --volumes --remove-orphans
  exit "${status}"
}
trap cleanup EXIT

python3 -c "from playwright.sync_api import sync_playwright" >/dev/null || {
  echo "Install E2E dependencies: python3 -m pip install -r tests/e2e/requirements.txt" >&2
  exit 1
}

"${compose[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
"${compose[@]}" up --detach --build --wait

cd "${repo_root}"
python3 -m unittest discover --start-directory tests/e2e --pattern 'test_*.py' --verbose
