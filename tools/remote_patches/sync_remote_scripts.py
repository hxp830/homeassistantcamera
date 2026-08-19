from remote_utils import backup_remote_file, open_ssh, read_remote_text, sync_text_to_paths


def main() -> None:
    with open_ssh() as (_, sftp, settings):
        content = read_remote_text(sftp, settings.tg_script_path)
        print(f"Read latest remote script: {settings.tg_script_path}")

        backup_path = backup_remote_file(sftp, settings.tg_tmp_script_path)
        print(f"Created backup for mirror path: {backup_path}")

        sync_text_to_paths(sftp, content, [settings.tg_script_path, settings.tg_tmp_script_path])
        print(f"Updated {settings.tg_script_path}")
        print(f"Updated {settings.tg_tmp_script_path}")


if __name__ == "__main__":
    main()
