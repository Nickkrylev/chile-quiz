# Multi-Test Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the single-test application into a multi-test platform with direct student links, a versatile quiz editor, timed or untimed attempts, and per-test results.

**Architecture:** Keep Flask, SQLite, JSON question sets, and the existing single-page frontend. Add an idempotent SQLite migration, parameterize student attempt flows by public test code, and snapshot question data and timer settings into every attempt. Add teacher APIs for library/edit/publish/results and extend the frontend with a library/editor/student forms for the three question types.

**Tech Stack:** Python 3.10+, Flask, SQLite, vanilla JavaScript, HTML, CSS.

**Spec:** `docs/superpowers/specs/2026-10-22-multi-test-platform-design.md`

## Global Constraints

- Student email is any syntactically valid address and is not verified.
- One attempt is allowed per casefolded email per test.
- Test states are `draft`, `closed`, and `open`.
- Questions support one choice, multiple choices with exact-set grading, and short text matched after trimming, whitespace normalization, and casefolding.
- Each question is worth one point; attempts store immutable question, answer-key, and timer snapshots.
- Timers are per-question, optional, 20 seconds by default on new tests, and 20 seconds on the existing test.
- Editing an open test closes it for new attempts; existing attempts continue from their snapshots.
- Student endpoints never return answer keys before the existing permitted result/detail contexts.
- Preserve the existing test ID, content, keys, attempts, and answers during migration.
- Do not change the remote VPS as part of local implementation.

## Review Focus

- Migration against an existing populated database: owned by Task 1; preserve old test and attempt state without destructive table recreation.
- Repeated/parallel start using case-variant emails: owned by Task 2; the transaction returns one attempt for that test/email.
- Email address previously used under a different identity provider: owned by Task 3; resume its test attempt rather than create a duplicate.
- Closing a test while an attempt is active, or editing while open: owned by Tasks 2 and 4; stop new starts while existing snapshots remain usable.
- Malformed questions and answer payloads, including duplicate/out-of-range indices and empty accepted text: owned by Tasks 2 and 4; reject the whole write with no partial mutation.

---

## File map

- `app/schema.sql`: add test state, public code, description and timer fields; add attempt snapshots and answer payload fields.
- `app/db.py`: apply repeatable migrations and backfill the existing test/attempt rows.
- `app/attempts.py`: generic start/resume/answer/timer/grading behavior keyed by test.
- `app/auth.py`: accept any valid email, normalize it, and resume by the selected test's participant identity.
- `app/teacher.py`: test-library CRUD, preview, publish/close, scoped overview/results/export.
- `app/__init__.py`: render test routes and keep asset URLs valid under `/testing/` prefix.
- `index.html`: generate prefix-aware static URLs and metadata.
- `static/app.js`: route-aware boot, teacher library/editor, typed answer forms and per-test results.
- `static/styles.css`: responsive library/editor and question-type controls consistent with existing visual system.
- `README.md`: document creation, sharing, email identity behavior, timer, and migration.

## Task 1: Repeatable schema migration

**Files:** `app/schema.sql`, `app/db.py`

- [ ] Add nullable migration columns for `tests.public_code`, `description`, `status`, and `seconds_per_question`; add `attempts.participant_email`, `seconds_per_question`, and any required snapshot version marker; add `answers.selection` and `answers.text_response` while retaining integer `choice` for old rows.
- [ ] In `init_db()`, inspect `PRAGMA table_info` before each `ALTER TABLE`, then backfill legacy test `id=1` with a cryptographically random URL-safe code, preserved title/questions/version, 20-second setting, and status `open` only when both legacy `is_open` and `keys_approved` are true.
- [ ] Backfill every existing attempt's participant email from its owner and timer to 20 seconds; leave all existing answers and question snapshots untouched.
- [ ] Keep `init_db()` repeatable: a second call leaves codes, statuses, snapshots, and row counts unchanged.
- [ ] Record migration fields and email-duplicate behavior in code comments/docstrings.

## Task 2: Attempt engine and grading

**Files:** `app/attempts.py`

**Interfaces:**
- Consumes: migrated `tests`, `attempts`, and `answers` columns.
- Produces: `start_attempt(user_id: int, test_id: int, participant_email: str, now: float) -> dict`, `attempt_state(user_id: int, attempt_id: int, now: float) -> dict`, and `submit_answer(user_id: int, attempt_id: int, question_index: int, answer: object, now: float) -> dict`.

- [ ] Replace fixed 20-question/four-choice behavior with validation and grading based on question type and saved snapshots.
- [ ] Start/resume inside `BEGIN IMMEDIATE`: resolve prior attempt by casefolded participant email and test; otherwise require `status='open'`, copy questions/timer/email into attempt, and set deadline only when timer is enabled.
- [ ] Make `_advance()` honor snapshotted timer: auto-skip overdue questions only for timed attempts; untimed attempts remain active until submitted.
- [ ] Grade single choice by membership in accepted indices; grade multiple choice by exact set equality; grade short text by trimming, collapsing whitespace, and casefolding against accepted strings.
- [ ] Accept answer payloads with exact shapes: `{choice: int}`, `{choices: list[int]}`, or `{text: str}`; reject duplicate, boolean, negative, out-of-range, empty, and oversized values.
- [ ] Return only current prompt/content/choices and remaining time during an attempt; never include keys. Return score, answered count, total, and status after completion.
- [ ] Preserve idempotent stale-answer behavior and ownership checks.

