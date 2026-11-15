# Design — 002 Persistent tasks in Postgres with 503 and readiness on a database outage

## Decisions

- **Driver: psycopg 3 (`psycopg[binary]>=3.2`), sync.** The handlers are sync `def` (FastAPI thread pool) and stay so; the binary wheel bundles libpq, so the `python:3.12-slim` image needs no system package. No ORM: two statements and one table do not justify one. ADR to be created (see "ADR" below).
- **A small own connection pool in `tasks/postgres.py`, not `psycopg_pool`.** `psycopg_pool` reconnects in background workers with exponential backoff (1 s, 2 s, 4 s ...), so after an outage the first requests can still answer `503` for many seconds although the database is back, and a pool opened while the database is down starts in that state; AC-002.4 ("also when it already is at service start") and AC-002.6 ("then they answer 201 and 200") need the next request after recovery to succeed. The own pool connects synchronously in the request thread when no idle connection is available, keeps at most 5 idle connections (LIFO), caps open connections at 10 (`threading.BoundedSemaphore`, waiting at most 2 s), and checks a reused idle connection with `SELECT 1` before handing it out; a failing check discards it and opens a fresh one, so stale connections from before a database restart never reach a request. Any `psycopg.OperationalError` / `psycopg.InterfaceError` during use discards that connection and drains the idle list (they are likely stale too).
- **Timeouts (spec "Timeouts"):** every connection is opened with `connect_timeout=2`, `options="-c statement_timeout=3000"`, `keepalives=1, keepalives_idle=5, keepalives_interval=1, keepalives_count=2`, `tcp_user_timeout=3000` (bounds a dead network, which a server-side statement timeout cannot). Budget for a task request: check of a reused connection (fast failure on a restarted server, at most ~3 s on a dead network) + fresh connect (at most 2 s) + statement (at most 3 s); against an unreachable or non-answering database a request answers `503` after at most ~5 s (AC-002.4).
- **`/ready` check bounded to 1 s on the client side:** `PostgresTaskStore.ping(timeout=1.0)` runs `SELECT 1` (through the pool) on a worker of a 2-thread executor owned by the store and waits `future.result(timeout)`; a timeout or an error is "not ready". libpq's connect timeout cannot go below 2 s, so the bound has to be client-side.
- **Schema created by the service, lazily and idempotently, not with a migration tool.** One table does not justify Alembic. The first successful connection of a store runs, in one transaction: `SELECT pg_advisory_xact_lock(2002001)` then `CREATE TABLE IF NOT EXISTS tasks (...)`. The advisory lock serializes two replicas starting at once (a bare `CREATE TABLE IF NOT EXISTS` can fail with a unique violation on `pg_type` when two run concurrently). It runs on first use, not at import or startup, because the database may be down at start (AC-002.4); a per-store flag (guarded by a lock) skips it afterwards, and a failure leaves the flag unset so the next request tries again (AC-002.6). The table name `tasks` is the schema's only object; a later schema change brings in a migration tool with its own spec.
- **Creation order from a database-filled column:** `seq BIGINT GENERATED ALWAYS AS IDENTITY`, listed `ORDER BY seq` (spec note; AC-002.2). `id` stays a UUID generated in Python (`uuid.uuid4()`), stored as `UUID` and returned as `str(id)` (canonical lowercase, as before).
- **`due_date` stored as `DATE`,** returned as `date.isoformat()`: the validator already guarantees a real `YYYY-MM-DD` date in years 0001-9999, which Postgres `DATE` holds, so the returned string equals the sent one (AC-002.1).
- **The HTTP contract of spec 001 is unchanged** (models untouched); the store sits behind the same `get_task_store` dependency. The in-memory `TaskStore` stays in `store.py` as a test double that satisfies the new `TaskRepository` protocol, so spec 001's acceptance tests (which construct `TaskStore()` and override `get_task_store`) keep running; only AC-001.7 is superseded (by AC-002.1), and retiring its two tests in `tests/test_tasks.py` is the testers' change.
- **`get_task_store` returns a lazily created process-wide `PostgresTaskStore`** built from the environment on first call (thread-safe), not one built at import or in the lifespan: `TestClient(app)` without `with` (how the existing tests use it) never runs the lifespan, and import must not need a database. The app's lifespan only closes the default store on shutdown, if it was created.
- **Database errors become `503 {"detail": "Task store unavailable"}` in the router** (`HTTPException`), from one exception type `StoreUnavailable` the store raises for connection, timeout and lost-connection failures (`psycopg.OperationalError` incl. `QueryCanceled`, `psycopg.InterfaceError`, pool wait timeout). Other errors stay FastAPI's `500`. A warning `task_store_unavailable` is logged with `error_type` (the exception class), never the conninfo or password.
- **Known limit, not new behaviour:** a title containing the NUL character (`\u0000`) is valid JSON and passes the 001 validator, but Postgres `TEXT` cannot store it; such a request answers `500` ("Unexpected API errors"). Rejecting it with `422` would change the 001 contract, which this spec keeps.
- **Connection config only from `DATABASE_URL` / `PG*`** (spec "Provided by the system"): conninfo is `DATABASE_URL` when set, else `""`, and libpq fills missing parts from `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`. No new variables.
- **Tests run against a real Postgres** from the devbox package `postgresql@16` (`initdb` / `pg_ctl` on PATH in `devbox run test`, locally and in CI's `test` job, which cannot be given a service container because `ci.yml` is platform-owned). No Docker / testcontainers: self-hosted runners do not guarantee a Docker daemon.

### ADR

The decision "Postgres via psycopg 3 with a service-created schema is the task store" outlives this feature and needs an ADR. It is not created yet: this planning run had no shell to run `cplat adr add`. To create: `cplat adr add postgres-task-store --decision "Tasks persist in Postgres via psycopg 3 (sync, own small pool); the service creates its schema idempotently under an advisory lock"`, then fill Context / Decision / Consequences from the bullets above.

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard20_api/tasks/postgres.py` | `PostgresTaskStore`: connection pool, schema bootstrap, `add`, `list`, `ping`, `close`; `StoreUnavailable` mapping | new |
| `src/taskboard20_api/tasks/store.py` | `TaskRepository` protocol, `StoreUnavailable`, in-memory `TaskStore` (test double, gains `ping`), `get_task_store` (lazy default), `close_default_store` | changed |
| `src/taskboard20_api/tasks/router.py` | maps `StoreUnavailable` to `503`; typed against `TaskRepository` | changed |
| `src/taskboard20_api/main.py` | `/ready` runs the store's `ping`; lifespan closes the default store | changed |
| `src/taskboard20_api/tasks/models.py` | unchanged | — |
| `pyproject.toml`, `uv.lock` | `psycopg[binary]>=3.2` | changed |
| `devbox.json` | package `postgresql@16` (test database binaries) | changed |
| `docs/env-vars.md` | `DATABASE_URL`, `PG*` | changed |

```python
# store.py
class StoreUnavailable(Exception): ...            # the database cannot be reached / timed out / connection lost

class TaskRepository(Protocol):
    def add(self, title: str, due_date: str | None) -> Task: ...   # durable before return; raises StoreUnavailable
    def list(self) -> list[Task]: ...                              # creation order; raises StoreUnavailable
    def ping(self, timeout: float = 1.0) -> bool: ...              # True iff SELECT 1 succeeded within timeout; never raises

class TaskStore:  # in-memory test double, as in spec 001; ping() -> True
    ...

def get_task_store() -> TaskRepository: ...       # lazily creates the process-wide PostgresTaskStore.from_env()
def close_default_store() -> None: ...            # closes it if created (lifespan shutdown)

# postgres.py
class PostgresTaskStore:
    def __init__(self, conninfo: str, *, max_idle: int = 5, max_open: int = 10) -> None: ...  # never connects
    @classmethod
    def from_env(cls) -> PostgresTaskStore: ...   # conninfo = os.environ.get("DATABASE_URL", "")
    def add(self, title: str, due_date: str | None) -> Task: ...
    def list(self) -> list[Task]: ...
    def ping(self, timeout: float = 1.0) -> bool: ...
    def close(self) -> None: ...                  # closes idle connections and the ping executor; idempotent
```

Pseudocode of a store operation:

```
with self._connection() as conn:        # semaphore (2 s) -> idle conn checked with SELECT 1, else psycopg.connect(...)
    self._ensure_schema(conn)           # once per store: advisory xact lock + CREATE TABLE IF NOT EXISTS
    INSERT INTO tasks (id, title, due_date) VALUES (%s, %s, %s)   -- add, then commit
    SELECT id, title, due_date FROM tasks ORDER BY seq            -- list
# OperationalError / InterfaceError / semaphore timeout -> discard conn, drain idle, raise StoreUnavailable
```

## Contract

The HTTP contract of `docs/specs/001-create-and-list-in-memory-tasks/design.md` holds unchanged (fields, validation, `422` body), plus:

### `POST /tasks`

- `201` as in 001; the row is committed before the response (AC-002.1).
- `422` as in 001; validation runs before the store is touched, so nothing is stored (AC-002.3).
- `503` `{"detail": "Task store unavailable"}` (exactly this body, `application/json`) when the database is unreachable, times out or the connection is lost; nothing is stored (AC-002.4). Answered within 6 s.

### `GET /tasks`

- `200` as in 001: array of `{"id", "title", "due_date"}` ordered by creation (`seq`) across every instance on the same database (AC-002.1, AC-002.2).
- `503` `{"detail": "Task store unavailable"}` as above (AC-002.4).

### Probes

- `GET /health`: `200` `{"status": "ok"}`, never touches the database (AC-002.5).
- `GET /ready`: `200` `{"status": "ready"}` when `ping(timeout=1.0)` is true; otherwise `503` `{"status": "not ready"}` (AC-002.5, AC-002.6). Answered within about 1 s.

Recovery: no state survives an outage that blocks the next request; the first request after the database is reachable again connects fresh and succeeds (AC-002.6).

### Test hooks (in-process tests; for the testers)

- **An instance** is a `PostgresTaskStore(url)` (import from `taskboard20_api.tasks.postgres`) put behind the app with `app.dependency_overrides[get_task_store] = lambda: store`, as in 001. `/ready` uses the same dependency, so the override drives it too.
- **Restart** (AC-002.1): `store.close()`, then a new `PostgresTaskStore(url)` against the same database.
- **Two instances** (AC-002.2): two `PostgresTaskStore(url)` objects on the same database; switch the override between requests.
- **Unreachable at start** (AC-002.4): a store on `postgresql://u@127.0.0.1:<free port with no listener>/db` (connection refused); a non-answering database is a local TCP listener that accepts and never replies (connect times out after 2 s).
- **Outage and recovery** (AC-002.4 - AC-002.6): stop the test server with `pg_ctl stop -m fast` and start it again on the same port and data directory, using the same store object throughout.
- **Harness** (owned by the testers in `tests/conftest.py`): a session-scoped throwaway server via `initdb` + `pg_ctl` (devbox `postgresql@16`; trust auth, a free port, data and socket dir under a temp dir), or the server at `TEST_DATABASE_URL` when set; a fresh database per test (`CREATE DATABASE` / `DROP DATABASE ... WITH (FORCE)`) so tests do not see each other's rows; and `DATABASE_URL` set for the session to the server, so the default store (as used by `tests/test_health.py`'s `/ready` test without an override) is ready.
- Smoke tests reach the deployed service only through `SMOKE_BASE_URL`, never assume an empty list, and may hit either replica: a task created through one request is listed by the next (shared database).

## Data

Table `tasks`, created by the service (no migration tool):

```sql
CREATE TABLE IF NOT EXISTS tasks (
    seq      BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- creation order (AC-002.2)
    id       UUID NOT NULL UNIQUE,                             -- returned as str
    title    TEXT NOT NULL,                                    -- as sent, untrimmed
    due_date DATE NULL
);
```

Created in task t1's `PostgresTaskStore._ensure_schema`. Existing in-memory tasks are not migrated: they vanish with the old pods, as spec 001 already stated.
