# Verification — 001 Create and list in-memory tasks

**Result:** pass
**Commit:** 83280b7 · **Base:** 8684198 · **Trace:** 7/7 criteria named by tests (smoke: AC-001.1, AC-001.5)

| Criterion | Verdict | Tests | Implementation | Notes |
|---|---|---|---|---|
| AC-001.1 | met | `tests/test_tasks.py::test_create_task_returns_201_with_fields`, `tests/test_tasks.py::test_create_task_ignores_client_id`, `tests/test_smoke_tasks.py::test_smoke_ac_001_1_create_task` | `src/taskboard20_api/tasks/router.py:19`, `src/taskboard20_api/tasks/store.py:19`, `src/taskboard20_api/main.py:26` | asserts 201, non-empty string `id`, `title` "Buy milk", `due_date` "2026-12-01", exactly three fields; client `id` ignored (A7) |
| AC-001.2 | met | `tests/test_tasks.py::test_create_task_without_due_date`, `tests/test_tasks.py::test_create_task_with_null_due_date` | `src/taskboard20_api/tasks/models.py:17`, `src/taskboard20_api/tasks/models.py:29` | both forms (absent, `null`) assert 201 and `due_date is None` |
| AC-001.3 | met | `tests/test_tasks.py::test_invalid_title_rejected` (7 cases), `tests/test_tasks.py::test_title_of_200_chars_accepted` | `src/taskboard20_api/tasks/models.py:16`, `src/taskboard20_api/tasks/models.py:19-24` | missing, `null`, int, list, empty, whitespace, 201 chars: 422, every error `loc[-1] == "title"`, then `GET /tasks == []`; 200-char boundary accepted |
| AC-001.4 | met | `tests/test_tasks.py::test_invalid_due_date_rejected` (6 cases) | `src/taskboard20_api/tasks/models.py:26-34` | the three spec examples plus `""`, int, `2026-1-1`: 422, `loc[-1]` list equals `["due_date"]`, then `GET /tasks == []` |
| AC-001.5 | met | `tests/test_tasks.py::test_list_tasks_shape`, `tests/test_smoke_tasks.py::test_smoke_ac_001_5_list_tasks` | `src/taskboard20_api/tasks/router.py:27-30`, `src/taskboard20_api/tasks/models.py:37-42` | 200, array of 2, each item's keys exactly `{id, title, due_date}` |
| AC-001.6 | met | `tests/test_tasks.py::test_list_tasks_in_creation_order` | `src/taskboard20_api/tasks/store.py:16`, `src/taskboard20_api/tasks/store.py:25-27` | `listed == created` (order and field equality), titles A, B, C, 3 distinct ids |
| AC-001.7 | met | `tests/test_tasks.py::test_fresh_service_lists_empty`, `tests/test_tasks.py::test_tasks_do_not_survive_restart` | `src/taskboard20_api/tasks/store.py:30-35` | fresh store -> 200 `[]`; restart simulated by a new `TaskStore` via the design's dependency-override hook; process-local module store means a real restart starts empty |

Note (not blocking): `models.py:31` uses `_DATE_RE.match` with `$`, not `fullmatch` as the plan says; `$` also matches before a trailing `\n`. `datetime.date.fromisoformat` is expected to reject `"2026-12-01\n"`, so behaviour holds, but `fullmatch` would match the plan exactly.

## Non-goals

No update, complete, delete or get-by-id route; no persistence or shared storage; no auth; no pagination, filtering or caps; `due_date` is date-only. No template-owned layout change (`main.py` gains only the import and `include_router`; health, ready, ping and metrics unchanged). ✔

## Deviations from the plan

- `router.py:13` creates `APIRouter()` without `tags=["tasks"]` as the plan notes; affects only OpenAPI grouping, no criterion or contract field. Acceptable.
- Dependency injected as `Annotated[TaskStore, Depends(get_task_store)]` instead of a default-argument `Depends`; equivalent. Acceptable.
- `docs/specs/001-create-and-list-in-memory-tasks/spec.md` (status `building` and Changelog line), `design.md`, `plan.md`, `tests/test_tasks.py`, `tests/test_smoke_tasks.py` are outside t1's `files`: spec lifecycle and acceptance-test artefacts. Acceptable.
- t1 is `done: true`; no task left open.

## Contract

Matches `design.md`: `POST /tasks` 201 with exactly `id` (uuid4 string), `title` (untrimmed), `due_date`; FastAPI standard 422 with `loc` ending in the offending field, nothing stored; `GET /tasks` 200 array in creation order; `extra` ignored; `StrictStr` title; strict `YYYY-MM-DD` due date validated by regex plus `date.fromisoformat`. `task_created` log event carries `task_id` only (`router.py:23`). ✔

## Smoke tests

`tests/test_smoke_tasks.py`: the AC-001.1 test is `smoke` + `writes`, uses a `smoke-<uuid>` title and only the base URL; the AC-001.5 test is read-only and fails on a missing route (404 raises). With an empty list in staging or prod its per-item key check is vacuous, but it still requires a 200 JSON array from `/tasks`, which only the feature serves. No SMOKE findings.

## Test review

Unresolved test-review findings: none (the one finding in the review commit was resolved in `d4cb90e`). No acceptance test changed since red commit `29a078f`.

## Mutation check (report only)

11 of 13 mutants of the changed code were caught by the acceptance tests (85 %; spec 152, report only).

Survived (a test that names the criterion would fail if it checked this):
- `src/taskboard20_api/tasks/models.py:30 return value → None`
- `src/taskboard20_api/tasks/store.py:35 return value → None`
