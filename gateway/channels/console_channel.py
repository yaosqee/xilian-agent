"""
ConsoleChannel — 终端控制台通道（阶段 6：rich 美化）

基于 stdin/stdout 的交互式对话通道，用于开发调试。
支持 rich 美化输出、Ctrl+D/Ctrl+C 优雅退出。
"""
import asyncio
import sys
from typing import Optional

from loguru import logger

from .base import Channel, EventHandler
from packages.shared.events import InternalEvent
from gateway.security import SecurityFilter

# Rich 终端美化
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.live import Live
from rich.spinner import Spinner

# 主题色
PINK = "#ff69b4"        # 昔涟粉
CYAN_HEX = "#00e5ff"    # 用户青
YELLOW_HEX = "#ffd54f"  # 提示黄
DIM = "dim"             # 系统灰
GREEN_HEX = "#69f0ae"   # 成功绿


class ConsoleChannel(Channel):
    """终端交互通道 — rich 美化版"""

    def __init__(self, security: Optional[SecurityFilter] = None):
        super().__init__(name="Console")
        self.security = security or SecurityFilter()
        self._running = False
        self._console = Console(highlight=False)

    async def start(self, handler: EventHandler) -> None:
        """启动终端对话循环"""
        self._running = True

        self._print_banner()
        self._print_help()

        while self._running:
            try:
                line = await self._read_line()
                if line is None:
                    break
                if not line.strip():
                    continue

                if self._handle_builtin(line.strip()):
                    continue

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

                self._print_thinking()
                reply = await handler(filtered)

                await self.send(reply)

            except KeyboardInterrupt:
                self._console.print(
                    Text(" (输入 /quit 退出，或再按一次 Ctrl+C)", style="dim italic")
                )
            except asyncio.CancelledError:
                break

        await self.stop()

    async def send(self, text: str) -> None:
        """输出昔涟的回复（rich Panel 渲染）"""
        self._console.print()  # 空行
        content = Text(text, style=PINK)
        panel = Panel(
            content,
            border_style=PINK,
            title="🐾 昔涟",
            title_align="left",
            padding=(0, 1),
        )
        self._console.print(panel)
        self._console.print()

    async def stop(self) -> None:
        """停止通道"""
        if self._running:
            self._running = False
            farewell = Panel(
                "昔涟合上了膝头的书……再见，伙伴。♪",
                border_style=DIM,
                title="🐾",
            )
            self._console.print(farewell)
            logger.info("console.stopped")

    # ── 内部方法 ──

    async def _read_line(self) -> Optional[str]:
        """异步读取一行 stdin"""
        loop = asyncio.get_event_loop()
        prompt = Text("你", style=f"bold {CYAN_HEX}")
        prompt.append(" > ", style="dim")
        try:
            line = await loop.run_in_executor(None, lambda: input(str(prompt)))
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
                self._console.clear()
                self._print_banner()
                return True
        return False

    def _print_banner(self):
        banner = Panel(
            Text("昔涟 · 心之涟漪\n", style=f"bold {PINK}", justify="center")
            + Text("控制台通道 (开发调试)", style=DIM, justify="center"),
            border_style=PINK,
            padding=(1, 2),
        )
        self._console.print(banner)
        self._console.print()

    def _print_help(self):
        self._console.print(
            Text("命令: ", style="dim")
            + Text("/quit", style="bold yellow")
            + Text(" 退出 | ", style="dim")
            + Text("/clear", style="bold yellow")
            + Text(" 清屏 | ", style="dim")
            + Text("/help", style="bold yellow")
            + Text(" 帮助", style="dim")
        )
        self._console.print(
            Text("提示: ", style="dim")
            + Text("直接输入文字，和昔涟聊天吧~", style="italic")
        )
        self._console.print()

    def _print_thinking(self):
        self._console.print(
            Text("昔涟正在翻书…", style="italic dim")
        )

    def _print_blocked(self):
        self._console.print(
            Text("⚠ 消息已被安全过滤拦截", style="bold red")
        )
