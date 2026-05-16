"""
MarkerParser — LLM 输出标记解析器

阶段 7c 核心交付。从 LLM 流式输出中分离 literal（用户可见文本）
和 special（系统级标记）。支持跨 chunk 边界的标记解析。

标记语法（5 种）：
  [emotion:joy:0.8]  → 情感状态切换 → EmotionEngine
  [action:thinking]  → 动作/表情触发 → 前端动画
  [pause:1.5]        → TTS 停顿（阶段 9 转 SSML）
  [emph:重要]        → TTS 重读（阶段 9 转 SSML）
  [whisper:悄悄话]   → TTS 低语（阶段 9 转 SSML）

SSML 接口 markers_to_ssml() 已定义（空实现），为语音管道预留。
"""
import re
from dataclasses import dataclass, field
from typing import Iterator, Optional


# ═══════════════════════════════════════════════════════════
# 标记正则
# ═══════════════════════════════════════════════════════════

_MARKER_RE = re.compile(
    r'\[('
    r'emotion:[a-z_]+:[0-9.]+'      # [emotion:joy:0.8]
    r'|action:[a-z_]+'              # [action:thinking]
    r'|pause:[0-9.]+'               # [pause:1.5]
    r'|emph:[^\]]+'                 # [emph:重要]
    r'|whisper:[^\]]+'              # [whisper:悄悄话]
    r')\]'
)


# ═══════════════════════════════════════════════════════════
# 解析结果
# ═══════════════════════════════════════════════════════════

@dataclass
class ParsedToken:
    """解析后的 token"""
    kind: str                    # "literal" | "special"
    text: str                    # 文本内容（literal）或原始标记（special）
    marker_type: str = ""       # 仅 special: emotion/action/pause/emph/whisper
    payload: dict = field(default_factory=dict)  # 标记参数


# ═══════════════════════════════════════════════════════════
# MarkerParser
# ═══════════════════════════════════════════════════════════

@dataclass
class MarkerParser:
    """
    流式标记解析器。

    支持跨 chunk 边界的标记处理：
    - buffer 缓存未闭合的 [
    - feed(chunk) → 已解析 token 列表
    - flush() → 清空 buffer，返回剩余 literal

    用法：
        parser = MarkerParser()
        for chunk in llm_stream:
            tokens = parser.feed(chunk)
            for t in tokens:
                if t.kind == "literal":
                    yield_to_user(t.text)
                else:
                    dispatch_to_system(t)
        tokens = parser.flush()
        # 同上处理
    """

    _buffer: str = ""

    def feed(self, chunk: str) -> list[ParsedToken]:
        """
        喂入一个 chunk，返回解析出的 token 列表。

        算法（伪代码）：
          buffer += chunk
          while 扫描 buffer 中的 [:
              找到标记起始位置 bracket
              bracket 之前的文本 → literal token
              尝试用 MARKER_RE 匹配
              匹配成功 → special token, 跳过标记长度
              匹配失败 → [ 未闭合, 留在 buffer 等下一个 chunk
          剩余无标记文本 → literal token
        """
        self._buffer += chunk
        tokens: list[ParsedToken] = []
        pos = 0

        while pos < len(self._buffer):
            bracket = self._buffer.find('[', pos)
            if bracket == -1:
                # 无更多标记 → 剩余全为 literal
                if pos < len(self._buffer):
                    tokens.append(ParsedToken(
                        kind="literal", text=self._buffer[pos:]
                    ))
                    self._buffer = ""
                    return tokens
                break

            # 标记前的文本是 literal
            if bracket > pos:
                tokens.append(ParsedToken(
                    kind="literal", text=self._buffer[pos:bracket]
                ))

            # 尝试匹配标记
            match = _MARKER_RE.match(self._buffer, bracket)
            if match:
                raw = match.group(0)
                tokens.append(self._parse_marker(raw))
                pos = match.end()
            else:
                # [ 存在但未闭合 → 留在 buffer 等下一 chunk
                self._buffer = self._buffer[bracket:]
                return tokens

        self._buffer = ""
        return tokens

    def flush(self) -> list[ParsedToken]:
        """流结束时调用：清空 buffer，剩余内容全为 literal。"""
        if self._buffer:
            tokens = [ParsedToken(kind="literal", text=self._buffer)]
            self._buffer = ""
            return tokens
        return []

    # ── 标记解析 ──

    def _parse_marker(self, raw: str) -> ParsedToken:
        """解析单个标记字符串 → ParsedToken。"""
        inner = raw[1:-1]  # 去掉 []

        if inner.startswith("emotion:"):
            parts = inner.split(":")
            return ParsedToken(
                kind="special", text=raw, marker_type="emotion",
                payload={"emotion": parts[1], "intensity": float(parts[2])},
            )
        elif inner.startswith("action:"):
            return ParsedToken(
                kind="special", text=raw, marker_type="action",
                payload={"action": inner[7:]},
            )
        elif inner.startswith("pause:"):
            return ParsedToken(
                kind="special", text=raw, marker_type="pause",
                payload={"seconds": float(inner[6:])},
            )
        elif inner.startswith("emph:"):
            return ParsedToken(
                kind="special", text=raw, marker_type="emph",
                payload={"text": inner[5:]},
            )
        elif inner.startswith("whisper:"):
            return ParsedToken(
                kind="special", text=raw, marker_type="whisper",
                payload={"text": inner[8:]},
            )
        # 无法识别的 [xxx] 当作 literal
        return ParsedToken(kind="literal", text=raw)


# ═══════════════════════════════════════════════════════════
# SSML 转换接口（阶段 9 实现）
# ═══════════════════════════════════════════════════════════

def markers_to_ssml(
    tokens: list[ParsedToken],
    voice: str = "xilian",
) -> str:
    """
    将标记 token 流转换为 SSML。

    阶段 7c 仅定义接口签名，不实现。为语音管道预留清晰接入点。

    映射规则（阶段 9 实现）：
      [pause:Xs]   → <break time="Xs"/>
      [emph:text]  → <emphasis level="moderate">text</emphasis>
      [whisper:text] → <prosody volume="soft" rate="slow">text</prosody>

    Args:
        tokens: MarkerParser 解析出的 token 列表
        voice: 语音名称

    Returns:
        SSML 字符串（完整 <speak> 包裹）
    """
    # TODO(阶段 9): 实现完整 SSML 转换
    raise NotImplementedError("SSML generation — 阶段 9 实现")
