---
spec_id: 002-persistent-tasks-in-postgres-with-503
title: Persistent tasks in Postgres with 503 and readiness on a database outage
status: done
priority: P1
shape: service-python
parent: ika100-demo/taskboard20-gitops:001-persistent-tasks-and-web-task-board
---

# 002 — Persistent tasks in Postgres with 503 and readiness on a database outage

## Problem

The Task API keeps tasks in the memory of one instance, so every restart or redeploy loses all tasks, and a second replica would show a different list. The only way to use the board is to call the API directly; the web site is a fresh template that shows no tasks. People need tasks that survive restarts and a page where they can see the board and add tasks without a tool. A Postgres database for the API and a task board in the web UI deliver both.

## System context

Slice of the system plan `001-persistent-tasks-and-web-task-board` in `ika100-demo/taskboard20-gitops` for `taskboard20-api` (service-python). The system criteria and the contract below are binding: every criterion of this spec implements one of them and names it: `(system AC-<NNN>.<n>)`.

### System criteria

- **AC-001.1** Given a task created with `POST /tasks` `{"title": "Buy milk", "due_date": "2026-12-01"}`, when every instance of the Task API is restarted or replaced by a new deployment (also with two or more replicas running), then `GET /tasks` on any instance lists that task with the same `id`, `title` and `due_date` as returned at creation, and tasks keep their creation order.
- **AC-001.2** Given the database is unreachable, when a client sends `POST /tasks` or `GET /tasks`, then the response is `503` with a JSON error body and no task is created, `GET /ready` answers non-`200` while `GET /health` stays `200`; once the database is reachable again, both task requests succeed without a restart of the Task API.

### Contract

Caller: the `taskboard20-web` server, never the browser. Callee: `taskboard20-api`, at the base URL `TASK_API_URL` (dev: `http://taskboard20-api`). Every body is `application/json`. There is no authentication (spec non-goal). The API contract is the one in the API repo's `docs/specs/001-create-and-list-in-memory-tasks/design.md`, unchanged, plus the `503` below.

### `POST /tasks`

Request body:

| Field | Type | Rule |
|---|---|---|
| `title` | string | required; a JSON string, not coerced; 1 to 200 characters; at least one non-whitespace character; stored and returned as sent, not trimmed |
| `due_date` | string or null | optional, default `null`; exactly `YYYY-MM-DD` and a real calendar date; past dates are accepted |
| other fields | — | ignored (a client-sent `id` too) |

Responses:

- `201`: the created task `{"id": "<uuid4 string>", "title": "<as sent>", "due_date": "<YYYY-MM-DD>" | null}`, exactly these three fields, stored durably before the response.
- `422`: FastAPI's validation body `{"detail": [{"type", "loc", "msg", "input"}]}`. `loc[-1]` is `"title"` or `"due_date"`. Nothing is stored.
- `503`: the database is unreachable (see Errors). Nothing is stored.

The web site sends `due_date` as the date input's `YYYY-MM-DD` value, or `null` when it is empty.

### `GET /tasks`

- `200`: a JSON array of tasks, each exactly `{"id", "title", "due_date"}`, oldest first (creation order across every replica). The values equal those of the `201` that created each task.
- `503`: the database is unreachable.

### Probes (API)

- `GET /health`: `200` `{"status": "ok"}` while the process runs, whatever the database state.
- `GET /ready`: `200` `{"status": "ready"}` when a database check (`SELECT 1`) succeeds. Otherwise `503` `{"status": "not ready"}`.

### Web site (`taskboard20-web`)

- `/` is the task board.
- `TASK_API_URL` is a runtime server-side variable.
- `/api/health` and `/api/ready` do not depend on the Task API.

The fixed texts:

| Situation | Text |
|---|---|
| no tasks | `No tasks yet` |
| task without a due date | `No due date` |
| empty or whitespace-only title | `Title is required` |
| title over 200 characters | `Title must be at most 200 characters` |
| list failed | `Tasks could not be loaded. Try again later.` |
| save failed | `Task could not be saved. Try again.` |

### Errors

