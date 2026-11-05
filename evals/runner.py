"""
P3 评测 runner。

用法（默认 fake，不联网、不写真实 DB）：
    uv run python -m evals.runner --mode fake
    uv run python -m evals.runner --mode legacy --limit 2
    uv run python -m evals.runner --mode all --split all --output evals/reports/latest

模式：
- fake   : 按用例期望生成「完美脚本」，只用于验证 harness / 报告，报告标记 simulated；
- legacy : 真实 AgentCore，LOOP_V2=0（老工具路径）；
- loop   : 真实 AgentCore，LOOP_V2=1（新循环）；
- all    : legacy + loop 各跑一遍。

live 模式每个用例使用临时 DB，跳过了角色记忆播种（24 条向量化），
用例之间清空 history / pending，避免上下文互相污染。
"""
from __future__ import annotations

import argparse
import asyncio
import functools
import hashlib
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from .metrics import (
    CATEGORY_COUNTS,
    CaseRun,
    EvalCase,
    evaluate,
    load_cases,
    validate_cases,
)


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CASES = ROOT / "evals" / "cases" / "agent_loop_v2.jsonl"
DEFAULT_OUTPUT = ROOT / "evals" / "reports" / "latest"
_WEEKDAY_NAMES = "一二三四五六日"


# ─────────────────────────────────────────────────────────────
# 通用执行
# ─────────────────────────────────────────────────────────────


async def run_cases(cases: list[EvalCase], adapter: Any) -> list[CaseRun]:
    runs: list[CaseRun] = []
    for index, case in enumerate(cases, 1):
        logger.info("evals.case", index=index, total=len(cases), case_id=case.id)
        runs.append(await adapter.process(case))
    return runs


class ScriptedAdapter:
    """不联网的 oracle 脚本：按 expect_tools / fact_check 生成结果。

    它不代表模型真实能力，只验证 runner、指标和报告链路；报告会标 simulated。
    """

    simulated = True

    def __init__(self, now: datetime | None = None):
        self.now = now or datetime.now()

    async def process(self, case: EvalCase) -> CaseRun:
        calls = []
        for tool in case.expect_tools:
            if tool == "query_weather":
                arguments = {"city": (case.must_contain or ["杭州"])[0]}
            else:
                arguments = {"query": case.message[:60]}
            calls.append({"name": tool, "arguments": arguments})

        if case.fact_check == "current_date":
            reply = (
                f"今天是 {self.now.year}-{self.now.month:02d}-{self.now.day:02d}。"
            )
        elif case.fact_check == "current_time":
            reply = f"现在是 {self.now.hour:02d}:{self.now.minute:02d}。"
        elif case.fact_check == "weekday":
            reply = f"今天周{_WEEKDAY_NAMES[self.now.weekday()]}。"
        elif case.category == "no_tool":
            reply = "人家听着呢。"
        else:
            reply = "查好啦。"
            if case.must_contain:
                reply = f"{'、'.join(case.must_contain)}：{reply}"

        return CaseRun(
            case_id=case.id,
            reply=reply,
            tool_calls=calls,
            # 脚本 oracle 假定工具都成功；报告已标 SIMULATED
            tool_results=[
                {"name": call["name"], "ok": True, "error": ""} for call in calls
            ],
            latency_ms=1,
            model_calls=1,
            finished_at=self.now,
        )

    async def close(self) -> None:
        return None


