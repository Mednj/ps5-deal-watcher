#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(git rev-parse --show-toplevel)"
env_file="${WATCHER_ENV_FILE:-/etc/ps5-deal-watcher.env}"
health_timeout="${DEPLOY_HEALTH_TIMEOUT_SECONDS:-240}"
cd "$repo_root"

if [[ ! -r "$env_file" ]]; then
  echo "Deployment environment file is missing or unreadable: $env_file" >&2
  exit 2
fi

compose=(docker compose --env-file "$env_file" -f "$repo_root/compose.yaml")
services=(web worker monitor browser)

echo "Deploying commit $(git rev-parse --short HEAD) from $repo_root"
"${compose[@]}" up -d --build --remove-orphans

deadline=$((SECONDS + health_timeout))
while (( SECONDS < deadline )); do
  pending=()
  failed=()
  for service in "${services[@]}"; do
    container_id="$("${compose[@]}" ps -q "$service")"
    if [[ -z "$container_id" ]]; then
      pending+=("$service: not created")
      continue
    fi
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id")"
    case "$health" in
      healthy|running) ;;
      unhealthy|exited|dead) failed+=("$service: $health") ;;
      *) pending+=("$service: $health") ;;
    esac
  done

  if (( ${#failed[@]} > 0 )); then
    printf 'Deployment health check failed: %s\n' "${failed[*]}" >&2
    "${compose[@]}" ps >&2
    "${compose[@]}" logs --tail 80 "${services[@]}" >&2 || true
    exit 1
  fi
  if (( ${#pending[@]} == 0 )); then
    echo "Deployment healthy: ${services[*]}"
    exit 0
  fi
  sleep 5
done

echo "Timed out waiting for deployment health: ${pending[*]}" >&2
"${compose[@]}" ps >&2
"${compose[@]}" logs --tail 80 "${services[@]}" >&2 || true
exit 1