- **Validation:** `422` in FastAPI's standard body (above). Callers rely only on the status and `loc[-1]`, never on `type` or `msg`.
- **Database unavailable:** `503` with `{"detail": "Task store unavailable"}`. This covers connection refused, timeouts and a lost connection. The task is not created. The API does not crash or restart: each request opens or reuses a pooled connection, so the next request after recovery succeeds.
- **Unexpected API errors:** FastAPI's default `500`.
- **How the web site treats responses:**
  - `GET /tasks`: anything but `200` with a JSON array is "could not be loaded". That includes `503`, `500`, other statuses, a non-JSON body, a connection error and a timeout.
  - `POST /tasks`: anything but `201`, or a `422` whose `loc` ends in `title`, is "could not be saved". The page keeps the input.
  - A `422` naming `due_date` is also "could not be saved": the date picker cannot normally produce one.
  - The web site never shows the API's raw error text to the person.

### Timeouts

| Call | Timeout | When it expires or the other side is down |
|---|---|---|
| web → `GET /tasks` | 3 s | the page renders with `Tasks could not be loaded. Try again later.` and the form; no retry |
| web → `POST /tasks` | 5 s | `Task could not be saved. Try again.`, input kept; no automatic retry, so no duplicate task is created |
| API → Postgres, connect | 2 s | `503` |
| API → Postgres, statement | 3 s | `503` |
| API `/ready` database check | 1 s | `/ready` `503` |

A task request to the API therefore answers within about 6 s, even while the database hangs.

The kubelet's readiness probe takes a failing API replica out of the Service. With both replicas not ready, the web site's call fails fast (connection refused) and shows the failure text.

### Provided by the system

The gitops part of this plan wires these for this repo; rely on them, do not ask for them again:

- resource `postgres`: env `DATABASE_URL`, `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGPASSWORD`
- replicas `2` in `dev`

### Notes for this repo

Storage replaces the in-memory TaskStore behind the same models and router; the HTTP contract of the repo's spec 001
(fields, validation, 422 body) stays unchanged, only its AC-001.7 is superseded. The service creates its table
itself at start, idempotently (or with a migration tool run at start); with two replicas both may start at once.
Creation order needs an ordering column filled by the database (e.g. a bigserial or insertion timestamp plus
sequence), because `id` stays a UUID string. Connection config comes only from `DATABASE_URL` / `PG*` that the
gitops entry injects; tests run against a real Postgres (e.g. a container) or an equivalent test double for the
outage cases. Smoke tests must not assume an empty list and must tolerate two replicas behind the Service.

## Stories

<!-- As a <persona>, I want <goal>, so that <benefit>. -->

## Acceptance criteria

- **AC-002.1** Given a task created with `POST /tasks` `{"title": "Buy milk", "due_date": "2026-12-01"}`, when the service is restarted against the same database (`DATABASE_URL`), then `GET /tasks` answers `200` and lists that task with the same `id`, `title` and `due_date` as returned by the `201` at creation (system AC-001.1) (replaces AC-001.7)
- **AC-002.2** Given two service instances using the same database, when tasks A, B and C are created in that order alternately through either instance, then `GET /tasks` on each instance lists A, B, C in creation order with exactly the fields `id`, `title`, `due_date`, and with `due_date` `null` for a task created without one (system AC-001.1)
- **AC-002.3** Given a running service whose database is reachable, when a client sends `POST /tasks` with a `title` or `due_date` the contract rejects, then the response is still `422` with `loc` ending in that field, and no row is stored, so a following `GET /tasks` (also after a restart) does not contain it (system AC-001.1)
- **AC-002.4** Given the database is unreachable (also when it already is at service start), when a client sends `POST /tasks` or `GET /tasks`, then within 6 seconds the response is `503` with the JSON body `{"detail": "Task store unavailable"}`, and no task is created (system AC-001.2)
- **AC-002.5** Given the database is unreachable, when the probes are called, then `GET /ready` answers `503` while `GET /health` answers `200` (system AC-001.2)
- **AC-002.6** Given the database was unreachable and becomes reachable again, when a client then sends `POST /tasks` and `GET /tasks` to the same running process, then they answer `201` and `200` and `GET /ready` answers `200`, with no restart of the service (system AC-001.2)

## Non-goals

## Assumptions

<!-- Spec 149: decisions taken by default, approved with the spec. One bullet each: - **A1** <the decision> (other option: <…>; affects AC-…). A revised one is struck through (~~…~~), never deleted. -->

## Open questions

<!-- Only what may not be decided by default (spec 149): security or access, money, destroying or migrating data, or a request too ambiguous to build. Approval is refused while any is open. Strike answered ones (~~…~~) and fold the answer into the criteria. -->

## Changelog

- 2026-11-16 created from the system plan, with its criteria (spec 147)
- 2026-11-16 approved
- 2026-11-16 building
- 2026-11-16 done
