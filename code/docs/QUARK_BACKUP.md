# Quark Backup

The backup service creates a Zip64 archive of `user_data/` every five days. It uploads the new archive to a dedicated Quark Pan folder, then deletes only older archives whose names start with `local_video_renamer_user_data_`. Local data is never deleted.

## Connect With QR Login

1. Start the desktop application.
2. Click `登录夸克` on the third action row.
3. Scan the displayed QR code with the Quark mobile app and confirm the login.

The resulting credential is encrypted with Windows DPAPI for the current Windows user and saved in `user_data/config/quark_credentials.dat`. It is excluded from Git and from every generated backup archive. The credential cannot be decrypted after copying it to another Windows account.

If the credential expires, manual upload opens the QR login dialog and resumes one upload after a successful login. The scheduled task never opens a window or retries interactively; it records `login_required` and exits with code `2` until the user logs in from the desktop application.

## Configure

1. Edit `user_data/config/quark_backup.json`. It is created locally with the same defaults as [quark_backup.json.example](quark_backup.json.example).
2. Set `enabled` to `true`. The `cookie` field can remain empty after QR login.
3. Keep `remote_parent_folder_id` as `0` to create the dedicated backup folder in your Quark Pan root, or set it to a folder ID you control.

The encrypted QR credential takes precedence over the legacy `cookie` field. Existing Cookie configurations remain supported as a fallback. The configuration, state, and encrypted credential files are excluded from both Git and the backup archive. Do not paste a Cookie into source code, logs, or chat.

## Schedule

Run the following from the `code/` folder once to register a Windows task at 03:00 every five days:

```powershell
.\scripts\install_quark_backup_task.ps1
```

Use a different time when needed:

```powershell
.\scripts\install_quark_backup_task.ps1 -At '02:30'
```

The registered Windows task is the only automatic trigger, so backups occur at the fixed configured time even when the desktop application is closed.

## Manual Upload

The main application's third action row contains `登录夸克` and `上传备份` buttons. Manual upload immediately starts one backup and ignores the five-day interval. The upload runs in the task queue without blocking the interface. It uses the same dedicated remote folder and retention rule as the scheduled task.

Only one backup can run at a time. If the scheduled task is already uploading, the manual action reports that a backup is in progress and does not retry automatically.

## Restore

1. Download the newest `local_video_renamer_user_data_*.zip` from the dedicated Quark Pan folder.
2. Close the application.
3. Rename the current `user_data/` directory as a local fallback.
4. Extract the archive beside the project so it restores the `user_data/` directory.
5. Start the application and verify the database, settings, and browser profiles.

The archive contains sensitive browser profiles and local configuration. Protect the Quark Pan account and downloaded archive accordingly.
