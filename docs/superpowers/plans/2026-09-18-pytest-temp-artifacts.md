# Pytest Temporary Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Configure every repository pytest run to use one disposable temporary directory and remove existing test-only artifacts and caches.

**Architecture:** Add a repository-root `pytest.ini` so pytest behaves consistently whether invoked from the repository root or `code`. The configuration will point test discovery and imports at `code/tests` and `code`, and set pytest's base temporary directory to `code/.pytest-tmp`. Extend `.gitignore` for the unified directory and disposable caches; clean only known test artifacts after verification.

**Tech Stack:** Python 3.13, pytest 9.1.1, PowerShell 7, Git.

## Global Constraints

- Use `D:\Anaconda3Data\envs_dirs\video_env\python.exe` for Python and pytest commands.
- Preserve existing uncommitted changes in `code/app/gui/main_window.py` and `code/tests/test_gui_task_runner.py`.
- Do not delete `runtime/`, `user_data/`, source files, documentation, or databases.
- Use `code/.pytest-tmp/` for pytest base temporary data.

### Task 1: Add the pytest configuration regression test

**Files:**
- Create: `code/tests/test_pytest_configuration.py`

**Interfaces:**
- Consumes: the repository-root `pytest.ini` through pytest's `pytestconfig` fixture.
- Produces: an assertion that `--basetemp=code/.pytest-tmp` is present in pytest's effective addopts.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path


def test_pytest_uses_the_repository_test_temp_directory(pytestconfig):
    project_root = Path(__file__).parents[2]
    configured_options = pytestconfig.getini("addopts")

    assert "--basetemp=code/.pytest-tmp" in configured_options
    assert (project_root / "pytest.ini").is_file()
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run from `code`:

```powershell
& "D:\Anaconda3Data\envs_dirs\video_env\python.exe" -m pytest tests/test_pytest_configuration.py -q
```

Expected: FAIL because the repository has no `pytest.ini` and pytest's effective `addopts` does not contain the unified `--basetemp` option.

### Task 2: Configure and ignore disposable test artifacts

**Files:**
- Create: `pytest.ini`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: pytest's `addopts`, `testpaths`, and `pythonpath` configuration options.
- Produces: repository-wide pytest discovery and a base temporary directory at `code/.pytest-tmp`.

- [ ] **Step 1: Add the minimal pytest configuration**

```ini
[pytest]
testpaths = code/tests
pythonpath = code
addopts = --basetemp=code/.pytest-tmp
```

- [ ] **Step 2: Add explicit ignore rules**

Append these rules to `.gitignore`:

```gitignore
# Unified pytest temporary artifacts and local lint cache
/code/.pytest-tmp/
/code/.pytest_cache/
/code/.ruff_cache/
```

- [ ] **Step 3: Run the focused test to verify it passes**

Run from `code`:

```powershell
& "D:\Anaconda3Data\envs_dirs\video_env\python.exe" -m pytest tests/test_pytest_configuration.py -q
```

Expected: PASS.

### Task 3: Remove existing test-only artifacts

**Files:**
- Delete: existing `code/pytest-temp-*` directories
- Delete: existing `code/pytest-*.out.log` and `code/pytest-*.err.log` files
- Delete: `code/.pytest-tmp/`, `code/.pytest_cache/`, repository-root `.pytest_cache/`, and `code/.ruff_cache/` when present

**Interfaces:**
- Consumes: the artifact paths identified during repository inventory.
- Produces: no test-generated directories or logs outside `code/.pytest-tmp/`.

- [ ] **Step 1: Confirm cleanup targets and preserve protected data**

Run:

```powershell
$targets = @(
    (Join-Path (Get-Location) 'code'),
    (Join-Path (Get-Location) 'runtime'),
    (Join-Path (Get-Location) 'user_data')
)
$targets | ForEach-Object { Get-Item -LiteralPath $_ | Select-Object FullName,Mode }
```

Expected: `code` exists, and `runtime`/`user_data` are listed as protected directories; only the explicitly named test artifact children are eligible for removal.

- [ ] **Step 2: Delete only the confirmed disposable paths**

Run from the repository root:

```powershell
Get-ChildItem -LiteralPath 'code' -Directory -Filter 'pytest-temp-*' | Remove-Item -Recurse -Force
Get-ChildItem -LiteralPath 'code' -File -Filter 'pytest-*.out.log' | Remove-Item -Force
Get-ChildItem -LiteralPath 'code' -File -Filter 'pytest-*.err.log' | Remove-Item -Force
@('code/.pytest-tmp', 'code/.pytest_cache', '.pytest_cache', 'code/.ruff_cache') |
    ForEach-Object { if (Test-Path -LiteralPath $_) { Remove-Item -LiteralPath $_ -Recurse -Force } }
```

Expected: only test temporary directories, pytest/lint caches, and pytest log files are removed.

- [ ] **Step 3: Verify configuration and cleanup result**

Run from the repository root:

```powershell
& "D:\Anaconda3Data\envs_dirs\video_env\python.exe" -m pytest code/tests/test_pytest_configuration.py -q
git status --short
```

Expected: the focused test passes; no `code/pytest-temp-*` or `code/pytest-*.log` paths remain; existing user changes remain visible in `git status`.

- [ ] **Step 4: Commit the implementation**

```powershell
git add pytest.ini .gitignore code/tests/test_pytest_configuration.py
git commit -m "test: centralize pytest temporary artifacts"
```

## Verification Summary

Run the focused configuration test, then run the complete Python test suite from `code`:

```powershell
& "D:\Anaconda3Data\envs_dirs\video_env\python.exe" -m pytest tests -q
```

Expected: the suite completes with exit code 0, and all pytest temporary data created by the run is below `code/.pytest-tmp/`.
