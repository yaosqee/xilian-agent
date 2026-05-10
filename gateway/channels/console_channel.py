"""
ConsoleChannel — 终端控制台通道

基于 stdin/stdout 的交互式对话通道，用于开发调试。
支持彩色输出、Ctrl+D/Ctrl+C 优雅退出。
"""
import asyncio
import sys
from typing import Optional

from loguru import logger

from .base import Channel, EventHandler
from packages.shared.events import InternalEvent
from gateway.security import SecurityFilter


# ANSI 颜色（终端友好）
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"
BOLD = "\033[1m"


class ConsoleChannel(Channel):
    """终端交互通道"""

    def __init__(self, security: Optional[SecurityFilter] = None):
        super().__init__(name="Console")
        self.security = security or SecurityFilter()
        self._running = False

    async def start(self, handler: EventHandler) -> None:
        """启动终端对话循环"""
        self._running = True

        self._print_banner()
        self._print_help()

        while self._running:
            try:
                line = await self._read_line()
                if line is None:
                    # Ctrl+D / EOF
                    break
                if not line.strip():
                    continue

                # 检查内置命令
                if self._handle_builtin(line.strip()):
                    continue

                # 构造事件 → 安全过滤 → Agent 处理
                event = InternalEvent(
                    source="console",
                    user_id="hezi",
                    payload=line.strip(),
                    is_owner=True,
                )

                filtered = self.security.filter(event)
                if filtered is None:
                    self._print_blocked()
                    continue

                # 调用 Agent
                self._print_thinking()
                reply = await handler(filtered)

                await self.send(reply)

            except KeyboardInterrupt:
                # Ctrl+C
                print(f"\n{YELLOW}(输入 /quit 退出，或再按一次 Ctrl+C){RESET}")
            except asyncio.CancelledError:
                break

        await self.stop()

    async def send(self, text: str) -> None:
        """输出昔涟的回复"""
        # 换行美化
        print(f"\n{GREEN}{BOLD}昔涟{RESET} ✧ {text}\n")
        sys.stdout.flush()

    async def stop(self) -> None:
        """停止通道"""
        if self._running:
            self._running = False
            print(f"\n{YELLOW}昔涟合上了膝头的书……再见，伙伴。♪{RESET}")
            logger.info("console.stopped")

    # ── 内部方法 ──

    async def _read_line(self) -> Optional[str]:
        """异步读取一行 stdin"""
        loop = asyncio.get_event_loop()
        prompt = f"{CYAN}你{RESET} > "
        try:
            line = await loop.run_in_executor(None, lambda: input(prompt))
            return line
        except EOFError:
            return None

    def _handle_builtin(self, line: str) -> bool:
        """处理内置命令，返回 True 表示已处理"""
        if line.startswith("/"):
            cmd = line[1:].lower()
            if cmd in ("quit", "exit", "q"):
                self._running = False
                return True
            elif cmd == "help":
                self._print_help()
                return True
            elif cmd == "clear":
                print("\033[2J\033[H")  # 清屏
                self._print_banner()
                return True
        return False

    def _print_banner(self):
        print(f"""
{GREEN}{BOLD}╔══════════════════════════════╗
║   昔涟 V3.2 · 心之涟漪       ║
║   控制台通道 (开发调试)       ║
╚══════════════════════════════╝{RESET}
""")

    def _print_help(self):
        print(f"{YELLOW}命令:{RESET} /quit 退出 | /clear 清屏 | /help 帮助")
        print(f"{YELLOW}提示:{RESET} 直接输入文字，和昔涟聊天吧~\n")

    def _print_thinking(self):
        print(f"{YELLOW}昔涟正在翻书……{RESET}")

    def _print_blocked(self):
        print(f"{RED}⚠ 消息已被安全过滤拦截{RESET}")
