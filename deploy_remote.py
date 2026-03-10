import paramiko
import time
import os

hostname = '192.168.1.10'
username = 'linaro'
password = 'linaro'

try:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(hostname, port=22, username=username, password=password, timeout=10)
    
    print("SSH 登录成功，正在寻找 gesture-yolo-ha 目录...")
    stdin, stdout, stderr = ssh.exec_command("find / -type d -name 'gesture-yolo-ha' 2>/dev/null")
    paths = stdout.read().decode().strip().split('\n')
    paths = [p for p in paths if p]
    
    if not paths:
        print("未在远程服务器上找到 gesture-yolo-ha 目录。")
    else:
        target_dir = paths[0]
        print(f"找到目录: {target_dir}")
        target_file = f"{target_dir}/app/static/index.html"
        
        # 确认远程的 index.html 是否存在
        stdin, stdout, stderr = ssh.exec_command(f"ls {target_file}")
        out = stdout.read().decode().strip()
        
        if target_file in out or "No such file" not in stderr.read().decode():
            print(f"找到远程文件: {target_file}，正在上传本地文件...")
            sftp = ssh.open_sftp()
            local_file = 'app/static/index.html'
            sftp.put(local_file, target_file)
            sftp.close()
            print("上传完成！")
            
            # 也许需要重启服务？如果没有系统服务我们就只改前端
            print("前端界面更新完毕，请刷新 192.168.1.10 的网页查看。")
        else:
            print(f"远程目录找到了，但是没有找到 {target_file}")
            
    ssh.close()
except Exception as e:
    print(f"发生错误: {e}")