class LiveAgentAdapter:
    """真实 AgentCore（临时 DB）。mode 由 LOOP_V2 决定。"""

    simulated = False

    def __init__(self, loop_v2: bool, *, timeout: float = 120.0,
                 db_dir: Path | None = None, thinking: bool = False,
                 routing_v2: bool = False):
        self.loop_v2 = loop_v2
        self.routing_v2 = routing_v2
        self.timeout = timeout
        self.db_dir = db_dir
        self.thinking = thinking
        self.agent = None
        self._tmp: tempfile.TemporaryDirectory | None = None
        self._old_loop_v2: str | None = None
        self._old_routing_v2: str | None = None
        self._old_thinking: str | None = None
        self.available_tools: list[str] = []
        self._tool_calls: list[dict[str, Any]] = []
        self._tool_results: list[dict[str, Any]] = []
        self._model_calls = 0

    async def start(self) -> None:
        # AgentCore.__init__ / DeepSeekAdapter 会读环境变量，必须在构造前设置
        self._old_loop_v2 = os.environ.get("LOOP_V2")
        self._old_routing_v2 = os.environ.get("MODEL_ROUTING_V2")
        self._old_thinking = os.environ.get("DEEPSEEK_DISABLE_THINKING")
        os.environ["LOOP_V2"] = "1" if self.loop_v2 else "0"
        os.environ["MODEL_ROUTING_V2"] = "1" if self.routing_v2 else "0"
        # thinking 开启时 DeepSeek 不接受 tool_choice 强制指定，P3 默认关闭
        os.environ["DEEPSEEK_DISABLE_THINKING"] = "0" if self.thinking else "1"

        from packages.agent.agent_core import AgentCore

        if self.db_dir is None:
            self._tmp = tempfile.TemporaryDirectory(prefix="xilian-eval-")
            db_path = Path(self._tmp.name) / "eval.db"
        else:
            self.db_dir.mkdir(parents=True, exist_ok=True)
            db_path = self.db_dir / f"eval_{'loop' if self.loop_v2 else 'legacy'}.db"

        self.agent = AgentCore(db_path=str(db_path))

        # 评测不需要 24 条角色记忆的向量化播种（启动成本高且与指标无关）
        async def _skip_character_seed() -> int:
            return 0

        self.agent._ensure_character_memories = _skip_character_seed
        await self.agent.startup()

        original_execute = self.agent.tool_executor.execute

        @functools.wraps(original_execute)
        async def recording_execute(tool_name, arguments, *args, **kwargs):
            self._tool_calls.append({
                "name": tool_name,
                "arguments": dict(arguments or {}),
            })
            result = await original_execute(tool_name, arguments, *args, **kwargs)
            self._tool_results.append({
                "name": tool_name,
                "ok": bool(getattr(result, "success", False)),
                "error": str(getattr(result, "error", "") or "")[:160],
            })
            return result

        self.agent.tool_executor.execute = recording_execute

        original_route = self.agent.router.route

        @functools.wraps(original_route)
        async def recording_route(*args, **kwargs):
            self._model_calls += 1
            return await original_route(*args, **kwargs)

        self.agent.router.route = recording_route
        self.available_tools = list(self.agent.tool_registry.tool_names)
        logger.info(
            "evals.agent_ready",
            mode="loop" if self.loop_v2 else "legacy",
            db=str(db_path),
            thinking=self.thinking,
            tools=self.available_tools,
        )

    async def _drain_background(self) -> None:
        """等上一轮的异步情感/记忆任务结束，避免污染下一轮计数。"""
        if self.agent is None:
            return
        tasks = {
            task for task in getattr(self.agent, "_bg_tasks", set())
            if not task.done()
        }
        pending = getattr(self.agent, "_pending_analysis", None)
        if pending is not None and not pending.done():
            tasks.add(pending)
        if not tasks:
            return
        _, still_pending = await asyncio.wait(tasks, timeout=15)
        for task in still_pending:
            task.cancel()
            logger.warning("evals.background_cancelled")

    def _reset_case_state(self) -> None:
        self._tool_calls = []
        self._tool_results = []
        self._model_calls = 0
        context = self.agent.context
        context.history.clear()
        context._total_history_tokens = 0
        context.memory_retrieval = None
        context.character_memory_retrieval = None
        context.emotion_snapshot = None
        context.last_emotion_strategy = ""
        context._last_user_message = ""
        self.agent._current_images = []
        self.agent._current_user_msg = ""
        self.agent._pending_confirmation = None
        # 评测用例互相独立，清掉频率窗口，避免第 N 条天气被第 N-1 条限流影响
        tool_executor = getattr(self.agent, "tool_executor", None)
        if tool_executor is not None and hasattr(tool_executor, "_call_counts"):
            tool_executor._call_counts.clear()
        loop_confirmations = getattr(self.agent, "_loop_confirmations", None)
        if loop_confirmations is not None:
            loop_confirmations.clear()

    async def process(self, case: EvalCase) -> CaseRun:
        from packages.shared.events import InternalEvent

        await self._drain_background()
        self._reset_case_state()

        event = InternalEvent(
            source="eval",
            user_id="hezi",
            session_id=f"eval-{case.id}",
            payload=case.message,
            is_owner=True,
        )
        started = time.perf_counter()
        error = ""
        reply = ""
        try:
            response = await asyncio.wait_for(
                self.agent.process(event), timeout=self.timeout
            )
            reply = response.reply or ""
        except Exception as exc:  # noqa: BLE001 — 单条失败不能让整轮评测中断
            error = f"{type(exc).__name__}: {exc}"
            logger.warning("evals.case_error", case_id=case.id, error=error[:200])
        latency_ms = int((time.perf_counter() - started) * 1000)

        run = CaseRun(
            case_id=case.id,
            reply=reply,
            tool_calls=list(self._tool_calls),
            tool_results=list(self._tool_results),
            latency_ms=latency_ms,
            model_calls=self._model_calls,
            error=error,
            finished_at=datetime.now(),
        )
        await self._drain_background()
        return run

    async def close(self) -> None:
        try:
            if self.agent is not None:
                await self.agent.shutdown()
        finally:
            if self._old_loop_v2 is None:
                os.environ.pop("LOOP_V2", None)
            else:
                os.environ["LOOP_V2"] = self._old_loop_v2
            if self._old_thinking is None:
                os.environ.pop("DEEPSEEK_DISABLE_THINKING", None)
            else:
                os.environ["DEEPSEEK_DISABLE_THINKING"] = self._old_thinking
            if self._old_routing_v2 is None:
                os.environ.pop("MODEL_ROUTING_V2", None)
            else:
                os.environ["MODEL_ROUTING_V2"] = self._old_routing_v2
            if self._tmp is not None:
                self._tmp.cleanup()


