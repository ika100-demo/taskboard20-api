# Design — 001 Create and list in-memory tasks

## Decisions

- One new package `taskboard20_api.tasks` (models, store, router) that `main.py` includes with `app.include_router`. This keeps `main.py` as the wiring point, as the template has it, and gives later task specs (update, delete, persistence) one place to grow.
- The store is a process-local `TaskStore` (insertion-ordered dict guarded by a `threading.Lock`, since FastAPI runs sync endpoints in a thread pool). Handlers receive it through the FastAPI dependency `get_task_store`, which returns one module-level instance. Tests get a fresh, empty store by overriding that dependency, which is how AC-001.7 ("freshly started service") is tested in-process. No ADR: the in-memory store is a feature-local stop-gap that a persistence spec replaces (non-goal of this spec).
- `due_date` is validated as a strict `YYYY-MM-DD` string (regex `^\d{4}-\d{2}-\d{2}$`, then `datetime.date.fromisoformat`), not with Pydantic's `date` type: in lax mode Pydantic also accepts Unix timestamps and date-times with a zero time, which AC-001.4 must reject. The stored and returned value is the same ISO string.
- `title` is a strict string (`StrictStr`, so `123` or `true` is rejected, not coerced), `max_length=200`, plus a validator rejecting strings with no non-whitespace character; the value is stored untrimmed (A4).
- Validation errors use FastAPI's standard `422` body (A6); no custom exception handler.
- Request model ignores unknown fields (Pydantic default `extra="ignore"`, A7), so a client-sent `id` is ignored, never used.
- The spec's note on multiple replicas is followed: nothing in the design depends on more than one response, and the service keeps assuming a single replica (A9).

## Modules

| Module | Responsibility | New / changed |
|---|---|---|
| `src/taskboard20_api/tasks/__init__.py` | re-exports `router` | new |
| `src/taskboard20_api/tasks/models.py` | `TaskCreate` (request), `Task` (response) | new |
| `src/taskboard20_api/tasks/store.py` | `TaskStore`, `get_task_store` dependency | new |
| `src/taskboard20_api/tasks/router.py` | `POST /tasks`, `GET /tasks` | new |
| `src/taskboard20_api/main.py` | `app.include_router(tasks.router)` | changed |

```python
# models.py
class TaskCreate(BaseModel):          # extra fields ignored
    title: StrictStr                  # 1..200 chars, at least one non-whitespace char, not trimmed
    due_date: str | None = None       # YYYY-MM-DD and a real calendar date, or null/absent

class Task(BaseModel):
    id: str                           # str(uuid.uuid4())
    title: str
    due_date: str | None

# store.py
class TaskStore:
    def __init__(self) -> None: ...   # empty
    def add(self, title: str, due_date: str | None) -> Task: ...   # assigns id, appends
    def list(self) -> list[Task]: ... # creation order, a copy

def get_task_store() -> TaskStore: ...  # the process-wide instance
```

## Contract

All bodies are `application/json`.

### `POST /tasks` (AC-001.1 – AC-001.4)

Request body:

| Field | Type | Rule |
|---|---|---|
| `title` | string | required; JSON string only (no coercion); length 1–200; at least one non-whitespace character; stored as sent |
| `due_date` | string or null | optional, default `null`; exactly `YYYY-MM-DD` and a valid calendar date (`2026-02-30` is rejected, a date-time is rejected); past dates accepted |
| any other field | — | ignored (including `id`) |

Responses:

- `201` — the created task: `{"id": "<uuid4 string>", "title": "<as sent>", "due_date": "<YYYY-MM-DD>" | null}`. Exactly these three fields.
- `422` — FastAPI's standard validation body; nothing is stored:

  ```json
  {"detail": [{"type": "<error type>", "loc": ["body", "title"], "msg": "<message>", "input": "<offending value>"}]}
  ```

  `loc` ends with `"title"` for any title error (missing, not a string, empty, whitespace only, over 200 chars) and with `"due_date"` for any due-date error. A body that is not a JSON object answers `422` with `loc` `["body"]`. Tests assert on the status and on `loc[-1]`, not on `type` or `msg`.

### `GET /tasks` (AC-001.5 – AC-001.7)

- `200` — JSON array of task objects, each exactly `{"id", "title", "due_date"}`, in creation order; `[]` on a fresh process. Values equal those returned by the `POST` that created each task.

### Test hook (in-process tests only)

A fresh service is simulated by `app.dependency_overrides[get_task_store] = lambda: store` with `store = TaskStore()` created once per test (import from `taskboard20_api.tasks.store`); the override is removed after the test. Smoke tests reach the deployed service only through `SMOKE_BASE_URL` and must not assume an empty list there.

## Data

None persisted. Tasks live in the `TaskStore` of one process and vanish on restart (AC-001.7, A9).
