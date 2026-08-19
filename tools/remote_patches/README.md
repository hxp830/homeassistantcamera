# Remote Patch Tools

These scripts have been moved out of the main app root so the repository stays easier to understand.

## Setup

Add the following values to the project `.env` file:

```env
REMOTE_HOST=
REMOTE_PORT=22
REMOTE_USER=
REMOTE_PASSWORD=
REMOTE_TG_SCRIPT_PATH=/home/linaro/canva-dreamlab-cli/tg_persistent.py
REMOTE_TG_TMP_PATH=/tmp/tg_persistent.py
REMOTE_GESTURE_PROJECT_DIR=
```

## Notes

- All scripts now load SSH settings from `.env`.
- Patch scripts validate the generated remote Python before writing.
- `patch_new_command_v8.py` and the shared patch helpers create a remote backup first.
- `deploy_remote.py` creates a backup of the remote `index.html` before upload.
