"""
P3 评测：用例模型、指标计算与事实校验。

设计原则：
- 纯函数、无网络、无 DB，所有逻辑可在单测里用固定 `now` 重放；
- 指标面向「该不该调工具」而不是「回复好不好」：
  tool_call_rate / correct_tool_rate / no_tool_accuracy /
  multi_step_completion / fact_accuracy；
- 时间/日期用例需要 ground truth，用 `check_fact()` 和真实时钟比较。

用例 JSONL 字段：
    id, split(train|holdout), category, message,
    expect_tools(list), min_tool_calls, max_tool_calls,
    fact_check(current_time|current_date|weekday), must_contain(list)
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


ALLOWED_TOOLS = {"query_weather", "search_web", "search_memory", "coding_delegate"}
FACT_CHECKS = {"current_time", "current_date", "weekday"}
CATEGORY_COUNTS = {
    "weather": 8,
    "time": 6,
    "memory": 6,
    "search": 6,
    "no_tool": 8,
    "multi_step": 6,
}
EXPECTED_TOTAL = 40
EXPECTED_SPLITS = {"train": 20, "holdout": 20}

_WEEKDAY_NAMES = "一二三四五六日"


@dataclass
class EvalCase:
    id: str
    split: str
    category: str
    message: str
    expect_tools: list[str] = field(default_factory=list)
    min_tool_calls: int = 0
    max_tool_calls: int | None = None
    fact_check: str | None = None
    must_contain: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvalCase":
        case = cls(
            id=str(data["id"]),
            split=str(data["split"]),
            category=str(data["category"]),
            message=str(data["message"]),
            expect_tools=list(data.get("expect_tools") or []),
            min_tool_calls=int(data.get("min_tool_calls", 0) or 0),
            max_tool_calls=(
                None if data.get("max_tool_calls") is None
                else int(data["max_tool_calls"])
            ),
            fact_check=data.get("fact_check"),
            must_contain=list(data.get("must_contain") or []),
        )
        if case.expect_tools and case.min_tool_calls == 0:
            case.min_tool_calls = 1
        return case


@dataclass
class CaseRun:
    case_id: str
    reply: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    # 每个工具调用的执行结果：{"name": ..., "ok": bool, "error": str}
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: int = 0
    model_calls: int = 0
    error: str = ""
    finished_at: datetime | None = None

    @property
    def tool_names(self) -> list[str]:
        return [str(call.get("name", "")) for call in self.tool_calls]


def load_cases(path: str | Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                cases.append(EvalCase.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{path}:{line_no} 用例格式错误：{exc}") from exc
    return cases


def validate_cases(cases: Iterable[EvalCase]) -> list[str]:
    """返回错误列表；空列表表示 40 条用例结构符合 P3 约定。"""
    cases = list(cases)
    errors: list[str] = []
    ids: set[str] = set()
    splits = {"train": 0, "holdout": 0}
    categories: dict[str, int] = {}

    for case in cases:
        if case.id in ids:
            errors.append(f"重复 id：{case.id}")
        ids.add(case.id)

        if case.split not in splits:
            errors.append(f"{case.id}: split 必须是 train/holdout")
        else:
            splits[case.split] += 1

        categories[case.category] = categories.get(case.category, 0) + 1

        for tool in case.expect_tools:
            if tool not in ALLOWED_TOOLS:
                errors.append(f"{case.id}: 未知工具 {tool}")
        if case.fact_check and case.fact_check not in FACT_CHECKS:
            errors.append(f"{case.id}: 未知 fact_check {case.fact_check}")
        if case.min_tool_calls < len(case.expect_tools):
            errors.append(
                f"{case.id}: min_tool_calls({case.min_tool_calls}) < "
                f"expect_tools({len(case.expect_tools)})"
            )
        if case.max_tool_calls is not None and case.max_tool_calls < case.min_tool_calls:
            errors.append(f"{case.id}: max_tool_calls < min_tool_calls")
        if not case.message.strip():
            errors.append(f"{case.id}: message 为空")

    if len(cases) != EXPECTED_TOTAL:
        errors.append(f"用例数 {len(cases)} != {EXPECTED_TOTAL}")
    for split, expected in EXPECTED_SPLITS.items():
        if splits[split] != expected:
            errors.append(f"split={split} 数量 {splits[split]} != {expected}")
    for category, expected in CATEGORY_COUNTS.items():
        if categories.get(category, 0) != expected:
            errors.append(
                f"category={category} 数量 {categories.get(category, 0)} != {expected}"
            )
    return errors


# ─────────────────────────────────────────────────────────────
# 事实校验
# ─────────────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


_CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def _cn_to_int(token: str) -> int | None:
    """中文数字转整数，覆盖 六 / 十 / 十八 / 三十七 这类时间写法。"""
    if not token:
        return None
    if token.isdigit():
        return int(token)
    token = token.replace("零", "")
    if not token:
        return 0
    if "十" in token:
        left, _, right = token.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0) if right else 0
        if left and left not in _CN_DIGITS:
            return None
        if right and right not in _CN_DIGITS:
            return None
        return tens * 10 + ones
    if len(token) == 1:
        return _CN_DIGITS.get(token)
    return None


def _extract_times(text: str) -> list[tuple[int, int | None]]:
    """从回复里抽取 (hour, minute|None)，支持 22:47 / 22点47分 / 六点三十七分。"""
    text = _normalize(text)
    found: list[tuple[int, int | None]] = []

    for match in re.finditer(r"(\d{1,2})\s*[:：]\s*(\d{2})", text):
        hour, minute = int(match.group(1)), int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            found.append((hour, minute))

    for match in re.finditer(r"(\d{1,2})\s*(?:点|时)(?:\s*(\d{1,2})\s*分?)?", text):
        hour = int(match.group(1))
        minute = int(match.group(2)) if match.group(2) else None
        if 0 <= hour <= 23 and (minute is None or 0 <= minute <= 59):
            found.append((hour, minute))

    # 中文数字写法：六点三十七分 / 十八点零五分（排除「一点点」）
    for match in re.finditer(
        r"([零一二三四五六七八九十两]{1,4})\s*点(?!点)"
        r"(?:\s*([零一二三四五六七八九十两]{1,4})\s*分?)?",
        text,
    ):
        hour = _cn_to_int(match.group(1))
        minute = _cn_to_int(match.group(2)) if match.group(2) else None
        if hour is not None and 0 <= hour <= 23 and (
            minute is None or 0 <= minute <= 59
        ):
            found.append((hour, minute))

    return found


def check_fact(reply: str, kind: str, now: datetime | None = None) -> bool:
    """检查回复是否包含当前时间/日期/星期的 ground truth。"""
    text = _normalize(reply)
    if not text:
        return False
    now = now or datetime.now()
    compact = re.sub(r"\s+", "", text)

    if kind == "current_date":
        candidates = {
            now.strftime("%Y-%m-%d"),
            now.strftime("%Y/%m/%d"),
            f"{now.year}年{now.month}月{now.day}日",
            f"{now.year}年{now.month}月{now.day}号",
            f"{now.month}月{now.day}日",
            f"{now.month}月{now.day}号",
            f"{now.month:02d}月{now.day:02d}日",
            f"{now.month:02d}月{now.day:02d}号",
            f"{now.month:02d}-{now.day:02d}",
        }
        return any(candidate in compact for candidate in candidates)

    if kind == "weekday":
        name = _WEEKDAY_NAMES[now.weekday()]
        return f"周{name}" in compact or f"星期{name}" in compact

    if kind == "current_time":
        for hour, minute in _extract_times(text):
            if hour != now.hour:
                continue
            if minute is None or abs(minute - now.minute) <= 5:
                return True
        # 24 小时制下 22 点也可能写成「晚上 10 点」，允许 12 小时制换算
        for hour, minute in _extract_times(text):
            converted = hour + 12 if hour < 12 else hour
            if converted == now.hour and (minute is None or abs(minute - now.minute) <= 5):
                return True
        return False

    return False


# ─────────────────────────────────────────────────────────────
# 指标
# ─────────────────────────────────────────────────────────────


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _summarize(
    cases: list[EvalCase],
    runs_by_id: dict[str, CaseRun],
    *,
    now: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    errors = 0
    tool_call_hits = 0
    expected_total = 0
    expected_hits = 0
    no_tool_total = 0
    no_tool_hits = 0
    multi_total = 0
    multi_hits = 0
    fact_total = 0
    fact_hits = 0
    tool_success_total = 0
    tool_success_hits = 0
    keyword_total = 0
    keyword_hits = 0
    passed = 0
    total_latency = 0
    total_tool_calls = 0
    total_model_calls = 0

    for case in cases:
        run = runs_by_id.get(case.id) or CaseRun(
            case_id=case.id, error="missing run"
        )
        names = run.tool_names
        calls = len(names)
        total_latency += run.latency_ms
        total_tool_calls += calls
        total_model_calls += run.model_calls
        if run.error:
            errors += 1

        if calls > 0:
            tool_call_hits += 1

        for item in run.tool_results:
            tool_success_total += 1
            if item.get("ok"):
                tool_success_hits += 1

        expected_ok: bool | None = None
        if case.expect_tools:
            expected_total += 1
            expected_ok = set(case.expect_tools).issubset(set(names))
            if expected_ok:
                expected_hits += 1

        no_tool_ok: bool | None = None
        if case.category == "no_tool" or case.max_tool_calls == 0:
            no_tool_total += 1
            no_tool_ok = calls == 0
            if no_tool_ok:
                no_tool_hits += 1

        min_ok = calls >= case.min_tool_calls
        max_ok = case.max_tool_calls is None or calls <= case.max_tool_calls

        fact_ok: bool | None = None
        if case.fact_check:
            fact_total += 1
            fact_ok = check_fact(
                run.reply, case.fact_check, now=run.finished_at or now
            )
            if fact_ok:
                fact_hits += 1

        keyword_ok: bool | None = None
        if case.must_contain:
            keyword_total += 1
            normalized_reply = _normalize(run.reply).lower()
            keyword_ok = all(
                _normalize(keyword).lower() in normalized_reply
                for keyword in case.must_contain
            )
            if keyword_ok:
                keyword_hits += 1

        multi_ok: bool | None = None
        if case.category == "multi_step":
            multi_total += 1
            multi_ok = (
                calls >= max(2, case.min_tool_calls)
                and (expected_ok is not False)
                and not run.error
            )
            if multi_ok:
                multi_hits += 1

        case_ok = (
            not run.error
            and min_ok
            and max_ok
            and (expected_ok is not False)
            and (no_tool_ok is not False)
            and (fact_ok is not False)
            and (keyword_ok is not False)
        )
        if case_ok:
            passed += 1

        rows.append({
            "id": case.id,
            "split": case.split,
            "category": case.category,
            "message": case.message,
            "tools": names,
            "tool_calls": calls,
            "tool_results": run.tool_results,
            "model_calls": run.model_calls,
            "latency_ms": run.latency_ms,
            "ok": case_ok,
            "expected_tools_ok": expected_ok,
            "no_tool_ok": no_tool_ok,
            "fact_ok": fact_ok,
            "keyword_ok": keyword_ok,
            "multi_step_ok": multi_ok,
            "error": run.error,
            "reply_preview": (run.reply or "")[:200],
        })

    total = len(cases)
    summary = {
        "total": total,
        "errors": errors,
        "case_pass_rate": _rate(passed, total),
        "tool_call_rate": _rate(tool_call_hits, total),
        "correct_tool_rate": _rate(expected_hits, expected_total),
        "no_tool_accuracy": _rate(no_tool_hits, no_tool_total),
        "multi_step_completion": _rate(multi_hits, multi_total),
        "fact_accuracy": _rate(fact_hits, fact_total),
        "tool_success_rate": _rate(tool_success_hits, tool_success_total),
        "keyword_accuracy": _rate(keyword_hits, keyword_total),
        "avg_latency_ms": round(total_latency / total, 1) if total else 0.0,
        "avg_tool_calls": round(total_tool_calls / total, 2) if total else 0.0,
        "avg_model_calls": round(total_model_calls / total, 2) if total else 0.0,
    }
    return summary, rows


def evaluate(
    cases: Iterable[EvalCase],
    runs: Iterable[CaseRun],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """计算总体 + 分 split / 分 category 指标。"""
    cases = list(cases)
    now = now or datetime.now()
    runs_by_id = {run.case_id: run for run in runs}

    summary, rows = _summarize(cases, runs_by_id, now=now)
    by_split = {}
    for split in ("train", "holdout"):
        subset = [case for case in cases if case.split == split]
        by_split[split] = _summarize(subset, runs_by_id, now=now)[0]

    by_category = {}
    for category in CATEGORY_COUNTS:
        subset = [case for case in cases if case.category == category]
        by_category[category] = _summarize(subset, runs_by_id, now=now)[0]

    return {
        "summary": summary,
        "by_split": by_split,
        "by_category": by_category,
        "rows": rows,
    }
