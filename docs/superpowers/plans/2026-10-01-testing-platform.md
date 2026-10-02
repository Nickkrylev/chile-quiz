# Testing Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Создать и разместить учебный тест с одной попыткой, серверным таймером и кабинетом преподавателя, доступным через временный локальный пароль.

**Architecture:** Flask-приложение с SQLite, отдельными модулями авторизации, попыток и преподавателя. Статический интерфейс обращается к API того же origin; Nginx обслуживает приложение через Gunicorn на localhost.

**Tech Stack:** Python 3.10+, Flask, Gunicorn, Authlib, Werkzeug scrypt, SQLite, pytest, HTML/CSS/JavaScript.

**Spec:** `docs/superpowers/specs/2026-10-01-testing-platform-design.md`

## Global Constraints

- 20 вопросов на испанском, один вариант ответа, 20 секунд на каждый вопрос.
- Уникальная попытка на пару «пользователь, тест»; версия вопросов неизменяема.
- Студенческий домен: `student.karazin.ua`; Google identity определяется issuer + sub.
- Временный преподаватель: `admin@student.karazin.ua`, локальная идентичность отдельно от Google.
- Только scrypt-хеш пароля; случайный пароль не менее 20 символов; никаких секретов в Git.
- После пяти неудачных проверок за 15 минут блокируется дальнейший подбор с IP до конца окна.
- Сессии серверные, cookies HttpOnly/Secure/SameSite=Lax, изменения защищены от CSRF.
- Приложение не использует изображения и не заявляет официальный статус университета.
- Тест закрыт до проверки ключей №7, №10, №16 преподавателем.
- Ежедневная SQLite backup, хранение 14 дней; существующие сервисы VPS сохраняются.
- Развёртывание требует выбранного адреса; предложен `https://gsse.work/testing/`.

## Review Focus

1. Обрыв связи после принятого ответа: повторный POST не пропускает следующий вопрос — задача 2.
2. Два браузера одновременно начинают попытку: остаётся одна строка в базе — задача 2.
3. Одинаковый email локального и Google-пользователя не повышает чужую роль — задача 1.
4. Префикс `/testing/`: cookies, static URLs и OAuth callback не уходят в соседний сайт — задача 5.
5. CSV с именем `=1+1` или переносом строки безопасно открывается в таблице — задача 4.

## Структура файлов

- `app/__init__.py`, `app/config.py`: фабрика приложения и настройки окружения.
- `app/db.py`, `app/schema.sql`: транзакции, схема, миграция и backup.
- `app/auth.py`: серверные сессии, CSRF, локальный вход и роли.
- `app/google_auth.py`: Google OIDC и проверка учебного домена.
- `app/attempts.py`: дедлайны, ответы, возобновление, оценивание.
- `app/teacher.py`: обзор, карточка, фильтры, CSV, доступность теста.
- `app/cli.py`: начальная настройка и пароль через CLI.
- `data/test-uo6.json`: вопросы и исходные ключи, только для сервера.
- `index.html`, `static/styles.css`, `static/app.js`: интерфейс участника и преподавателя.
- `tests/conftest.py`, `tests/test_auth.py`, `tests/test_attempts.py`,
  `tests/test_google_auth.py`, `tests/test_teacher.py`, `tests/test_deployment.py`.
- `requirements.txt`, `.gitignore`, `.env.example`, `README.md`.
- `deploy/testing.service`, `deploy/nginx-testing.conf`,
  `deploy/testing-backup.service`, `deploy/testing-backup.timer`.

### Task 1: База и временный кабинет с защищённым входом

**Files:** `app/__init__.py`, `app/config.py`, `app/db.py`, `app/schema.sql`, `app/auth.py`, `app/cli.py`, `requirements.txt`, `.gitignore`, `.env.example`, `tests/conftest.py`, `tests/test_auth.py`.

**Interfaces:** `create_app(config: dict | None = None) -> Flask`; `get_db() -> sqlite3.Connection`; `require_user(role: str | None = None)`; `create_local_teacher(email: str, password: str) -> int`. API: GET `api/session` returns `{user, csrf, google_enabled, local_teacher_enabled}`; POST `api/auth/local`, `api/auth/logout`, `api/auth/password`.

