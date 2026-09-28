# Feishu lifecycle reporting

The desktop GUI reports application startup after its window and control
adapter are initialized, and reports a normal stop only when the existing GUI
close path accepts shutdown. Task reports remain separate from these lifecycle
notifications.

Use `code/.env.example` as the template for the ignored local file
`user_data/config/.env`, then set `FEISHU_CONTROL_TOKEN` to the same token as
the controller. The app reads settings from that user-data configuration
file. `FEISHU_CONTROLLER_REPORT_URL` defaults to `http://127.0.0.1:8760`;
custom controller URLs must also be present in the process environment.
Install `feishu_plugin_sdk` into the Python environment used to launch Local
Video Renamer.

Manual GUI starts are reported as `manual`; starts through controller command
`304` are reported as `feishu`. Normal GUI closes and controller command `305`
report a stopped event. A crash or forced process termination cannot reliably
report a normal stop and is instead visible as an offline system in controller
status.
