# Verification — 002 Persistent tasks in Postgres with 503 and readiness on a database outage

**Result:** pass
**Commit:** 9204649 · **Base:** 7095291 · **Trace:** 6/6 criteria named by tests (`tests/test_tasks_postgres.py`)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-002.1 | met | `tests/test_tasks_postgres.py::test_task_survives_restart` | `src/taskboard20_api/tasks/postgres.py:138` (insert + commit before return), `:150-157` (list), `:25-32` (table) | Posts `Buy milk` / `2026-12-01`, closes the store, opens a new one on the same database; asserts `200` and the list equals `[created.json()]` (same `id`, `title`, `due_date`). "Restart" is the design's test hook (new store object), not a new process; acceptable for an in-process test. |
| AC-002.2 | met | `tests/test_tasks_postgres.py::test_two_instances_list_in_creation_order` | `postgres.py:27` (`seq` identity), `:153` (`ORDER BY seq`); `tasks/store.py:57` | A via first, B via second (no `due_date`), C via first; each instance lists `A,B,C`, equal to the `201` bodies, exactly `{id,title,due_date}`, B's `due_date` `None`. |
| AC-002.3 | met | `tests/test_tasks_postgres.py::test_rejected_input_not_stored` (6 cases) | `tasks/router.py:23-31` (validation by `TaskCreate` before the store is called); models unchanged | Asserts `422`, every `loc[-1]` equals the field, `GET /tasks` is `[]` both on the same store and after a restart (new store). |
| AC-002.4 | met | `test_unreachable_at_start_answers_503`, `test_non_answering_database_answers_503_within_6s`, `test_outage_answers_503_and_creates_nothing` | `postgres.py:58-68` (`connect_timeout=2`, `statement_timeout=3000`, `tcp_user_timeout`), `:89-113` (OperationalError/InterfaceError → `StoreUnavailable`), `router.py:19-20,26-29,37-40` (`503 {"detail": "Task store unavailable"}`) | Covers refused at start, non-answering listener and a running-then-stopped server; each asserts `< 6 s`, `503` and the exact body; after recovery the list holds only `before`, so nothing was created. |
| AC-002.5 | met | `test_probes_during_outage`, `test_probes_when_unreachable_at_start` | `main.py:51-56` (`/ready` → `store.ping()`, `503 {"status": "not ready"}`), `main.py:45-48` (`/health` untouched), `postgres.py:164-169` (1 s client-side bound) | Asserts `/ready` `503` with `{"status": "not ready"}` and `/health` `200` `{"status": "ok"}`, both during an outage and when unreachable at start. |
| AC-002.6 | met | `test_recovers_without_restart`, `test_recovers_when_unreachable_at_start` | `postgres.py:76-87` (idle connection checked with `SELECT 1`, else fresh connect), `:99-104` (drain idle on failure), `:127-135` (schema flag set only after commit) | Same store object throughout: `503` during the outage, then `POST` `201`, `GET` `200` listing the new task, `/ready` `200` `{"status": "ready"}`; also for a store created while the database was down. |

## Non-goals

The spec lists no non-goals. No template-owned layout (Dockerfile, `ci.yml`, `devbox.json` recipes) was changed; `devbox.json` only gains the `postgresql@16` package, as planned. No authentication, ORM or migration tool was added (contract and design exclude them). ✔

## Deviations from the plan

- `tests/conftest.py`, `tests/test_health.py`, `tests/test_tasks.py`, `tests/test_tasks_postgres.py` are in no task's `files`: the testers' acceptance tests and Postgres harness, which design.md assigns to the testers; acceptable.
- `tests/test_tasks.py`: AC-001.7's two tests are removed and one renamed to `test_fresh_in_memory_store_lists_empty` (AC-001.5); AC-001.7 is struck in spec 001 as superseded by AC-002.1, as design.md foresees; acceptable.
- `devbox.lock` is in no task's `files`: the lock refresh that goes with t1's `devbox.json` change; acceptable.
- `docs/adr/001-postgres-task-store.md`, `docs/adr/README.md`, `docs/backlog.md`, spec 001 `spec.md`, and spec 002's `spec.md` / `plan.md` / `design.md` changed in the spec and plan commits before the build (the ADR design.md asks for); acceptable.
- Both tasks are `done: true`. Every planned file was touched.

## Contract

Matches `design.md`: `503 {"detail": "Task store unavailable"}` for `POST` and `GET /tasks` (`router.py:19-20`); `/ready` `200 {"status": "ready"}` / `503 {"status": "not ready"}` (`main.py:51-56`); `/health` unchanged; table `tasks` with `seq` identity, `UUID` id, `TEXT` title, `DATE` due_date (`postgres.py:25-32`); config only from `DATABASE_URL` / `PG*` (`postgres.py:52-54`, `docs/env-vars.md`). Signatures of `TaskRepository`, `get_task_store`, `close_default_store` and `PostgresTaskStore` match design.md. ✔

## Smoke

- `tests/test_smoke_tasks.py` (untouched by this build): `test_smoke_ac_001_5_list_tasks` passes on an empty list and with the old in-memory store, and no smoke test creates a task and then lists it, so persistence and the shared database across two replicas (spec note "Smoke tests must ... tolerate two replicas") are not smoke-checked after a deploy. No smoke test checks `/ready` against the database either. Not a criterion failure.

## Mutation check (report only)

10 of 20 mutants of the changed code were caught by the acceptance tests (50 %; spec 152, report only).

Survived (a test that names the criterion would fail if it checked this):
- `src/taskboard20_api/tasks/postgres.py:54 return value → None`
- `src/taskboard20_api/tasks/postgres.py:42 5 → 6`
- `src/taskboard20_api/tasks/postgres.py:122 Lt → GtE`
- `src/taskboard20_api/tasks/postgres.py:61 2 → 3`
- `src/taskboard20_api/tasks/postgres.py:64 5 → 6`
- `src/taskboard20_api/tasks/postgres.py:66 2 → 3`
- `src/taskboard20_api/tasks/postgres.py:99 IsNot → Is`
- `src/taskboard20_api/tasks/postgres.py:173 False → True`
- `src/taskboard20_api/tasks/store.py:50 return value → None`
- `src/taskboard20_api/tasks/store.py:74 IsNot → Is`
