# Quark QR Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let desktop users connect Quark Pan by scanning a QR code, securely reuse that login for manual and scheduled backups, and retain legacy Cookie compatibility.

**Architecture:** A new system service wraps QuarkPan's QR API adapter and a current-user DPAPI credential store. The backup service resolves encrypted credentials before the legacy configuration Cookie, while a dedicated PyQt dialog runs the blocking QR flow on a worker thread and hands successful login back to the main window.

**Tech Stack:** Python 3.13, PyQt5, `quarkpan`/`quark_client`, `qrcode`, Windows CryptProtectData/CryptUnprotectData through `ctypes`, `unittest`/`pytest`.

## Global Constraints

- Never store or log a plaintext Cookie, QR token, service ticket, or complete authentication response.
- The scheduled task must never display an interactive login UI.
- The encrypted credential must be excluded from Git and from the generated user-data backup archive.
- Existing `quark_backup.json.cookie` configuration remains a fallback.
- Failed replacement login must not destroy the previous saved credential.

---

### Task 1: DPAPI Credential Store And QR Authentication Service

**Files:**
- Modify: `code/app/core/project_paths.py`
- Create: `code/app/services/system/quark_auth_service.py`
- Create: `code/tests/test_quark_auth_service.py`

**Interfaces:**
- Produces: `QuarkCredentialStore.save_cookie(cookie: str)`, `load_cookie() -> str`, `clear()`.
- Produces: `QuarkAuthService.login(cancel_event, qr_callback, status_callback) -> dict` with statuses `connected`, `expired`, or `cancelled`.
- Produces: `QuarkAuthService.has_saved_credential() -> bool` and `validate_saved_credential() -> bool`.

- [ ] **Step 1: Write failing credential-store tests**

Test injected reversible protect/unprotect callables, atomic replacement, corrupt payload handling, and clearing. Assert the persisted bytes never contain the source Cookie.

- [ ] **Step 2: Run the service test file and verify import failure**

Run: `& "D:\Anaconda3Data\envs_dirs\video_env\python.exe" -m pytest "tests\test_quark_auth_service.py" -q`

Expected: FAIL because `app.services.system.quark_auth_service` does not exist.

- [ ] **Step 3: Implement current-user DPAPI storage**

Add `QUARK_CREDENTIAL_FILE = USER_CONFIG_DIR / 'quark_credentials.dat'`. Implement Windows DPAPI through `ctypes.windll.crypt32`, dependency-injected protectors for tests, a versioned encrypted payload, temporary-file replacement, and sanitized exceptions.

- [ ] **Step 4: Write failing QR flow tests**

Use a fake adapter that returns QR bytes, pending states, success with a Cookie, expiration, and cancellation. Assert callbacks contain only public state labels and QR image bytes.

- [ ] **Step 5: Implement the QuarkPan adapter and login loop**

Wrap `quark_client.auth.api_login.APILogin` in one private adapter. Generate PNG bytes from the QR URL with `qrcode`, poll at a configurable interval, exchange the service ticket through the adapter, validate with `QuarkClient`, and save only after validation succeeds.

- [ ] **Step 6: Run authentication tests**

Run: `& "D:\Anaconda3Data\envs_dirs\video_env\python.exe" -m pytest "tests\test_quark_auth_service.py" -q`

Expected: PASS.

### Task 2: Backup Credential Resolution

**Files:**
- Modify: `code/app/services/system/quark_backup_service.py`
- Modify: `code/tests/test_quark_backup_service.py`

**Interfaces:**
- Consumes: `QuarkCredentialStore.load_cookie() -> str`.
- Produces: backup result `{status: 'login_required', error: str}` when no usable credential exists.

- [ ] **Step 1: Write failing backup resolution tests**

Assert encrypted credential precedence, legacy Cookie fallback, missing credential `login_required`, invalid client login `login_required`, and exclusion of the credential/config/state files from the ZIP.

- [ ] **Step 2: Run focused tests and verify failures**

Run: `& "D:\Anaconda3Data\envs_dirs\video_env\python.exe" -m pytest "tests\test_quark_backup_service.py" -q`

Expected: FAIL on the new credential-resolution assertions.

- [ ] **Step 3: Implement credential resolution before archive creation**

Inject a credential store, resolve encrypted then legacy credentials, validate the client before creating the archive, return `login_required` for missing/expired authentication, and preserve existing lock/upload/retention behavior.

