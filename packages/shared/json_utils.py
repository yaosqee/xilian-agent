"""LLM 输出 JSON 容错解析工具。"""
import json
import re
from typing import Any


def robust_json_parse(text: str | None) -> Any:
    """容错解析 LLM 输出的 JSON。

    处理 LLM 常见的不规范输出：
    1. markdown 代码块围栏（```json ... ```）
    2. JSON 前后夹杂的文字（截取首个 { 到最后一个 }）

    Args:
        text: LLM 原始输出文本

    Returns:
        解析后的对象（dict/list/...），解析失败返回 None。
    """
    if text is None:
        return None

    text = text.strip()
    if not text:
        return None

    # 1. 剥离 markdown 代码块围栏
    fence = re.search(r"```(?:json)?[^\n]*\n(.*?)\n?```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    # 2. 直接解析
    try:
        return json.loads(text)
    except (ValueError, json.JSONDecodeError):
        pass

    # 3. 截取首个 { 到最后一个 } 再解析
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return None