- [ ] Написать тесты: успешный вход даёт teacher; неверный пароль возвращает 401; попытка 6 после пяти отказов — 429; через 900 секунд ограничение истекает. Проверить CSRF, отзыв старых сессий при смене пароля и отказ при отключённой настройке. `assert password not in db_hash`; локальный и Google sub с одинаковым email принадлежат разным пользователям.
- [ ] Запустить `python -m pytest tests/test_auth.py -q`; зафиксировать падение из-за отсутствующего приложения.
- [ ] Реализовать фабрику, транзакционную SQLite, хранилище сессий, scrypt, CSRF и ограничитель входа в базе. CLI создаёт пароль через `secrets.token_urlsafe(24)` и пишет владельцу в файл 0600 вне Git без вывода в журналы. Версии зависимостей выбрать совместимыми с Python 3.10 и закрепить.
- [ ] Запустить тесты авторизации; ожидаются все PASS.
- [ ] Закоммитить задачу: `feat: add database and temporary teacher authentication`.

### Task 2: Импорт вопросов и серверная попытка

**Files:** `data/test-uo6.json`, `app/attempts.py`, `app/schema.sql`, `tests/test_attempts.py`.

**Interfaces:** `start_attempt(user_id: int, test_id: int, now: float) -> dict`; `attempt_state(user_id: int, attempt_id: int, now: float) -> dict`; `submit_answer(user_id: int, attempt_id: int, question_index: int, choice: int, now: float) -> dict`. State contains `{id, status, question_index, question, choices, deadline, server_time, score}`; score is returned only when completed. API: GET `api/test`, POST `api/attempts`, GET `api/attempts/current`, POST `api/attempts/<id>/answers`.

- [ ] Написать тесты: старт в t=100 даёт deadline=120; ответ в t=119 принимается; в t=120 отклоняется; в t=161 текущий индекс равен 3. Проверить одну запись при параллельном старте, идентичный результат повторной отправки, отказ чужому пользователю, возобновление после пересоздания приложения, завершение после 400 секунд бездействия и отсутствие ключей в API.
- [ ] Запустить `python -m pytest tests/test_attempts.py -q`; ожидается FAIL до реализации.
- [ ] Извлечь 20 вопросов из Word, сохранить исходные ключи и отдельные предложенные исправления №7/10/16. Реализовать атомарные переходы через `BEGIN IMMEDIATE`, UNIQUE(test_id,user_id), UNIQUE(attempt_id,question_index). Хранить снимок версии теста; для просроченных вопросов считать следующий дедлайн от предыдущего.
- [ ] Запустить тесты попыток и авторизации; ожидаются PASS.
- [ ] Закоммитить задачу: `feat: implement timed single-attempt testing`.

### Task 3: Google-вход студентов

**Files:** `app/google_auth.py`, `app/config.py`, `tests/test_google_auth.py`, `.env.example`.

**Interfaces:** GET `auth/google`, GET `auth/google/callback`; `validated_identity(claims: dict) -> dict` produces `{issuer, sub, email, name, role}` after OIDC validation. Uses session and role interfaces from Task 1.

- [ ] Написать тесты с имитацией провайдера: разрешённый домен проходит; неверные issuer/audience/signature/expiry/state/nonce, неподтверждённый email и неверный hd не проходят. При отсутствии OAuth конфигурации нет обхода входа. Совпадение email с локальным admin не даёт teacher.
- [ ] Запустить `python -m pytest tests/test_google_auth.py -q`; ожидается FAIL.
- [ ] Подключить Authlib с Google discovery, scope `openid email profile`, серверной проверкой claims и конфигурируемым hd. Список Google-преподавателей настраивать отдельно от локального логина; не назначать туда временный admin автоматически.
- [ ] Запустить тесты Google и локального входа; ожидаются PASS. Реальный вход отдельно проверяется после получения OAuth credentials.
- [ ] Закоммитить задачу: `feat: add restricted Google student sign-in`.

### Task 4: API преподавателя и проверка ключей

**Files:** `app/teacher.py`, `tests/test_teacher.py`, `app/schema.sql`.

**Interfaces:** GET `api/teacher/overview`, GET `api/teacher/attempts?search=&status=`, GET `api/teacher/attempts/<id>`, GET `api/teacher/export.csv`, POST `api/teacher/test/settings`. Последний принимает `{is_open, approve_suggested_keys}`; открытие возможно только после решения по спорным ключам и настроенного студенческого входа. Изменение ключей создаёт новую версию для будущих попыток.

