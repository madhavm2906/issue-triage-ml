#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

triage_python=.venv/bin/python
if [[ ! -x "$triage_python" ]]; then
    echo 'Create the project virtual environment and install its requirements first.' >&2
    exit 1
fi

triage_container="$(docker run --detach --rm \
    --env POSTGRES_USER=triage_test \
    --env POSTGRES_PASSWORD=triage_test \
    --env POSTGRES_DB=triage_test \
    --publish 127.0.0.1::5432 \
    postgres:17)"
trap 'docker stop "$triage_container" >/dev/null 2>&1 || true' EXIT

echo 'Waiting for the test database.'
for attempt in {1..30}; do
    if docker exec "$triage_container" pg_isready -q -h 127.0.0.1 \
        -U triage_test -d triage_test; then
        break
    fi
    if [[ "$attempt" -eq 30 ]]; then
        docker logs "$triage_container" >&2
        exit 1
    fi
    sleep 1
done

triage_address="$(docker port "$triage_container" 5432/tcp)"
export DATABASE_URL="postgresql+psycopg://triage_test:triage_test@${triage_address}/triage_test"

"$triage_python" -m alembic upgrade head
"$triage_python" -m unittest discover -s tests -p test_delivery_workflow.py -v
