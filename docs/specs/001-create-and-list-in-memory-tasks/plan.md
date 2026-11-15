---
spec_id: 001-create-and-list-in-memory-tasks
shape: service-python
spec_hash: 54f882553ea7
summary: In-memory task resource with POST /tasks and GET /tasks
tasks:
  - id: t1
    title: Add tasks package (models, in-memory store, router) and wire it into the app
    files: [src/taskboard20_api/tasks/__init__.py, src/taskboard20_api/tasks/models.py, src/taskboard20_api/tasks/store.py, src/taskboard20_api/tasks/router.py, src/taskboard20_api/main.py]
    covers: [AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7]
    parallel_safe: true
    depends_on: []
    done: true
---

# Plan — 001 Create and list in-memory tasks

One task: the feature is four small modules plus one line of wiring, and none of it can be checked through the API until the router is mounted, so splitting would only produce a task whose acceptance tests cannot pass alone. See [design.md](design.md) for the contract.

## t1 — Add tasks package (models, in-memory store, router) and wire it into the app

**Files:** src/taskboard20_api/tasks/__init__.py, src/taskboard20_api/tasks/models.py, src/taskboard20_api/tasks/store.py, src/taskboard20_api/tasks/router.py, src/taskboard20_api/main.py
**Covers:** AC-001.1, AC-001.2, AC-001.3, AC-001.4, AC-001.5, AC-001.6, AC-001.7
**Goal:** Clients can create a task with a title and optional due date and list all tasks in creation order, held in process memory, with validation errors answered as FastAPI's standard `422`.

**Implementation notes:**
- `models.py`: `TaskCreate` with `title: StrictStr` (`max_length=200`, field validator rejecting `not v.strip()`, value returned untrimmed) and `due_date: str | None = None` (validator: full match `^\d{4}-\d{2}-\d{2}$`, then `date.fromisoformat`; raise `ValueError` on either failure so `loc` ends with `due_date`). Keep the default `extra="ignore"`. `Task` with `id: str`, `title: str`, `due_date: str | None`.
- `store.py`: `TaskStore` with a `threading.Lock`, an insertion-ordered `dict[str, Task]`, `add(title, due_date) -> Task` (id `str(uuid.uuid4())`) and `list() -> list[Task]` (copy). Module-level `_store = TaskStore()` and `get_task_store() -> TaskStore` returning it.
- `router.py`: `APIRouter(tags=["tasks"])`; `POST /tasks` (`status_code=201`, `response_model=Task`) and `GET /tasks` (`response_model=list[Task]`), both sync `def`, taking `store: TaskStore = Depends(get_task_store)`.
- `__init__.py`: re-export `router`.
- `main.py`: `app.include_router(tasks.router)` after the middleware setup; health, ready, ping and metrics stay unchanged.
- Log one structured event per created task (`task_created`, field `task_id`; not the title) via structlog, as the existing logging setup does.
- The metrics middleware labels by route template, so `/tasks` needs no change there.

**Done when:** the acceptance tests for AC-001.1 to AC-001.7 pass (in-process, using the `get_task_store` override from design.md for a fresh store), and `devbox run quality` and `devbox run test` pass.
