---
spec_id: 001-create-and-list-in-memory-tasks
title: Create and list in-memory tasks
status: done
priority: P1
shape: service-python
---

# 001 — Create and list in-memory tasks

## Problem

The Task API has health, readiness and metrics endpoints but no tasks yet, so a client has nothing to record or show. Callers need the smallest useful task board: add a task with a title and, optionally, a due date, and read back every task. Keeping tasks in memory gives clients a working API now, without choosing or running a database.

## Stories

As an API client, I want to create a task with a title and an optional due date, so that I can record what has to be done and by when.

As an API client, I want to list all tasks, so that I can show the current task board.

## Acceptance criteria

- **AC-001.1** Given a running service, when a client sends `POST /tasks` with JSON `{"title": "Buy milk", "due_date": "2026-12-01"}`, then the response is `201` with a JSON body holding a server-assigned string `id`, `"title": "Buy milk"` and `"due_date": "2026-12-01"`. (smoke)
- **AC-001.2** Given a running service, when a client sends `POST /tasks` with only `{"title": "Call Bob"}` (or with `"due_date": null`), then the response is `201` and the body holds `"due_date": null`.
- **AC-001.3** Given a running service, when a client sends `POST /tasks` whose `title` is missing, not a string, empty, only whitespace, or longer than 200 characters, then the response is `422` with an error body naming the `title` field, and a following `GET /tasks` does not contain that task.
- **AC-001.4** Given a running service, when a client sends `POST /tasks` whose `due_date` is not a calendar date in `YYYY-MM-DD` form (for example `"tomorrow"`, `"2026-02-30"` or `"2026-12-01T10:00:00Z"`), then the response is `422` with an error body naming the `due_date` field, and no task is created.
- **AC-001.5** Given a running service, when a client sends `GET /tasks`, then the response is `200` with a JSON array of task objects, each with exactly the fields `id`, `title` and `due_date`. (smoke)
- **AC-001.6** Given tasks A, B and C created in that order, when a client sends `GET /tasks`, then the array lists A, B, C in creation order, each `id` is distinct, and each task's fields equal those returned when it was created.
- **AC-001.7** Given a freshly started service, when a client sends `GET /tasks`, then the response is `200` with `[]`; tasks created before a restart are not listed after it.

## Non-goals

- Updating, completing or deleting tasks; fetching a single task by id.
- Persistent storage, or tasks shared between several running instances.
- Authentication, authorization and per-user task lists.
- Pagination, filtering, sorting other than creation order, and a cap on the number of tasks.
- Due times or time zones (a due date is a calendar date only).

## Assumptions

- **A1** The resource lives at `/tasks`: `POST /tasks` creates, `GET /tasks` lists (other option: a versioned path such as `/v1/tasks`; affects AC-001.1–AC-001.7).
- **A2** A task carries exactly `id`, `title`, `due_date`; no `created_at` or status field (other option: add `created_at` and `done`; affects AC-001.1, AC-001.5).
- **A3** `id` is a server-assigned opaque unique string (a UUID); clients cannot set it (other option: ascending integers from 1; affects AC-001.1, AC-001.6).
- **A4** `title` must contain at least one non-whitespace character and is at most 200 characters; it is stored and returned exactly as sent, without trimming (other option: trim surrounding whitespace, other length limit; affects AC-001.3).
- **A5** `due_date` is an ISO 8601 calendar date `YYYY-MM-DD`; dates in the past are accepted (other option: reject past dates, or accept a date-time; affects AC-001.1, AC-001.4).
- **A6** Validation errors answer `422` in the framework's standard error format, which names the offending field (other option: `400` with a custom error body; affects AC-001.3, AC-001.4).
- **A7** Unknown fields in the create request are ignored (other option: reject them with `422`; affects AC-001.1).
- **A8** The list is unauthenticated and open to any caller of the service, which is acceptable because tasks are throwaway in-memory data (other option: require an API key; affects AC-001.1, AC-001.5).
- **A9** Tasks live in the memory of one service instance and are lost on restart; consistent results assume a single replica (other option: shared storage; affects AC-001.6, AC-001.7).

## Notes for the architect

- With more than one replica, a task created on one instance is not listed by another; the smoke checks are therefore phrased so that each needs only a single response.

## Open questions

## Changelog

- 2026-11-15 created
- 2026-11-15 approved
- 2026-11-15 building
- 2026-11-15 done