- [ ] **Step 4: Run backup tests**

Run: `& "D:\Anaconda3Data\envs_dirs\video_env\python.exe" -m pytest "tests\test_quark_backup_service.py" -q`

Expected: PASS.

### Task 3: QR Login Dialog

**Files:**
- Create: `code/app/gui/quark_login_dialog.py`
- Create: `code/tests/test_quark_login_dialog.py`

**Interfaces:**
- Consumes: `QuarkAuthService.login(...) -> dict`.
- Produces: `QuarkLoginDialog.exec_()` returning `QDialog.Accepted` only after a validated credential is saved.

- [ ] **Step 1: Write failing dialog tests**

Patch the worker execution to drive QR-ready, waiting, success, expiration, retry, and close-cancellation states. Assert a QR pixmap is rendered, controls are stable, and success accepts the dialog.

- [ ] **Step 2: Run dialog tests and verify import failure**

Run: `& "D:\Anaconda3Data\envs_dirs\video_env\python.exe" -m pytest "tests\test_quark_login_dialog.py" -q`

Expected: FAIL because the dialog does not exist.

- [ ] **Step 3: Implement dialog and worker lifecycle**

Create a modal dialog with a fixed QR viewport, status label, retry button, and cancel button. Run login in `QThread`, emit PNG bytes and state changes through signals, cancel via `threading.Event`, and cleanly stop thread references on every terminal state.

- [ ] **Step 4: Run dialog tests**

Run: `& "D:\Anaconda3Data\envs_dirs\video_env\python.exe" -m pytest "tests\test_quark_login_dialog.py" -q`

Expected: PASS.

### Task 4: Main Window Integration And Recovery Flow

**Files:**
- Modify: `code/app/gui/main_window.py`
- Modify: `code/tests/test_main_window_startup.py`
- Modify: `code/docs/QUARK_BACKUP.md`

**Interfaces:**
- Consumes: `QuarkLoginDialog` and backup `login_required` result.
- Produces: home-page `登录夸克` action and upload-to-login-to-upload continuation.

- [ ] **Step 1: Write failing main-window tests**

Assert the login action opens the dialog, a successful dialog can resume manual upload, and `_run_manual_quark_backup` returns `login_required` without raising.

- [ ] **Step 2: Run focused startup tests and verify failures**

Run: `& "D:\Anaconda3Data\envs_dirs\video_env\python.exe" -m unittest discover -s "tests" -p "test_main_window_startup.py"`

Expected: FAIL on missing login action and result handling.

- [ ] **Step 3: Add the home-page login action and handoff**

Place `登录夸克` before `上传备份` on the third action row. Open the QR dialog directly for manual login; when upload reports `login_required`, open it and queue one upload after successful authentication. Do not automatically retry any failed upload.

- [ ] **Step 4: Update operator documentation**

Document QR login, DPAPI current-user scope, legacy fallback, expiry recovery, and the fact that scheduled tasks only report `login_required`.

- [ ] **Step 5: Run all Quark and main-window tests**

Run: `& "D:\Anaconda3Data\envs_dirs\video_env\python.exe" -m pytest "tests\test_quark_auth_service.py" "tests\test_quark_backup_service.py" "tests\test_quark_login_dialog.py" -q`

Run: `& "D:\Anaconda3Data\envs_dirs\video_env\python.exe" -m unittest discover -s "tests" -p "test_main_window_startup.py"`

Expected: all tests PASS.

### Task 5: Final Verification

**Files:**
- Verify all modified files.

**Interfaces:**
- Consumes: completed Tasks 1-4.
- Produces: verified implementation with no formatting or syntax errors.

- [ ] **Step 1: Compile modified Python files**

Run: `& "D:\Anaconda3Data\envs_dirs\video_env\python.exe" -m py_compile "code\app\core\project_paths.py" "code\app\services\system\quark_auth_service.py" "code\app\services\system\quark_backup_service.py" "code\app\gui\quark_login_dialog.py" "code\app\gui\main_window.py"`

Expected: exit code 0.

- [ ] **Step 2: Run the complete related regression set**

Run all Quark, main-window startup, and project-path tests.

Expected: all tests PASS.

- [ ] **Step 3: Inspect patch integrity**

Run: `git diff --check`

Expected: exit code 0 with no whitespace errors.
