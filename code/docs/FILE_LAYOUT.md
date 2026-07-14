# Project File Layout

The outer folder contains four visible domains. Git metadata remains hidden at the outer level so one repository can version both desktop code and the independent mobile app.

## 1. Desktop Code

- `code/app/`: Python application package.
- `code/tests/`: automated tests.
- `code/assets/`, `code/docs/`, `code/scripts/`: versioned supporting content.
- `code/.env.example`: safe configuration template.
- `code/Local_Video_gui.py`, `code/backend_server.py`, `code/safe_start_vidnorm.py`, and startup scripts: application entry points.

## 2. Mobile App

`mobile_app/` is an independent Flutter project, but remains in the same Git repository.

## 3. Persistent User Data

`user_data/` is local-only and must be copied when moving the application to another machine.

- `user_data/config/`: `.env`, UI settings, and query history.
- `user_data/databases/`: SQLite databases.
- `user_data/browser_profiles/`: browser profiles, cookies, and login state.
- `user_data/backups/`: user-created database backups.
- `user_data/snapshots/`: refresh snapshots and cached crawler results.

## 4. Disposable Runtime Data

`runtime/` is local-only. It is recreated automatically when absent and must not be committed.

- `runtime/logs/`: rotating application, error, module, and HTTP access logs.
- `runtime/task_logs/`, `runtime/combo_task_logs/`: task execution traces.
- `runtime/locks/`: single-instance lock files.
- `runtime/tmp/`: temporary files.

On startup, the application migrates legacy local folders into these two local-only directories. Existing destination files are never overwritten; conflicting legacy runtime artifacts are retained with a `.legacy` suffix.