# ─────────────────────────────────────────────────────────────
# 报告
# ─────────────────────────────────────────────────────────────


def _summary_line(summary: dict[str, Any]) -> str:
    return (
        f"pass={summary['case_pass_rate']:.1%} "
        f"tool_call={summary['tool_call_rate']:.1%} "
        f"correct_tool={summary['correct_tool_rate']:.1%} "
        f"no_tool={summary['no_tool_accuracy']:.1%} "
        f"multi_step={summary['multi_step_completion']:.1%} "
        f"fact={summary['fact_accuracy']:.1%} "
        f"tool_success={summary.get('tool_success_rate', 0.0):.1%} "
        f"avg_latency={summary['avg_latency_ms']}ms"
    )


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# P3 评测报告：Agent 循环 v2",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 用例文件：`{payload['cases_file']}`",
        f"- split：`{payload['split']}`，category：`{payload.get('category', 'all')}`，用例数：{payload['case_count']}",
        "",
    ]
    modes: dict[str, Any] = payload["modes"]
    for mode, result in modes.items():
        summary = result["summary"]
        lines.append(f"## {mode}")
        if result.get("simulated"):
            lines.append("> **SIMULATED**：脚本生成结果，不代表真实模型能力。")
        tools = result.get("available_tools") or []
        if tools:
            lines.append(f"- 可用工具：{', '.join(tools)}")
        if result.get("thinking") is not None:
            lines.append(f"- thinking：{'on' if result['thinking'] else 'off'}")
        lines.append("")
        lines.append("| 指标 | 值 |")
        lines.append("|---|---|")
        for key, label in (
            ("case_pass_rate", "用例通过率"),
            ("tool_call_rate", "工具调用率"),
            ("correct_tool_rate", "正确工具率"),
            ("no_tool_accuracy", "不该调准确率"),
            ("multi_step_completion", "多步完成率"),
            ("fact_accuracy", "事实正确率"),
            ("tool_success_rate", "工具执行成功率"),
            ("keyword_accuracy", "关键词命中率"),
            ("avg_latency_ms", "平均耗时(ms)"),
            ("avg_tool_calls", "平均工具调用数"),
            ("avg_model_calls", "平均模型调用数"),
        ):
            value = summary.get(key)
            if key not in ("avg_latency_ms", "avg_tool_calls", "avg_model_calls"):
                value = f"{value:.1%}"
            lines.append(f"| {label} | {value} |")
        lines.append("")

        by_split = result.get("by_split") or {}
        if by_split:
            lines.append("| split | 用例 | 通过率 | 事实正确 | 多步 |")
            lines.append("|---|---|---|---|---|")
            for split in ("train", "holdout"):
                part = by_split.get(split)
                if not part:
                    continue
                lines.append(
                    f"| {split} | {part['total']} | {part['case_pass_rate']:.1%} | "
                    f"{part['fact_accuracy']:.1%} | {part['multi_step_completion']:.1%} |"
                )
            lines.append("")

        failed = [row for row in result["rows"] if not row["ok"]]
        lines.append(f"失败用例：{len(failed)} / {summary['total']}")
        if failed:
            lines.append("")
            lines.append("| id | category | tools | error |")
            lines.append("|---|---|---|---|")
            for row in failed[:20]:
                lines.append(
                    f"| {row['id']} | {row['category']} | "
                    f"{', '.join(row['tools']) or '-'} | {row['error'] or '-'} |"
                )
        lines.append("")
    return "\n".join(lines)


def write_report(payload: dict[str, Any], output_base: Path) -> tuple[Path, Path]:
    output_base.parent.mkdir(parents=True, exist_ok=True)
    json_path = output_base.with_suffix(".json")
    md_path = output_base.with_suffix(".md")
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_path.write_text(render_markdown(payload), encoding="utf-8")
    return json_path, md_path


# ─────────────────────────────────────────────────────────────
# 入口
# ─────────────────────────────────────────────────────────────


