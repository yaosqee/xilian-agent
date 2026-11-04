"""search_web 供应商切换的纯函数单测（不联网）。"""
import sys

sys.path.insert(0, ".")

from datetime import datetime

import pytest

from packages.agent.tools.search_web import (
    build_deepseek_query,
    classify_status,
    map_deepseek_results,
)


NOW = datetime(2026, 11, 4, 20, 0)


def test_build_query_no_limit_keeps_query():
    assert build_deepseek_query("杭州天气", "noLimit", now=NOW) == "杭州天气"


def test_build_query_adds_after_syntax():
    assert "after:2026-11-04" in build_deepseek_query("杭州天气", "oneDay", now=NOW)
    assert "after:2026-10-29" in build_deepseek_query("杭州天气", "oneWeek", now=NOW)
    assert "after:2026-10-06" in build_deepseek_query("杭州天气", "oneMonth", now=NOW)


def test_map_results_prefers_summary_and_truncates():
    payload = {
        "results": [
            {
                "title": "标题A",
                "url": "https://a.example",
                "summary": "长摘要" * 200,
                "content": "",
                "site_name": "站点A",
                "date": "2026-11-03T00:00:00+00:00",
            },
            {
                "title": "标题B",
                "url": "https://b.example",
                "summary": "",
                "content": "正文B",
                "site_name": None,
                "date": None,
            },
        ]
    }

    mapped = map_deepseek_results(payload, 5)

    assert [m["title"] for m in mapped] == ["标题A", "标题B"]
    assert mapped[0]["link"] == "https://a.example"
    assert mapped[0]["publish_date"] == "2026-11-03"
    assert mapped[1]["link"] == "https://b.example"
    assert mapped[1]["content"] == "正文B"
    assert len(mapped[0]["content"]) <= 300


def test_map_results_respects_count():
    payload = {"results": [{"title": str(i)} for i in range(10)]}
    assert len(map_deepseek_results(payload, 3)) == 3


@pytest.mark.parametrize("status", [401, 402, 403])
def test_permanent_errors_tell_model_not_to_retry(status):
    retryable, message = classify_status(status)
    assert retryable is False
    assert "不要再重复搜索" in message or "不要重试" in message


@pytest.mark.parametrize("status", [408, 429, 500, 503, 504])
def test_transient_errors_are_retryable(status):
    retryable, message = classify_status(status)
    assert retryable is True
    assert "先别连续重试" in message


def test_unknown_4xx_is_not_retryable():
    retryable, message = classify_status(400)
    assert retryable is False
    assert "状态码 400" in message
