# Project File Layout

This project keeps source code, local runtime data, and launchers separated so the root folder stays readable.

## Root

- `.env`: local private environment values. Keep it at the root because the launcher and config loader read it there.
- `.env.example`: safe environment template.
- `.editorconfig`, `.gitignore`: editor and Git configuration. These should stay at the root.
- `Local_Video_gui.py`: thin GUI launcher.
- `backend_server.py`: thin backend launcher.
- `safe_start_vidnorm.py`, `start_vidnorm.ps1`, `start_vidnorm.bat`, `启动系统.bat`, `启动系统_静默.vbs`: user-facing startup entry points.

## Application Code

- `app/`: main Python application package.
- `app/queen_library/`: queen library domain rules, scraper, service, sorting, and UI.
- `tests/`: automated tests.

## Local Data

- `config/user/`: local UI and feature settings. Files here are ignored by Git.
- `data/`: local SQLite databases. Files here are ignored by Git.
- `runtime_snapshots/`, `task_logs/`, `combo_task_logs/`, `browser_profiles/`: generated runtime state and logs.

## Support Files

- `docs/`: project documentation.
- `scripts/dev/`: developer diagnostics and one-off probes.
- `backups/`: manually created local backups.
