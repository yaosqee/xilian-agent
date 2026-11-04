"""P3 评测 harness 单测：用例结构、事实校验、指标、fake 全链路。"""
import sys

sys.path.insert(0, ".")

from datetime import datetime

import pytest

from evals.metrics import (
    CaseRun,
    EvalCase,
    check_fact,
    evaluate,
    load_cases,
    validate_cases,
)
from evals.runner import ScriptedAdapter, render_markdown, run_mode, run_cases


CASES_PATH = "evals/cases/agent_loop_v2.jsonl"
NOW = datetime(2026, 11, 4, 13, 30)  # 周三 13:30


def _case(case_id: str, category: str, **kwargs) -> EvalCase:
    data = {
        "id": case_id,
        "split": "train",
        "category": category,
        "message": "测试",
        "expect_tools": [],
    }
    data.update(kwargs)
    return EvalCase.from_dict(data)


# ─────────────────────────────────────────────────────────────
# 用例集
# ─────────────────────────────────────────────────────────────


def test_cases_file_is_valid_p3_set():
    cases = load_cases(CASES_PATH)
    assert len(cases) == 40
    assert validate_cases(cases) == []

    by_split = {"train": 0, "holdout": 0}
    by_category: dict[str, int] = {}
    for case in cases:
        by_split[case.split] += 1
        by_category[case.category] = by_category.get(case.category, 0) + 1
    assert by_split == {"train": 20, "holdout": 20}
    assert by_category == {
        "weather": 8, "time": 6, "memory": 6,
        "search": 6, "no_tool": 8, "multi_step": 6,
    }


def test_validate_cases_catches_unknown_tool():
    errors = validate_cases([
        _case("bad-1", "weather", expect_tools=["not_a_tool"]),
    ])
    assert any("未知工具" in error for error in errors)


# ─────────────────────────────────────────────────────────────
# 事实校验
# ─────────────────────────────────────────────────────────────


def test_check_fact_date_time_weekday():
    assert check_fact("今天是 2026-11-04。", "current_date", NOW)
    assert check_fact("今天是 11月4日。", "current_date", NOW)
    assert check_fact("今天是 11 月 4 号。", "current_date", NOW)
    assert check_fact("今天是 2026 年 11 月 4 日。", "current_date", NOW)
    assert not check_fact("今天是 2026-11-05。", "current_date", NOW)

    assert check_fact("现在是 13:32。", "current_time", NOW)
    assert check_fact("下午 1:32。", "current_time", NOW)
    assert check_fact("下午一点三十分。", "current_time", NOW)
    assert check_fact(
        "现在是傍晚六点三十七分。", "current_time",
        datetime(2026, 11, 4, 18, 37),
    )
    assert not check_fact("现在是 13:00。", "current_time", NOW)
    assert not check_fact("现在是 15:32。", "current_time", NOW)

    assert check_fact("今天周三。", "weekday", NOW)
    assert check_fact("今天是星期三。", "weekday", NOW)
    assert not check_fact("今天周四。", "weekday", NOW)


# ─────────────────────────────────────────────────────────────
# 指标
# ─────────────────────────────────────────────────────────────


