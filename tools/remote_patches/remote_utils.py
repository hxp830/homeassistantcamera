from __future__ import annotations

import ast
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

import paramiko
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class RemoteSettings:
    host: str
    port: int
    username: str
    password: str
    tg_script_path: str
    tg_tmp_script_path: str
    gesture_project_dir: str


def load_remote_settings() -> RemoteSettings:
    host = os.getenv("REMOTE_HOST", "").strip()
    username = os.getenv("REMOTE_USER", "").strip()
    if not host or not username:
        raise RuntimeError(
            "Missing REMOTE_HOST or REMOTE_USER in .env. "
            "Please configure tools/remote_patches before running these scripts."
        )

    return RemoteSettings(
        host=host,
        port=int(os.getenv("REMOTE_PORT", "22")),
        username=username,
        password=os.getenv("REMOTE_PASSWORD", ""),
        tg_script_path=os.getenv("REMOTE_TG_SCRIPT_PATH", "/home/linaro/canva-dreamlab-cli/tg_persistent.py").strip(),
        tg_tmp_script_path=os.getenv("REMOTE_TG_TMP_PATH", "/tmp/tg_persistent.py").strip(),
        gesture_project_dir=os.getenv("REMOTE_GESTURE_PROJECT_DIR", "").strip(),
    )


@contextmanager
def open_ssh() -> Iterator[tuple[paramiko.SSHClient, paramiko.SFTPClient, RemoteSettings]]:
    settings = load_remote_settings()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        settings.host,
        port=settings.port,
        username=settings.username,
        password=settings.password,
        timeout=15,
    )
    sftp = client.open_sftp()
    try:
        yield client, sftp, settings
    finally:
        sftp.close()
        client.close()


def read_remote_text(sftp: paramiko.SFTPClient, path: str) -> str:
    with sftp.open(path, "r") as handle:
        return handle.read().decode("utf-8")


def write_remote_text(sftp: paramiko.SFTPClient, path: str, content: str) -> None:
    with sftp.open(path, "w") as handle:
        handle.write(content)


def backup_remote_file(sftp: paramiko.SFTPClient, path: str) -> str:
    content = read_remote_text(sftp, path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{path}.bak_{timestamp}"
    write_remote_text(sftp, backup_path, content)
    return backup_path


def ensure_substrings(content: str, expected: list[str]) -> None:
    missing = [item for item in expected if item not in content]
    if missing:
        raise RuntimeError(f"Patched content is missing expected markers: {missing}")


def validate_python_source(content: str, label: str) -> None:
    try:
        ast.parse(content)
    except SyntaxError as exc:
        raise RuntimeError(f"{label} is not valid Python after patch: {exc}") from exc


def apply_regex_patch(content: str, pattern: re.Pattern[str], replacement: str, label: str) -> str:
    patched, count = pattern.subn(replacement, content, count=1)
    if count != 1:
        raise RuntimeError(f"{label}: target block not found; nothing was written.")
    if patched == content:
        raise RuntimeError(f"{label}: patch produced no changes; nothing was written.")
    return patched


def sync_text_to_paths(sftp: paramiko.SFTPClient, content: str, paths: list[str]) -> None:
    for path in paths:
        write_remote_text(sftp, path, content)


def patch_remote_python_file(
    *,
    target_path: str,
    mirror_paths: list[str],
    pattern: re.Pattern[str],
    replacement: str,
    patch_label: str,
    expected_markers: list[str] | None = None,
) -> None:
    with open_ssh() as (_, sftp, _settings):
        original = read_remote_text(sftp, target_path)
        print(f"Read remote file: {target_path}")

        patched = apply_regex_patch(original, pattern, replacement, patch_label)
        if expected_markers:
            ensure_substrings(patched, expected_markers)
        validate_python_source(patched, patch_label)

        backup_path = backup_remote_file(sftp, target_path)
        print(f"Created backup: {backup_path}")

        sync_text_to_paths(sftp, patched, [target_path, *mirror_paths])
        for path in [target_path, *mirror_paths]:
            print(f"Updated {path}")


def remote_path_exists(sftp: paramiko.SFTPClient, path: str) -> bool:
    try:
        sftp.stat(path)
        return True
    except OSError:
        return False


def run_remote_command(client: paramiko.SSHClient, command: str) -> tuple[str, str]:
    stdin, stdout, stderr = client.exec_command(command)
    _ = stdin
    return stdout.read().decode("utf-8"), stderr.read().decode("utf-8")


def resolve_remote_gesture_dir(client: paramiko.SSHClient, settings: RemoteSettings) -> str:
    if settings.gesture_project_dir:
        return settings.gesture_project_dir
    out, _err = run_remote_command(client, "find / -type d -name 'gesture-yolo-ha' 2>/dev/null")
    paths = [line.strip() for line in out.splitlines() if line.strip()]
    if not paths:
        raise RuntimeError("Could not find remote gesture-yolo-ha directory.")
    return paths[0]


def upload_file_with_backup(
    sftp: paramiko.SFTPClient,
    *,
    local_path: Path,
    remote_path: str,
) -> str:
    backup_path = backup_remote_file(sftp, remote_path)
    sftp.put(str(local_path), remote_path)
    return backup_path