## Task 3: Student identity and public test routes

**Files:** `app/auth.py`, `app/attempts.py`, `app/__init__.py`, `index.html`

**Interfaces:**
- Consumes: attempt engine interfaces from Task 2.
- Produces: `/t/<public_code>` page; `GET /api/tests/<public_code>` public test metadata; test-scoped `POST /api/tests/<public_code>/attempts`, `GET /api/tests/<public_code>/attempts/current`, and existing answer endpoint scoped by owned attempt.

- [ ] Validate email syntax and length without requiring `STUDENT_DOMAIN`; normalize with `casefold()` before lookup and session identity creation.
- [ ] Resolve a legacy user with an existing attempt for the requested test/email before creating or selecting a student identity; preserve current attempt ownership and names.
- [ ] Add a Flask test route that resolves the public code, returns 404 for unknown codes, and prevents draft metadata from being exposed to students.
- [ ] Include `SCRIPT_NAME`-aware static asset URLs so `/testing/t/<code>` loads assets at `/testing/static/...`.
- [ ] Make public test metadata include title, description, open/closed state, question count, and timer settings, but no answer keys.
- [ ] Keep a compatibility redirect from the old root student route to test id 1's public URL where appropriate; keep teacher entry available at `/`.

## Task 4: Teacher API and per-test results

**Files:** `app/teacher.py`

**Interfaces:**
- Produces protected endpoints: `GET/POST /api/teacher/tests`, `GET/PUT /api/teacher/tests/<int:test_id>`, `POST /api/teacher/tests/<int:test_id>/state`, `GET /api/teacher/tests/<int:test_id>/preview`, plus scoped attempts/detail/export endpoints.

- [ ] Implement test list/create/read/update with server-side validation, CSRF and teacher role. New tests get random stable public codes and `draft` state.
- [ ] Validate all question types, answer keys, counts, text lengths, and timer bounds before the transaction; reject invalid saves without partial writes.
- [ ] Save updates atomically, increment `version`, and change `open` to `closed`. Preserve legacy key approval requirements for test id 1.
- [ ] Publish only complete tests; closing never mutates attempts. Record create/save/open/close audit events.
- [ ] Scope overview, average percentage, pagination, search, details and CSV by test ID. Compute score maximum and percent from each attempt's snapshot length; CSV carries test title and score/max.
- [ ] Preserve CSV formula-injection protections and escaping for user supplied names, emails, and answer text.

## Task 5: Teacher library and editor UI

**Files:** `static/app.js`, `static/styles.css`

**Interfaces:**
- Consumes: Task 4 teacher endpoints.
- Produces: library screen, test editor, preview, per-test results, share-link copy action.

- [ ] Replace the single dashboard as the landing view for teachers with a library of test cards showing state, attempt count, edit, results, preview, copy link, and open/close actions.
- [ ] Add create flow with title, description, default 20-second timer setting and blank initial question.
- [ ] Build reusable dynamic question cards for one choice, multiple choice and short text; support add/remove/reorder questions and choices, set answer keys, preserve values on validation/network errors.
- [ ] Show legacy key clarification UI for test id 1; keep its special approval workflow intact.
- [ ] Add publish confirmation and closed/open status labels. A save while open must display that it closed new attempts.
- [ ] Render student preview through the same question component without persisting an attempt.
- [ ] Add test-scoped participant filters, dynamic score/max details, answer detail rendering and CSV link.
- [ ] Use HTML escaping for all user-controlled text and clipboard fallback when Clipboard API is unavailable.

## Task 6: Student forms and typed answer flow

**Files:** `static/app.js`, `static/styles.css`

**Interfaces:**
- Consumes: Task 3 public metadata and Task 2 attempt APIs.
- Produces: direct-link intro, identity form, rules, question flow, result screen.

- [ ] Resolve current test from URL, then load its public metadata and existing attempt state.
- [ ] Replace the hard-coded university domain hint with generic email label and copy stating that the address identifies the participant and is not verified.
- [ ] Render radio inputs for single choice, checkboxes for multiple choice, and text input/textarea for short answer; submit the matching JSON payload.
- [ ] Use timer and question count from server state; hide countdown when disabled; keep all deadlines server-authoritative.
- [ ] Show result numerator and denominator dynamically. Closed tests cannot start; active attempts remain available after closure.
- [ ] Preserve current account/logout/teacher login behaviors.

## Task 7: Responsive styling and user documentation

**Files:** `static/styles.css`, `README.md`

- [ ] Add responsive styles for test library cards, editor question blocks, controls, and student forms using the existing palette, spacing, and focus treatment.
- [ ] Document teacher workflow, student share URL, accepted question types, exact grading rules, configurable timer, unverified email limitation, and local database migration behavior.
- [ ] Update obsolete README language that says the application contains a single fixed test or enforces the student domain.

## Execution notes

Implement tasks in order because each task defines interfaces used by later tasks. Keep changes local; no remote deployment. The workspace instructions for this task prohibit adding or running tests unless specifically requested, so do not add test files or execute test commands during implementation.