def test_evaluate_metrics_and_failures():
    cases = [
        _case("w1", "weather", expect_tools=["query_weather"], min_tool_calls=1,
              must_contain=["杭州"]),
        _case("n1", "no_tool", max_tool_calls=0),
        _case("m1", "multi_step",
              expect_tools=["query_weather", "search_web"], min_tool_calls=2),
        _case("t1", "time", fact_check="current_date"),
    ]
    runs = [
        CaseRun("w1", reply="杭州 18℃", tool_calls=[{"name": "query_weather"}], latency_ms=10),
        CaseRun("n1", reply="嗯嗯", tool_calls=[{"name": "search_web"}], latency_ms=20),
        CaseRun("m1", reply="查好了", tool_calls=[
            {"name": "query_weather"}, {"name": "search_web"},
        ], latency_ms=30),
        CaseRun("t1", reply="今天是 2026-11-04", latency_ms=40),
    ]

    result = evaluate(cases, runs, now=NOW)
    summary = result["summary"]

    assert summary["total"] == 4
    assert summary["tool_call_rate"] == 0.75
    assert summary["correct_tool_rate"] == 1.0
    assert summary["no_tool_accuracy"] == 0.0
    assert summary["multi_step_completion"] == 1.0
    assert summary["fact_accuracy"] == 1.0
    assert summary["case_pass_rate"] == 0.75
    assert summary["avg_tool_calls"] == 1.0

    failed = {row["id"] for row in result["rows"] if not row["ok"]}
    assert failed == {"n1"}


def test_tool_success_rate_counts_execution_failures():
    """工具被调用了但执行失败（如搜索额度用尽）不能算成功。"""
    cases = [
        _case("s1", "search", expect_tools=["search_web"]),
        _case("s2", "search", expect_tools=["search_web"]),
    ]
    runs = [
        CaseRun(
            "s1",
            reply="查到了",
            tool_calls=[{"name": "search_web"}],
            tool_results=[{"name": "search_web", "ok": True, "error": ""}],
            latency_ms=5,
        ),
        CaseRun(
            "s2",
            reply="查不到",
            tool_calls=[{"name": "search_web"}],
            tool_results=[{"name": "search_web", "ok": False, "error": "额度不可用"}],
            latency_ms=5,
        ),
    ]

    result = evaluate(cases, runs, now=NOW)

    assert result["summary"]["tool_success_rate"] == 0.5
    assert result["summary"]["correct_tool_rate"] == 1.0  # 调用了就算"正确工具"
    assert result["rows"][1]["tool_results"][0]["ok"] is False


def test_tool_success_rate_is_zero_without_tool_calls():
    case = _case("n1", "no_tool", max_tool_calls=0)
    run = CaseRun("n1", reply="嗯嗯", latency_ms=1)
    result = evaluate([case], [run], now=NOW)
    assert result["summary"]["tool_success_rate"] == 0.0



def test_evaluate_missing_run_is_error():
    case = _case("w1", "weather", expect_tools=["query_weather"])
    result = evaluate([case], [], now=NOW)
    assert result["summary"]["errors"] == 1
    assert result["summary"]["case_pass_rate"] == 0.0


# ─────────────────────────────────────────────────────────────
# fake 全链路
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scripted_adapter_passes_all_cases():
    cases = load_cases(CASES_PATH)
    adapter = ScriptedAdapter(now=NOW)
    runs = await run_cases(cases, adapter)
    result = evaluate(cases, runs, now=NOW)

    assert result["summary"]["case_pass_rate"] == 1.0
    assert result["summary"]["correct_tool_rate"] == 1.0
    assert result["summary"]["no_tool_accuracy"] == 1.0
    assert result["summary"]["multi_step_completion"] == 1.0
    assert result["summary"]["fact_accuracy"] == 1.0


@pytest.mark.asyncio
async def test_runner_fake_mode_writes_report(tmp_path):
    cases = load_cases(CASES_PATH)
    result = await run_mode("fake", cases, timeout=1, db_dir=None)
    assert result["simulated"] is True
    assert result["summary"]["total"] == 40

    payload = {
        "generated_at": "2026-11-04T13:30:00",
        "cases_file": CASES_PATH,
        "split": "all",
        "case_count": 40,
        "modes": {"fake": result},
    }
    from evals.runner import write_report

    json_path, md_path = write_report(payload, tmp_path / "report")
    assert json_path.exists() and md_path.exists()
    markdown = md_path.read_text(encoding="utf-8")
    assert "SIMULATED" in markdown
    assert "| 平均工具调用数 | 0.8 |" in markdown
    assert "80.0%" not in markdown
