from remote_utils import open_ssh, read_remote_text


def main() -> None:
    with open_ssh() as (_, sftp, settings):
        content = read_remote_text(sftp, settings.tg_script_path)
        print(content)


if __name__ == "__main__":
    main()
