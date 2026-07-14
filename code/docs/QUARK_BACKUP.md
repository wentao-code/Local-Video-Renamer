# Quark Backup

The backup service creates a Zip64 archive of `user_data/` every five days. It uploads the new archive to a dedicated Quark Pan folder, then deletes only older archives whose names start with `local_video_renamer_user_data_`. Local data is never deleted.

## Configure

1. Edit `user_data/config/quark_backup.json`. It is created locally with the same defaults as [quark_backup.json.example](quark_backup.json.example).
2. Set `enabled` to `true` and paste the Cookie obtained from a `drive.quark.cn` browser request into `cookie`.
3. Keep `remote_parent_folder_id` as `0` to create the dedicated backup folder in your Quark Pan root, or set it to a folder ID you control.

The configuration file is excluded from both Git and the backup archive. Do not paste the Cookie into source code, logs, or chat.

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

## Restore

1. Download the newest `local_video_renamer_user_data_*.zip` from the dedicated Quark Pan folder.
2. Close the application.
3. Rename the current `user_data/` directory as a local fallback.
4. Extract the archive beside the project so it restores the `user_data/` directory.
5. Start the application and verify the database, settings, and browser profiles.

The archive contains sensitive browser profiles and local configuration. Protect the Quark Pan account and downloaded archive accordingly.
