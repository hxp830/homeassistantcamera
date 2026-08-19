from pathlib import Path
from posixpath import join as remote_join

from remote_utils import (
    open_ssh,
    remote_path_exists,
    resolve_remote_gesture_dir,
    upload_file_with_backup,
)


def main() -> None:
    with open_ssh() as (client, sftp, settings):
        print("SSH 登录成功，正在寻找 gesture-yolo-ha 目录...")
        target_dir = resolve_remote_gesture_dir(client, settings)
        print(f"找到目录: {target_dir}")

        target_file = remote_join(target_dir, "app/static/index.html")
        if not remote_path_exists(sftp, target_file):
            raise RuntimeError(f"远程目录找到了，但是没有找到 {target_file}")

        print(f"找到远程文件: {target_file}，正在上传本地文件...")
        backup_path = upload_file_with_backup(
            sftp,
            local_path=Path(__file__).resolve().parents[2] / "app/static/index.html",
            remote_path=target_file,
        )
        print(f"已创建备份: {backup_path}")
        print("上传完成！")
        print("前端界面更新完毕，请刷新远程网页查看。")


if __name__ == "__main__":
    main()
