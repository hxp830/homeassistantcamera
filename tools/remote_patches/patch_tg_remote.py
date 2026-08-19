from remote_utils import backup_remote_file, open_ssh, read_remote_text, validate_python_source, write_remote_text


def main() -> None:
    with open_ssh() as (_, sftp, settings):
        content = read_remote_text(sftp, settings.tg_script_path)

        target_parse = """CHAT_ID  = args.chat
MSG_TEXT = args.msg"""
        replacement_parse = """CHAT_ID  = args.chat

# 检查传入的是否是文件路径
msg_path = os.path.expanduser(args.msg)
if os.path.isfile(msg_path):
    print(f"Reading message from file: {msg_path}")
    with open(msg_path, 'r', encoding='utf-8') as mf:
        MSG_TEXT = mf.read()
else:
    MSG_TEXT = args.msg
"""

        target_input = """        # ===== 第2步：发送正式消息 =====
        log(f'\\n第2步：输入消息: {MSG_TEXT}')
        set_status('typing')
        await page.evaluate(f\"\"\"
    () => {{
        const el = document.querySelector('div[contenteditable="true"].input-message-input') ||
                   document.querySelector('div[contenteditable="true"]');
        if (el) {{
            el.focus();
            document.execCommand('insertText', false, {repr(MSG_TEXT)});
        }}
    }}
\"\"\")"""

        replacement_input = """        # ===== 第2步：发送正式消息 =====
        log(f'\\n第2步：准备输入长文本，长度: {len(MSG_TEXT)} 字符')
        set_status('typing')
        
        await page.evaluate(f\"\"\"
    (msgText) => {{
        const el = document.querySelector('div[contenteditable="true"].input-message-input') ||
                   document.querySelector('div[contenteditable="true"]');
        if (el) {{
            el.focus();
            document.execCommand('insertText', false, msgText);
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        }}
    }}
\"\"\", MSG_TEXT)"""

        target_old_input = """        # ===== 第2步：发送正式消息 =====
        log(f'\\n第2步：输入消息: {MSG_TEXT}')
        set_status('typing')
        await page.keyboard.type(MSG_TEXT, delay=80)"""

        updated = content
        updated = updated.replace(target_parse, replacement_parse)
        updated = updated.replace(target_input, replacement_input)
        updated = updated.replace(target_old_input, replacement_input)

        if updated == content:
            raise RuntimeError("patch_tg_remote: no target block matched; nothing was written.")

        validate_python_source(updated, "patch_tg_remote")
        backup_path = backup_remote_file(sftp, settings.tg_script_path)
        print(f"Created backup: {backup_path}")
        write_remote_text(sftp, settings.tg_script_path, updated)
        print(f"Updated {settings.tg_script_path}")


if __name__ == "__main__":
    main()