- [ ] Написать тесты: student получает 403; admin видит сохранённые ответы и корректные агрегаты; истёкшая попытка учитывается завершённой. Проверить CSV с `=1+1`, запятой, кавычкой, переносом строки; закрытый тест не принимает новый старт, но принимает ответ начатой попытки; версии старых попыток не меняются.
- [ ] Запустить `python -m pytest tests/test_teacher.py -q`; ожидается FAIL.
- [ ] Реализовать SQL-параметры, серверную проверку роли, пагинацию по 50 строк, CSV escaping и защиту формул, журнал изменения доступности теста. Предложенные ключи: №7 b/c, №10 d, №16 b; выбор преподавателя отображать явно.
- [ ] Запустить все серверные тесты; ожидаются PASS.
- [ ] Закоммитить задачу: `feat: add teacher results and test controls`.

### Task 5: Строгий адаптивный интерфейс

**Files:** `index.html`, `static/styles.css`, `static/app.js`, `tests/test_deployment.py`.

**Interfaces:** Использует API задач 1–4, все URL относительны base path приложения. Экраны: вход, правила/ФИО, вопрос, результат, кабинет, карточка попытки, смена локального пароля. Пароль и Google tokens не сохраняются в localStorage.

- [ ] Написать интеграционные тесты префикса `/testing/`: HTML/static доступны, cookie path и callback соответствуют префиксу, соседние маршруты не перехватываются.
- [ ] Запустить `python -m pytest tests/test_deployment.py -q`; ожидается FAIL до маршрутизации интерфейса.
- [ ] Реализовать светлую типографическую страницу, явные подписи полей, состояния загрузки/ошибки, доступную клавиатурную навигацию. Таймер рассчитывать по server_time/deadline с монотонным браузерным временем; при возвращении во вкладку перечитывать состояние. Не показывать «сохранено» до подтверждения сервера; при неопределённом результате POST перечитать попытку.
- [ ] Проверить браузером ширины 390 и 1440 px: тестовый вход, кабинет, фильтры, смену пароля, тестовый сценарий через изолированную тестовую базу. Проверить потерю связи, двойное нажатие и обновление страницы. Прогнать все серверные тесты; ожидаются PASS.
- [ ] Закоммитить задачу: `feat: build formal testing and teacher interface`.

### Task 6: Развёртывание и проверка на VPS

**Files:** `deploy/testing.service`, `deploy/nginx-testing.conf`, `deploy/testing-backup.service`, `deploy/testing-backup.timer`, `README.md`, `app/cli.py`, `tests/test_deployment.py`.

**Interfaces:** CLI `init-db`, `create-teacher --credentials-file PATH`, `backup --destination PATH`; сервис запускается отдельным пользователем на свободном localhost-порту; `/api/health` раскрывает только статус готовности базы, без настроек и секретов.

- [ ] Написать тест backup/restore: восстановленная копия сохраняет пользователей, хеш и попытки; учётная запись работает после перезапуска процесса, cookie flags проверяются. Запустить и подтвердить FAIL до backup CLI.
- [ ] Реализовать deploy-конфигурации, SQLite backup и очистку копий старше 14 дней, `.env.example` без секретов, инструкции Google callback и отключения временного входа.
- [ ] Прогнать `python -m pytest -q`, `python -m compileall -q app`; ожидаются PASS и код 0. Проверить diff на секреты и несвязанные изменения.
- [ ] После выбора публичного адреса проверить свободный порт VPS, сделать копию изменяемой конфигурации Nginx, установить сервис и зависимости в отдельное окружение. Создать временного преподавателя, сохранить пароль в локальном файле 0600 через защищённый SSH-канал. Перед reload выполнить `nginx -t`; при ошибке восстановить конфигурацию.
- [ ] Проверить HTTPS, действующие сайты, вход временного преподавателя, кабинет, перезапуск сервиса и запуск backup. Не заявлять Google-вход работающим без реального успешного входа учебного аккаунта.
- [ ] Закоммитить deploy/README и передать URL, логин, ссылку на локальный файл пароля и точный статус OAuth.

## Предлагаемый порядок исполнения

Выполнять в текущей сессии последовательно (Native): задачи тесно связаны
схемой базы и авторизацией. До исполнения пользователь проверяет этот план.
Недостающие OAuth credentials блокируют только реальный Google-вход;
временный кабинет можно реализовать и проверить независимо.


## Виконання

Реалізацію та розгортання завершено. Підсумок перевірок і зовнішні умови
активації Google наведено в `docs/implementation-status.md`.