async def run_mode(
    mode: str,
    cases: list[EvalCase],
    *,
    timeout: float,
    db_dir: Path | None,
    thinking: bool = False,
    routing_v2: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    if mode == "fake":
        adapter: Any = ScriptedAdapter()
    else:
        adapter = LiveAgentAdapter(
            mode == "loop", timeout=timeout, db_dir=db_dir, thinking=thinking,
            routing_v2=routing_v2,
        )
        try:
            await adapter.start()
        except Exception:
            await adapter.close()
            raise
    try:
        runs = await run_cases(cases, adapter)
    finally:
        await adapter.close()

    result = evaluate(cases, runs)
    return {
        "mode": mode,
        "simulated": adapter.simulated,
        "thinking": getattr(adapter, "thinking", None),
        "routing_v2": bool(getattr(adapter, "routing_v2", False)),
        "available_tools": list(getattr(adapter, "available_tools", [])),
        "duration_sec": round(time.perf_counter() - started, 2),
        **result,
    }


async def main_async(args: argparse.Namespace) -> int:
    cases = load_cases(args.cases)
    errors = validate_cases(cases)
    if errors:
        for error in errors:
            logger.error("evals.case_invalid", error=error)
        return 2

    if args.split != "all":
        cases = [case for case in cases if case.split == args.split]
    if args.category != "all":
        cases = [case for case in cases if case.category == args.category]
    if args.limit and args.limit > 0:
        cases = cases[: args.limit]
    if not cases:
        logger.error("evals.no_cases")
        return 2

    modes = ["legacy", "loop"] if args.mode == "all" else [args.mode]
    db_dir = Path(args.db_dir) if args.db_dir else None
    results: dict[str, Any] = {}
    for mode in modes:
        logger.info("evals.mode_start", mode=mode, cases=len(cases))
        results[mode] = await run_mode(
            mode, cases, timeout=args.timeout, db_dir=db_dir,
            thinking=args.thinking == "on",
            routing_v2=args.routing_v2 and mode == "loop",
        )
        logger.info(
            "evals.mode_done", mode=mode,
            summary=results[mode]["summary"],
        )

    cases_sha256 = hashlib.sha256(Path(args.cases).read_bytes()).hexdigest()
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "cases_file": str(args.cases),
        # 用例集指纹：冻结后一旦变化，报告里能立刻看出来
        "cases_sha256": cases_sha256,
        "split": args.split,
        "category": args.category,
        "case_count": len(cases),
        "modes": results,
    }
    json_path, md_path = write_report(payload, Path(args.output))
    print(f"EVAL_DONE json={json_path} md={md_path}")
    for mode, result in results.items():
        print(f"{mode}: {_summary_line(result['summary'])}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="P3 Agent 循环评测 runner")
    parser.add_argument(
        "--mode", default="fake",
        choices=["fake", "legacy", "loop", "all"],
        help="fake=脚本冒烟；legacy/loop=真实 AgentCore；all=两种模式都跑",
    )
    parser.add_argument(
        "--split", default="all", choices=["all", "train", "holdout"],
    )
    parser.add_argument(
        "--category", default="all", choices=["all", *CATEGORY_COUNTS],
        help="只跑某一类（weather/time/memory/search/no_tool/multi_step）",
    )
    parser.add_argument(
        "--limit", type=int, default=0, help="只跑前 N 条（0=全部）",
    )
    parser.add_argument(
        "--timeout", type=float, default=120.0, help="单条用例超时秒数",
    )
    parser.add_argument(
        "--thinking", default="off", choices=["on", "off"],
        help="DeepSeek thinking；默认 off（thinking 开启时强制 tool_choice 会 400）",
    )
    parser.add_argument(
        "--routing-v2", action="store_true",
        help="loop 模式使用 MODEL_ROUTING_V2=1（legacy 仍用 V1）",
    )
    parser.add_argument(
        "--cases", default=str(DEFAULT_CASES),
    )
    parser.add_argument(
        "--output", default=str(DEFAULT_OUTPUT),
        help="报告输出前缀（生成 .json + .md）",
    )
    parser.add_argument(
        "--db-dir", default=None,
        help="live 模式的 DB 目录；默认临时目录",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="保留 AgentCore DEBUG/INFO 日志（默认只显示 WARNING）",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    # .env 里是 API Key；评测 runner 不走 main.py，必须自己加载
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except Exception as exc:  # noqa: BLE001 — 没有 dotenv 时仍允许跑 fake
        logger.debug("evals.dotenv_skip", error=str(exc))
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not getattr(args, "verbose", False):
        # 评测默认只保留结果和警告，避免 40 条用例的 AgentCore 日志刷屏
        logger.remove()
        logger.add(sys.stderr, level="WARNING")
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
