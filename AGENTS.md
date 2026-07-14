# Shell requirements

- The shell is PowerShell 7 (`pwsh`) on Windows.
- Never use Bash, Git Bash, CMD, or WSL syntax.
- Never use Bash heredoc syntax such as `python - <<'PY'`.
- Never use `rm`, `cp`, `mv`, `cat`, `grep`, `sed`, `export`, or `source`.
- Use native PowerShell commands.
- Quote every path that may contain spaces.
- For Python paths, use `pathlib.Path`.
- Do not manually concatenate paths using `/` or `\`.
- Prefer the Python interpreter configured for this project, especially
  `APP_PYTHON_EXE` in `.env` when it exists. This may point to an Anaconda or
  Conda environment.
- Use `.venv\Scripts\python.exe` only when the project is intentionally using a
  local `.venv`.
- Do not silently fall back to an unrelated global Python interpreter. If neither
  `.env` nor `.venv` identifies the intended interpreter, ask before running
  dependency or test commands.

# Environment setup

- Use the configured Anaconda/Conda interpreter when the project is set up that
  way. Create a local `.venv` only when the project has no configured Python
  interpreter or the user explicitly requests a `.venv`.
- Use `pwsh` for project scripts and automation once PowerShell 7 is installed.
- Verify the active environment before dependency or test commands by running
  the selected interpreter with `-c "import sys; print(sys.executable)"`.
