# Teacher Question Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let teachers edit the current test, including its question and answer counts, while preserving existing attempts and removing the page branding requested by the user.

**Architecture:** Keep the current `tests` row as the latest version and use its `version` field. Teacher saves replace the question JSON atomically, close the test, and clear key approval; attempts keep their existing JSON snapshots. Student and teacher views derive counts and score maxima from those snapshots.

**Tech Stack:** Flask, SQLite, vanilla JavaScript, HTML, CSS.

**Spec:** `docs/superpowers/specs/2026-10-02-test-question-editor-design.md`

## Global Constraints

- A student still selects exactly one option for each question.
- A question must have at least two non-empty options and at least one correct option.
- A test must have at least one question.
- Each question keeps a 20-second timer.
- Saving changes closes the test and requires key review before reopening.
- Existing attempts keep their question snapshots and stored results.
- The top account/logout controls remain available after the branding is removed.

## Review Focus

- A non-teacher cannot read or save the current test.
- A malformed question payload is rejected as a whole, without partial updates.
- Removing all questions, fewer than two choices, or all correct choices is rejected.
- Correct-option indexes cannot point beyond the question's current choice list.
- Empty and whitespace-only text fields cannot be saved.

---

## File Map

- `app/teacher.py`: teacher question endpoints, payload validation, versioning, results, details, and CSV totals.
- `app/attempts.py`: count current questions dynamically and validate submitted choices against the attempt snapshot.
- `static/app.js`: teacher editor controls and dynamic question/choice counts in student, preview, and results views.
- `static/styles.css`: responsive editor fields and compact account header.
- `index.html`: remove brand logo/title and footer label while retaining the account region.
- `README.md`: describe editable question and option counts rather than a fixed set.

## Tasks

### Task 1: Teacher question API and version save

**Files:** Modify `app/teacher.py`.

**Interfaces:**
- Produces `GET /api/teacher/questions` returning `{questions, version, is_open, keys_approved}` for a teacher.
- Produces `POST /api/teacher/questions` accepting `{questions: [...]}` and returning `{ok, version, is_open, keys_approved}`.

- [ ] Add a question normalizer/validator that accepts only question objects with non-empty `prompt`, `text`, `choices`, and `correct`; trim text, require at least two non-empty choices, require one or more unique integer correct indexes in range, and reject an empty test.
- [ ] Add the protected read endpoint and protected save endpoint. Validate the whole payload before opening a transaction.
- [ ] In one transaction, save normalized JSON, set `is_open=0`, set `keys_approved=0`, increment `version`, and write a `questions_updated` audit event. Keep all `attempts.questions` rows untouched.
- [ ] Make teacher preview render the currently saved key for the editor's version, while retaining the existing key confirmation flow for opening the test.

### Task 2: Dynamic attempt and score data

**Files:** Modify `app/attempts.py`, `app/teacher.py`.

**Interfaces:**
- `GET /api/test` reports `total=len(current_questions)`.
- Attempt states continue to report `total=len(attempt_snapshot)`.
- Teacher participant rows and detail responses include the corresponding attempt `total`.

- [ ] Replace the fixed current-test total with the length of the saved question JSON.
- [ ] Validate a submitted choice against the current question in the attempt snapshot, rather than a fixed upper bound of three.
- [ ] Return each historical attempt's own question total in participant and detail data.
- [ ] Calculate average performance as each completed attempt's score divided by its own snapshot length, then average those percentages.
- [ ] Export `Score` and `Maximum` columns; derive both values from each row's score and question snapshot length.

### Task 3: Teacher editor

**Files:** Modify `static/app.js`, `static/styles.css`.

**Interfaces:**
- The dashboard's question action opens an editor backed by `/api/teacher/questions`.
- Successful save returns to the dashboard and states that the test is closed pending key review.

- [ ] Replace the read-only questions screen with editable prompt/text fields, dynamic choice fields, and correct-choice checkboxes.
- [ ] Add controls to add/remove/reorder questions and choices; keep at least two choices visible and identify choices with dynamic numeric labels.
- [ ] Add client-side validation matching the server rules and preserve form values when the save request fails.
- [ ] Add a preview action that renders current editor contents and keys without saving them.
- [ ] On save, submit the complete question set. Prevent duplicate submits and handle validation or network errors in the editor.
- [ ] Add responsive styles for question cards, choice controls, and editor actions on narrow screens.

### Task 4: Dynamic student flow and historical result views

**Files:** Modify `static/app.js`.

- [ ] Use API question totals in login/status copy, student question progress, and completion labels; keep the 20-second timer constant.
- [ ] Render any number of answer options with dynamic numeric labels.
- [ ] Use preview question length for preview completion and timeout advancement.
- [ ] Render teacher participant scores, detail score maxima, answer labels, and question headers from each attempt's own snapshot and total.
- [ ] Remove fixed `/ 20` and `Бали з 20` assumptions from displayed results.

### Task 5: Remove branding and update documentation

**Files:** Modify `index.html`, `static/styles.css`, `README.md`.

- [ ] Remove the brand logo/title link and footer label. Preserve the account container, sign-out action, skip link, page content, and toast region.
- [ ] Remove header/footer layout rules that only apply to the deleted branding; keep the remaining account controls usable on mobile.
- [ ] Update README wording to describe editable question and option counts and the save/review/reopen flow.

## Self-review

- Spec coverage: editor and validation are Task 1/3; version snapshots and historical scores are Task 1/2/4; dynamic options and counts are Task 2/4; branding removal is Task 5; editor error handling is Task 3.
- The API contract is consistent: editor saves a whole `{questions}` payload; the server returns the new version and closed/unapproved state.
- Existing answer rows remain valid because choice indexes and question indexes are stored against each attempt's immutable question snapshot.
- The task order establishes the API and dynamic data contract before the UI consumes it.
- No automated test changes or test commands are included in this plan.
