# ADR-001: Postgres task store

**Status:** Proposed (2026-11-16)

## Context

Spec 001 kept tasks in memory, so they vanished on every restart and each replica saw only its own tasks. Spec 002 requires tasks that survive restarts, are shared by all replicas, answer `503` when the database is down, and recover without a restart. The system plan already provides a Postgres resource (`DATABASE_URL` / `PG*`). The handlers are sync `def`, and the data is one table with two statements.

## Decision

Tasks persist in Postgres via psycopg 3 (sync, own small pool); the service creates its schema idempotently under an advisory lock.

- Driver `psycopg[binary]>=3.2`, no ORM.
- A small own pool instead of `psycopg_pool`: its background reconnect backoff would keep answering `503` after the database is back, and it starts failed when the database is down at startup. The own pool connects synchronously on demand and checks reused connections with `SELECT 1`.
- The schema (`tasks`, ordered by an identity column `seq`) is created on first use with `CREATE TABLE IF NOT EXISTS` after `pg_advisory_xact_lock`, so replicas starting together do not collide and a database that is down at start does not block startup. No migration tool for one table.
- Connection config only from `DATABASE_URL` / `PG*`; tests use a real Postgres (devbox `postgresql@16`).

## Consequences

- Tasks are durable and shared across replicas; a database outage gives `503` on `/tasks` and `/ready`, and the next request after recovery succeeds.
- The service owns a small connection pool and its timeouts (connect 2 s, statement 3 s) instead of a library.
- A later schema change needs a migration tool and its own spec, because the schema is created by `CREATE TABLE IF NOT EXISTS`.
- A title with a NUL character answers `500`, because Postgres `TEXT` cannot store it. The 001 contract is kept.
- The in-memory `TaskStore` stays as a test double behind the `TaskRepository` protocol.
