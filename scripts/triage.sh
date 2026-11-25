#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

triage_action="${1:-start}"
case "$triage_action" in
    start|status|logs|stop) ;;
    *)
        printf 'Usage: bash scripts/triage.sh {start|status|logs|stop}\n' >&2
        exit 2
        ;;
esac

triage_config="${XDG_CONFIG_HOME:-$HOME/.config}/issue-triage/compose.env"
for triage_file in .env "$triage_config"; do
    if [[ ! -r "$triage_file" ]]; then
        printf 'Missing or unreadable settings file: %s\n' "$triage_file" >&2
        exit 1
    fi
done

TRIAGE_UID="$(id -u)"
TRIAGE_GID="$(id -g)"
export TRIAGE_UID TRIAGE_GID

triage_compose=(
    docker compose
    --env-file .env
    --env-file "$triage_config"
    -f compose.yaml
    -f compose.local.yaml
)

case "$triage_action" in
    start)
        "${triage_compose[@]}" up -d --build
        curl --fail --silent --show-error --output /dev/null \
            --max-time 3 --retry 5 --retry-connrefused \
            http://127.0.0.1:8080/health
        printf '\nDashboard ready at http://127.0.0.1:8080/\n'
        ;;
    status)
        exec "${triage_compose[@]}" ps --all
        ;;
    logs)
        exec "${triage_compose[@]}" logs --tail 50
        ;;
    stop)
        exec "${triage_compose[@]}" stop
        ;;
esac
