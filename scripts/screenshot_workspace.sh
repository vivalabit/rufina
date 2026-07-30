#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly screenshot_project="tasko-screenshots"

export API_PORT="${SCREENSHOT_API_PORT:-8001}"
export WEB_PORT="${SCREENSHOT_WEB_PORT:-3001}"
export POSTGRES_PORT="${SCREENSHOT_POSTGRES_PORT:-5433}"
export REDIS_PORT="${SCREENSHOT_REDIS_PORT:-6380}"
export SCREENSHOT_SESSION_ID="${SCREENSHOT_SESSION_ID:-$(date -u +%Y%m%dT%H%M%SZ)}"

if [[ "${API_PORT}" == "8000" || "${WEB_PORT}" == "3000" ]]; then
  echo "Screenshot API/web ports must not use the primary workspace ports 8000/3000." >&2
  exit 2
fi

if [[ "${POSTGRES_PORT}" == "5432" || "${REDIS_PORT}" == "6379" ]]; then
  echo "Screenshot database/cache ports must not use the primary ports 5432/6379." >&2
  exit 2
fi

compose=(
  docker compose
  --project-name "${screenshot_project}"
  --file "${repo_root}/compose.yaml"
  --file "${repo_root}/infra/screenshots/compose.screenshots.yaml"
)

seed_workspace() {
  "${compose[@]}" exec -T api \
    python /workspace/scripts/seed_screenshot_workspace.py
}

start_workspace() {
  "${compose[@]}" up --detach --build --wait
  seed_workspace
  echo "Screenshot workspace is ready at http://localhost:${WEB_PORT}"
}

case "${1:-up}" in
  up)
    start_workspace
    ;;
  seed)
    seed_workspace
    echo "Screenshot fixture was restored."
    ;;
  reset)
    "${compose[@]}" down --volumes --remove-orphans
    start_workspace
    ;;
  down)
    "${compose[@]}" down
    ;;
  logs)
    "${compose[@]}" logs --follow api web
    ;;
  status)
    "${compose[@]}" ps
    ;;
  *)
    echo "Usage: $0 {up|seed|reset|down|logs|status}" >&2
    exit 2
    ;;
esac
