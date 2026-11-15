# Architecture decision records

| ADR | Decision |
|---|---|
| [001](001-postgres-task-store.md) | Tasks persist in Postgres via psycopg 3 (sync, own small pool); the service creates its schema idempotently under an advisory lock |
