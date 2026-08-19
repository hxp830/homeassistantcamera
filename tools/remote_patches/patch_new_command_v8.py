import re

from remote_utils import load_remote_settings, patch_remote_python_file


REPLACEMENT_BLOCK = """        # ===== 第1步：发送 /new (v8 - 针对性点击 multiline-item 菜单选项) =====
        log('第1步：尝试发送 /new ...')
        set_status('typing_new')
        
        try:
            # 等待聊天界面加载
            await page.wait_for_selector('.chat-background, .messages-layout', timeout=15000, state='visible')
            
            log("  清空输入框...")
            input_selector = 'div[contenteditable="true"].input-message-input, div[contenteditable="true"]'
            input_field = await page.wait_for_selector(input_selector, timeout=5000, state='visible')
            
            await input_field.click(force=True)
            await page.keyboard.press('Control+A')
            await page.keyboard.press('Backspace')
            await asyncio.sleep(0.5)

            log("  模拟键盘打字 '/new'...")
            # 必须用 /new 且不带空格，才能触发内联命令补全
            await page.keyboard.type('/new', delay=100)
            
            # 等待自动补全菜单弹出
            log("  等待包含 /new 的 .multiline-item 菜单弹出...")
            await asyncio.sleep(1.5)
            
            # 核心修改：寻找所有 .multiline-item，再精确定位标题为 /new 的那一个
            menu_item_clicked = await page.evaluate(\"\"\"
                () => {
                    const items = document.querySelectorAll('.multiline-item');
                    for (const item of items) {
                        const titleSpan = item.querySelector('.title');
                        if (titleSpan && titleSpan.innerText.trim() === '/new') {
                            item.click();
                            return true;
                        }
                    }
                    return false;
                }
            \"\"\")
            
            if menu_item_clicked:
                log("  ✓ 成功找到了并点击了下拉列表中的 /new 选项！")
            else:
                log("  - 未找到下拉列表中的 /new，尝试使用 Playwright locator 点击...")
                try:
                    await page.locator('.multiline-item:has(.title:has-text(\"/new\"))').first.click(timeout=3000)
                    log("  ✓ 使用 Locator 点击成功！")
                except Exception as ex2:
                    log(f"  ⚠ Locator点击失败: {ex2}，盲按回车...")
                    await page.keyboard.press('Enter')
            
            await asyncio.sleep(2)
            
            current_text = await input_field.text_content()
            if current_text and "/new" in current_text:
                log("  ⚠ 输入框中还有内容，可能是被拦截，再补一脚发送按钮或回车")
                await page.keyboard.press('Enter')
                await asyncio.sleep(1)

        except Exception as e:
            log(f"  ⚠ 准备 /new 严重失败: {e}")
            
        await page.screenshot(path='/tmp/tg_p4b_new_sent.png')
        log('  截图: /tmp/tg_p4b_new_sent.png')
        log('  ✓ /new 发送流程结束')"""

PATTERN = re.compile(
    r"        # ===== 第1步：发送 /new .*?=====(.*?)(?=log\('  ✓ /new 发送流程结束'\)|log\('  ✓ /new 发送流程已执行'\))log\('  ✓ /new 发送流程(?:结束|已执行)'\)",
    re.DOTALL,
)


def main() -> None:
    settings = load_remote_settings()
    patch_remote_python_file(
        target_path=settings.tg_script_path,
        mirror_paths=[settings.tg_tmp_script_path],
        pattern=PATTERN,
        replacement=REPLACEMENT_BLOCK,
        patch_label="patch_new_command_v8",
        expected_markers=[
            "v8 - 针对性点击 multiline-item 菜单选项",
            ".multiline-item",
            "log('  ✓ /new 发送流程结束')",
        ],
    )
    print("Patch applied successfully with backup, validation, and guarded write.")


if __name__ == "__main__":
    main()
