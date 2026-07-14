# Quark QR Login Design

## Goal

Replace manual Cookie copying with a GUI-driven Quark QR login while preserving unattended scheduled backups. The application must continue to support the existing Cookie configuration during migration.

## Scope

- Add a Quark account connection action to the desktop home page.
- Display a QR code and login status in a modal dialog.
- Use the installed `quarkpan` authentication flow to obtain the session Cookie after the user confirms login in the Quark mobile app.
- Encrypt the resulting credential for the current Windows user.
- Reuse the credential for manual and scheduled backups.
- Detect expired credentials and require a new interactive QR login.
- Keep the existing plaintext Cookie configuration as a temporary fallback.

Direct username/password or SMS-code login is excluded. It adds credential handling and anti-abuse challenges without improving unattended backup behavior.

## Architecture

### Authentication service

Create a focused Quark authentication service under `code/app/services/system/`. It owns these operations:

- Start a QR login session and return QR image data plus an opaque session identifier.
- Poll the session until it is pending, confirmed, expired, cancelled, or failed.
- Convert a confirmed session into the Cookie string required by `QuarkClient`.
- Encrypt, load, validate, and clear the saved credential.

The service will wrap the installed library rather than importing private authentication classes from GUI code. Any adaptation required by the library remains behind this service boundary.

### Credential store

Use Windows DPAPI with current-user scope. Store only encrypted bytes and non-secret metadata such as connection time and account display name. The encrypted credential file belongs in the local configuration area but must be excluded from Git and from the `user_data` backup archive.

Scheduled tasks run as the same Windows user and can decrypt the credential. A copied project or archive on another Windows account cannot decrypt it.

### Backup service

Credential resolution order:

1. Load and decrypt the QR-derived credential.
2. Fall back to the existing `cookie` value in `quark_backup.json`.
3. Return a structured `login_required` result when neither credential is usable.

The backup service validates the resolved credential before creating or uploading an archive. It does not start an interactive login from a scheduled task.

## GUI Flow

Add a `登录夸克` action near the existing `上传备份` action.

1. The user opens the login dialog.
2. The dialog requests a QR login session on a worker thread.
3. The QR image is displayed with a concise status label and cancel/retry controls.
4. Polling continues on a worker or timer without blocking the UI.
5. After confirmation, the service encrypts the credential and verifies access by requesting account or root-folder data.
6. The dialog reports success and closes after user acknowledgement.

The dialog must cancel polling when closed. QR expiration offers a retry that creates a new session. It must never log the QR token, Cookie, encrypted payload, or full authentication response.

## Scheduled Backup Behavior

- A valid saved credential keeps the existing five-day task fully unattended.
- An expired credential produces `login_required`, writes a sanitized warning to the Quark backup module log, and performs no upload or retry loop.
- The next desktop startup shows a non-blocking login-required state on the backup controls.
- Manual upload reports the same state and offers the login dialog.
- Successful re-login replaces the old encrypted credential atomically.

## Compatibility And Migration

Existing installations continue to work with `quark_backup.json.cookie`. After a successful QR login, the encrypted credential takes precedence. The GUI may offer to clear the legacy Cookie, but migration does not silently rewrite user configuration.

The QR credential file and legacy backup configuration remain excluded from generated backup ZIP files. No authentication secret is uploaded to Quark Pan.

## Error Handling And Logging

Use structured module logging for session start, state transitions, elapsed time, validation, and cancellation. Sensitive values are always redacted.

Expected user-facing states are:

- Waiting for scan
- Waiting for confirmation
- Login successful
- QR code expired
- Login cancelled
- Network unavailable
- Login required
- Credential validation failed

Network and API errors do not delete a previously valid credential. A credential is replaced only after a newly acquired credential passes validation.

## Tests

- Authentication service tests for QR state mapping, cancellation, timeout, validation, encryption round trips, corrupt storage, and atomic replacement.
- Backup service tests for encrypted credential precedence, legacy Cookie fallback, `login_required`, and secret redaction.
- GUI tests for dialog state transitions, retry, close cancellation, successful connection, and upload-to-login handoff.
- Scheduled-task regression tests proving that no dialog or interactive login is invoked.
- Windows-only integration test for a DPAPI round trip; library/network login remains an explicit manual integration test.

## Acceptance Criteria

- A user can connect Quark Pan by scanning a QR code without opening developer tools or copying a Cookie.
- Manual and scheduled backups use the saved login after the application restarts.
- Expired login state is reported clearly and never causes endless retries.
- Existing Cookie-based configuration remains functional.
- Authentication secrets never appear in Git, backup archives, or logs.
