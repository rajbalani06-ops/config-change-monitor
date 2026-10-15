# Configuration Change Monitor

This repository contains a PHP management API, a Python file watcher and webhook worker, PostgreSQL event/snapshot/outbox storage, RabbitMQ transport, an optional Redis hash cache, a local webhook receiver, and Prometheus configuration. PostgreSQL initialization is in `docker/postgres/init.sql`.

## Start with Docker Desktop (PowerShell)

From the repository root:

```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
Invoke-RestMethod http://localhost:8080/health
```

The checked-in Compose defaults and API keys are for local development. Change passwords and API keys in `.env` before exposing any service outside a local machine. The watched directory is `./watched`, mounted as `/watched` in both containers. The API key `dev-admin-key` is an administrator for the `default` tenant; use `X-API-Key: dev-admin-key` for local requests.

Stop services while retaining the PostgreSQL volume:

```powershell
docker compose down
```

To delete the local database volume too (this removes persisted local data):

```powershell
docker compose down -v
```

## Tests

Install worker test dependencies and run the Python suite:

```powershell
python -m pip install -r .\python-worker\requirements-dev.txt
python -m pytest .\python-worker\tests
```

Run PHP tests with Composer/PHPUnit when available, or the repository's standalone runner:

```powershell
Push-Location .\php-api
composer install --no-interaction
if (Test-Path .\vendor\bin\phpunit) { .\vendor\bin\phpunit } else { php .\tests\run.php }
Pop-Location
```

The PHP standalone test command needs PHP 8.2 or newer. The worker suite includes unit tests and a logical integration flow using fakes; it does not by itself prove that Dockerized RabbitMQ, PostgreSQL, or HTTP services are connected end to end.

## Local acceptance walkthrough

After startup, register the sample YAML file and inspect its file ID:

```powershell
$headers = @{ "X-API-Key" = "dev-admin-key"; "Content-Type" = "application/json" }
Invoke-RestMethod -Method Post -Uri http://localhost:8080/watch -Headers $headers -Body '{"path":"/watched/app.yaml"}'
```

The first scan establishes a baseline by default (`EMIT_INITIAL_SNAPSHOT_EVENTS=false`). Change a nested value in `watched\app.yaml`, wait for the watcher debounce/stability window, and inspect the event and delivery records:

```powershell
Invoke-RestMethod http://localhost:8080/events?limit=10 -Headers $headers | ConvertTo-Json -Depth 12
Invoke-RestMethod http://localhost:8080/deliveries?limit=10 -Headers $headers | ConvertTo-Json -Depth 8
```

`scripts\demo-change.ps1` automates registration, a sample edit, and event/delivery inspection. The Compose webhook receiver is local at `mock-webhook:8088`; its default behavior accepts requests. For retry/dead-letter/replay exercise, configure a local failing receiver or use the worker unit tests. A complete Docker acceptance run including retry exhaustion and replay has not been validated in this environment.

## API

- `GET /health` (database check; queue health currently reports `unknown`)
- `GET /files`
- `POST /watch` with `{ "path": "/watched/app.yaml" }`
- `DELETE /watch/{file-id}`
- `GET /events?limit=20&offset=0` with file/operation/delivery/time filters
- `GET /events/{event-id}`, `POST /events/{event-id}/replay`
- `GET /deliveries`, `GET /dead-letters`, `GET /destinations`, `GET /status`
- `GET /metrics`

Administrative routes require an API key. Tenant identity comes from the authenticated key; file/event queries are tenant scoped. Paths must be absolute, use a supported configuration extension, and resolve under `WATCH_ALLOWLIST`.

## Delivery and snapshot behavior

Valid snapshots are canonical parsed structures plus a raw-content SHA-256. Initial discovery establishes a baseline unless initial events are enabled. Invalid/partial parses retain the last valid structure. Deletion emits a deletion event when a valid prior snapshot exists; a later recreation is treated as a new `created` event. On restart, persisted snapshots are hydrated before scanning, avoiding restart-only modifications.

For emitted changes, event history, snapshot update, and outbox insertion share one PostgreSQL transaction. The outbox publishes durable RabbitMQ messages with publisher confirms. Delivery is at least once: a publisher/consumer crash can cause duplicate delivery, so receiver integrations should honor the event ID idempotency key. Outbox publishing claims are recoverable after a two-minute stale lock. Webhook retry attempts are republished with an incremented attempt after bounded jittered backoff; exhausted events are recorded in PostgreSQL and the RabbitMQ dead-letter queue.

## Feature status

The repository includes Redis hash caching, OpenTelemetry instrumentation, tenant-scoped API records, a static dashboard, Kubernetes manifests, and mocked webhook tests. Kubernetes deployment, real distributed tracing, production-grade tenant provisioning, and a full service-to-service Docker acceptance run require environment-specific validation. The database initialization SQL is the current schema bootstrap; it is not yet maintained as a versioned migration set.
