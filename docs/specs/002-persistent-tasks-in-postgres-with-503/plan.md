---
spec_id: 002-persistent-tasks-in-postgres-with-503
shape: service-python
spec_hash: 0545e0abfa87
summary: Postgres-backed task store with 503 on a database outage and a database readiness check
tasks:
  - id: t1
    title: Add PostgresTaskStore (psycopg 3, own pool, schema bootstrap, timeouts)
    files: [src/taskboard20_api/tasks/postgres.py, pyproject.toml, uv.lock, devbox.json, docs/env-vars.md]
    covers: [AC-002.1, AC-002.2, AC-002.4, AC-002.6]
    parallel_safe: true
    depends_on: []
    done: true
  - id: t2
    title: Wire the Postgres store into the tasks dependency, 503 mapping and /ready
    files: [src/taskboard20_api/tasks/store.py, src/taskboard20_api/tasks/router.py, src/taskboard20_api/main.py]
    covers: [AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6]
    parallel_safe: false
    depends_on: [t1]
---

# Plan — 002 Persistent tasks in Postgres with 503 and readiness on a database outage

Two sequential tasks: t1 builds the store module with its own unit-level checks against a real Postgres; t2 puts it behind the existing `get_task_store` dependency, maps outages to `503` and makes `/ready` check the database, after which the HTTP acceptance tests pass. See [design.md](design.md) for the contract and test hooks. No gitops task: the system plan already wires `postgres` (`DATABASE_URL`, `PG*`) and 2 replicas in dev.

## t1 — Add PostgresTaskStore (psycopg 3, own pool, schema bootstrap, timeouts)

**Files:** src/taskboard20_api/tasks/postgres.py, pyproject.toml, uv.lock, devbox.json, docs/env-vars.md
**Covers:** AC-002.1, AC-002.2, AC-002.4, AC-002.6
**Goal:** A `PostgresTaskStore` that stores and lists tasks durably in creation order, never connects at construction, raises `StoreUnavailable` within the time budget when the database is unreachable, and works again on the next call once the database is back.

**Implementation notes:**
- `pyproject.toml`: add `psycopg[binary]>=3.2` to `dependencies`; refresh `uv.lock` through devbox (`devbox shell` / `devbox run test` runs `uv sync` in its init hook), never `uv add` directly.
- `devbox.json`: add the package `postgresql@16` to `packages` (gives `initdb` / `pg_ctl` for the test harness); recipes stay untouched.
- `postgres.py`: `StoreUnavailable(Exception)` and `PostgresTaskStore(conninfo, *, max_idle=5, max_open=10)` with `from_env()` (`os.environ.get("DATABASE_URL", "")`, libpq fills the rest from `PG*`), signatures as in design.md. It imports `Task` from `.models` and never imports `.store` (t2's `store.py` imports from here and re-exports `StoreUnavailable`).
- Connections: `psycopg.connect(conninfo, connect_timeout=2, options="-c statement_timeout=3000", keepalives=1, keepalives_idle=5, keepalives_interval=1, keepalives_count=2, tcp_user_timeout=3000)`; a `BoundedSemaphore(max_open)` acquired with `timeout=2`; idle LIFO list of at most `max_idle`; a reused connection is checked with `SELECT 1` and replaced by a fresh one if the check fails.
- On `psycopg.OperationalError` / `psycopg.InterfaceError` (or semaphore timeout): close the connection, drain the idle list, raise `StoreUnavailable` from the error; log `task_store_unavailable` (structlog, warning, `error_type` only, never conninfo).
- `_ensure_schema(conn)`: once per store (flag behind a `threading.Lock`), in one transaction `SELECT pg_advisory_xact_lock(2002001)` + `CREATE TABLE IF NOT EXISTS tasks (...)` from design.md "Data"; flag set only after commit.
- `add`: `id = uuid.uuid4()`, `INSERT ... (id, title, due_date)` with `due_date` as `datetime.date.fromisoformat(...)` or `None`, commit, return `Task(id=str(id), title=title, due_date=due_date)`. `list`: `SELECT id, title, due_date FROM tasks ORDER BY seq`, map `str(id)` and `due_date.isoformat()` / `None`.
- `ping(timeout=1.0)`: submit `SELECT 1` (through the pool) to a store-owned `ThreadPoolExecutor(max_workers=2)`, `result(timeout)`; any exception or timeout returns `False`. `close()`: close idle connections and shut down the executor (`wait=False`), idempotent.
- `docs/env-vars.md`: a "Database" section with `DATABASE_URL` and `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD` (injected by the gitops entry's `postgres` resource; no default database).

**Done when:** unit tests of `PostgresTaskStore` against a throwaway Postgres show add/list round trip and creation order across two store objects, survival across `close()` + new store, `StoreUnavailable` within 6 s for a refused and a non-answering endpoint, recovery on the next call after a `pg_ctl` restart, and `ping` true/false; `devbox run quality` and `devbox run test` pass (the HTTP acceptance tests of spec 002 pass only after t2).

## t2 — Wire the Postgres store into the tasks dependency, 503 mapping and /ready

**Files:** src/taskboard20_api/tasks/store.py, src/taskboard20_api/tasks/router.py, src/taskboard20_api/main.py
**Covers:** AC-002.1, AC-002.2, AC-002.3, AC-002.4, AC-002.5, AC-002.6
**Goal:** The running service stores tasks in Postgres through `get_task_store`, answers `503 {"detail": "Task store unavailable"}` on an outage, and `/ready` reflects the database while `/health` does not.

**Implementation notes:**
- `store.py`: add the `TaskRepository` protocol (`add`, `list`, `ping`), re-export `StoreUnavailable` from `.postgres`; keep the in-memory `TaskStore` unchanged and add `ping(self, timeout: float = 1.0) -> bool: return True`.
- `store.py`: `get_task_store() -> TaskRepository` lazily creates one `PostgresTaskStore.from_env()` (module-level, double-checked under a `threading.Lock`); `close_default_store()` closes and forgets it.
- `router.py`: `StoreDep = Annotated[TaskRepository, Depends(get_task_store)]`; wrap `store.add` / `store.list` and turn `StoreUnavailable` into `HTTPException(status_code=503, detail="Task store unavailable")`; keep the `task_created` log event.
- `main.py`: `/ready` takes `store: Annotated[TaskRepository, Depends(get_task_store)]` and returns `{"status": "ready"}` or `JSONResponse(status_code=503, content={"status": "not ready"})`; `/health`, `/ping`, `/metrics` unchanged.
- `main.py`: `FastAPI(..., lifespan=...)` whose shutdown calls `close_default_store()`; nothing connects at import or startup.

**Done when:** the acceptance tests for AC-002.1 to AC-002.6 pass (in-process, with the test hooks from design.md), spec 001's acceptance tests for AC-001.1 to AC-001.6 still pass, and `devbox run quality` and `devbox run test` pass.
