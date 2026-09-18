# Pytest Temporary Artifacts Design

## Goal

Keep pytest temporary directories and test-run logs in one disposable location so the project can be cleaned predictably without touching runtime or user data.

## Design

- Use `code/.pytest-tmp/` as the single pytest base temporary directory.
- Configure pytest through `code/pytest.ini` so normal test runs use that directory automatically.
- Resolve the base temporary directory from `code/conftest.py` so the same absolute path is used from the repository root and from `code`.
- Keep pytest's cache inside the unified directory as `code/.pytest-tmp/.pytest_cache/`.
- Store manually captured test stdout/stderr logs under `code/.pytest-tmp/logs/` when test scripts need persistent logs.
- Do not redirect application runtime files from `runtime/tmp`; those files can be needed by the running application and are outside test cleanup.
- Ignore the unified directory and existing cache locations in Git.

## Cleanup Scope

Remove existing `code/pytest-temp-*` directories, `code/pytest-*.out.log`, `code/pytest-*.err.log`, `code/.pytest-tmp/`, the repository pytest cache, the inaccessible legacy `code/.pytest_cache/` when permissions allow, and `code/.ruff_cache/` contents when they are not in use. Do not remove `runtime/`, `user_data/`, source files, documentation, or databases.

## Verification

- A focused test proves pytest configuration resolves the base temporary directory below `code/.pytest-tmp/`.
- The relevant pytest test passes with the new configuration.
- Git status confirms only intentional configuration, test, ignore-rule, and design/plan files changed; pre-existing user edits remain intact.
