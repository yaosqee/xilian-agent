"""
EmotionEngine — PAD 三维情感引擎

阶段 4 核心交付。基于评价理论 (Scherer) 和 PAD 情感空间 (Mehrabian & Russell)。
情绪在 PAD 三维连续空间中平滑演化——有惯性、有过渡、受人格调制。

组件：
  · EmotionState     — PAD 坐标存储 + 衰减 + 11维映射
  · AppraisalExtractor — 评价变量提取（DS Flash）
  · PADMapper         — 评价变量 → PAD 坐标
  · PersonalityModulator — 人格调制 PAD 偏移
  · EmotionEngine     — 统一入口

PAD 参数参考：
  · Mehrabian, A. (1980). Basic dimensions for a general psychological theory.
  · Russell, J. A. (2003). Core affect and the psychological construction of emotion.
"""
import math
import time
import json
import asyncio
from dataclasses import dataclass, field
from typing import Optional


# ═══════════════════════════════════════════════════════════
# PAD 情绪参考中心（11 个基本情绪 × (P, A, D)）
# 来源：Mehrabian 1980, Russell 2003
# ═══════════════════════════════════════════════════════════

EMOTION_CENTERS: dict[str, tuple[float, float, float]] = {
    "快乐": ( 0.71,  0.48,  0.55),
    "悲伤": (-0.68, -0.25, -0.53),
    "愤怒": (-0.48,  0.59,  0.42),
    "恐惧": (-0.67,  0.50, -0.61),
    "惊讶": ( 0.26,  0.72, -0.06),
    "厌恶": (-0.58,  0.22,  0.21),
    "信任": ( 0.40, -0.39, -0.05),
    "期待": ( 0.20,  0.40,  0.11),
    "焦虑": (-0.52,  0.60, -0.42),
    "平静": ( 0.38, -0.70,  0.30),
    "兴奋": ( 0.52,  0.68,  0.40),
}

# σ 参数：控制 PAD→11维 映射的"模糊度"
# 值越小，情绪标签越集中（当前 PAD 点只匹配 1-2 个情绪）
# 值越大，混合情绪越多（更模糊）
PAD_SIGMA: float = 0.5


# ═══════════════════════════════════════════════════════════
# 情绪动力学默认参数
# ═══════════════════════════════════════════════════════════

DEFAULT_TAU = 1800.0          # 半衰期 30 分钟（秒）
DEFAULT_SENSITIVITY = 1.0      # 敏感度
DEFAULT_BASELINE = (0.15, 0.05, 0.1)  # 昔涟的基线心境：微正、平静、有掌控
DECAY_CLIP = 0.001             # 最低衰减因子
LONG_INACTIVITY_SECONDS = 7200  # > 2h 重置到基线


# ═══════════════════════════════════════════════════════════
# EmotionState — 核心情绪状态
# ═══════════════════════════════════════════════════════════

@dataclass
class EmotionState:
    """昔涟的当前情绪状态（PAD 三维坐标 + 元数据）"""

    pad_p: float = 0.15        # Pleasure，[-1, 1]
    pad_a: float = 0.05        # Arousal，[-1, 1]
    pad_d: float = 0.10        # Dominance，[-1, 1]
    timestamp: float = field(default_factory=time.time)

    # 缓存（按需计算）
    primary_emotion: Optional[str] = None
    primary_intensity: float = 0.0
    dimensions: Optional[dict[str, float]] = None

    # ── 属性 ──────────────────────────────────────────

    @property
    def pad(self) -> tuple[float, float, float]:
        return (self.pad_p, self.pad_a, self.pad_d)

    # ── 衰减 ──────────────────────────────────────────

    def decay(self, tau: float = DEFAULT_TAU) -> "EmotionState":
        """
        时间衰减：PAD → PAD × exp(-Δt/τ)

        无新事件时，情绪自然地回归基线。
        τ（半衰期）：无事件约 30min 后情绪衰减到一半强度。

        Returns:
            新的 EmotionState（原地修改当前，也返回引用）
        """
        now = time.time()
        dt = now - self.timestamp

        if dt <= 0:
            return self

        # 长间隔 → 直接重置基线
        if dt > LONG_INACTIVITY_SECONDS:
            self._reset_to_baseline(now)
            return self

        # 衰减因子
        decay_factor = math.exp(-dt / tau)
        decay_factor = max(decay_factor, DECAY_CLIP)

        # 衰减：向基线回归而非向零
        # PAD = PAD × e^(-Δt/τ) + baseline × (1 - e^(-Δt/τ))
        baseline_p, baseline_a, baseline_d = DEFAULT_BASELINE
        self.pad_p = self.pad_p * decay_factor + baseline_p * (1 - decay_factor)
        self.pad_a = self.pad_a * decay_factor + baseline_a * (1 - decay_factor)
        self.pad_d = self.pad_d * decay_factor + baseline_d * (1 - decay_factor)

        self.timestamp = now
        self._invalidate_cache()

        return self

    def _reset_to_baseline(self, now: float) -> None:
        """重置到昔涟的基线心境"""
        baseline_p, baseline_a, baseline_d = DEFAULT_BASELINE
        self.pad_p = baseline_p
        self.pad_a = baseline_a
        self.pad_d = baseline_d
        self.timestamp = now
        self._invalidate_cache()

    # ── 更新 ──────────────────────────────────────────

    def update(
        self,
        event_pad: tuple[float, float, float],
        sensitivity: float = DEFAULT_SENSITIVITY,
        tau: float = DEFAULT_TAU,
    ) -> "EmotionState":
        """
        情绪更新公式（核心）：

            PAD_new = PAD_old × e^(-Δt/τ)
                    + event_impact × (1 - e^(-Δt/τ))

        event_impact = event_pad × sensitivity

        直觉：旧情绪随时间衰减 → 基线，新事件占据「新信息」份额。
        dt→0 时 event 几乎不生效（短时间第一条消息还未被充分理解）；
        dt→∞ 时旧情绪清空，event 全额生效。

        Args:
            event_pad: 本次事件的 (P, A, D) 偏移量
            sensitivity: 人格敏感度（>1 更敏感，<1 更钝感）
            tau: 衰减半衰期参数

        Returns:
            更新后的 self
        """
        # 1. 计算时间衰减
        now = time.time()
        dt = now - self.timestamp
        if dt > LONG_INACTIVITY_SECONDS:
            # 太久没对话 → 从基线重新开始，decay_factor=0 表示旧情绪完全释放
            baseline_p, baseline_a, baseline_d = DEFAULT_BASELINE
            old_p = baseline_p
            old_a = baseline_a
            old_d = baseline_d
            decay_factor = 0.0
        else:
            old_p = self.pad_p
            old_a = self.pad_a
            old_d = self.pad_d
            decay_factor = math.exp(-dt / tau)
            decay_factor = max(decay_factor, DECAY_CLIP)

        # 2. 事件冲击（人格调制）
        ep, ea, ed = event_pad
        impact_p = ep * sensitivity
        impact_a = ea * sensitivity
        impact_d = ed * sensitivity

        # 3. 核心公式
        #    PAD_new = old × decay + impact × (1 - decay)
        #    旧情绪随时间衰减，新事件按「新信息」比例加入
        self.pad_p = old_p * decay_factor + impact_p * (1 - decay_factor)
        self.pad_a = old_a * decay_factor + impact_a * (1 - decay_factor)
        self.pad_d = old_d * decay_factor + impact_d * (1 - decay_factor)

        # 4. clamp [-1, 1]，但保留一点余量防止锁死
        self.pad_p = max(-0.95, min(0.95, self.pad_p))
        self.pad_a = max(-0.95, min(0.95, self.pad_a))
        self.pad_d = max(-0.95, min(0.95, self.pad_d))

        self.timestamp = now
        self._invalidate_cache()

        return self

    def set_pad(self, p: float, a: float, d: float) -> "EmotionState":
        """手动设置 PAD（调试/重置用）"""
        self.pad_p = p
        self.pad_a = a
        self.pad_d = d
        self.timestamp = time.time()
        self._invalidate_cache()
        return self

    # ── PAD → 11维映射 ────────────────────────────────

    def compute_profile(self) -> dict:
        """
        PAD → 11 维情绪强度 + primary_emotion。

        方法：高斯核距离 → 相似度 → 归一化。

        Returns:
            {
                "primary_emotion": str,
                "primary_intensity": float,
                "dimensions": {emotion_name: float, ...},  # 11 维，0-1
            }
        """
        # Euclidean distances to 11 centers
        distances = {}
        for name, (cp, ca, cd) in EMOTION_CENTERS.items():
            dist = math.sqrt(
                (self.pad_p - cp) ** 2
                + (self.pad_a - ca) ** 2
                + (self.pad_d - cd) ** 2
            )
            distances[name] = dist

        # 高斯核：越近强度越高，原始值即为可信度
        sigma2 = 2 * PAD_SIGMA ** 2
        intensities = {
            name: math.exp(-dist ** 2 / sigma2)
            for name, dist in distances.items()
        }

        # 最近的是主情绪
        primary = min(distances, key=distances.get)
        primary_intensity = intensities[primary]

        # 最低强度门槛：微弱信号 → 降级为「平静」，避免基线误判为「期待」
        # 基线 (0.15,0.05,0.10) → 期待 intensity=0.78，远超阈值，需要特殊处理
        # 改用距离阈值：距基线越近越倾向「平静」
        base_p, base_a, base_d = DEFAULT_BASELINE
        dist_from_baseline = math.sqrt(
            (self.pad_p - base_p) ** 2
            + (self.pad_a - base_a) ** 2
            + (self.pad_d - base_d) ** 2
        )
        MIN_DEVIATION = 0.25  # PAD 偏离基线超过此值才算有效情绪
        if dist_from_baseline < MIN_DEVIATION and primary_intensity < 0.85:
            primary = "平静"
            primary_intensity = intensities.get("平静", 0.3)

        # 归一化到 [0,1] 用于前端展示（保持相对关系），
        # 但 primary_intensity 保留原始高斯值（真实可信度）
        max_intensity = max(intensities.values()) or 1.0
        display_intensities = {k: v / max_intensity for k, v in intensities.items()}

        self.primary_emotion = primary
        self.primary_intensity = primary_intensity
        self.dimensions = display_intensities

        return {
            "primary_emotion": primary,
            "primary_intensity": self.primary_intensity,
            "dimensions": display_intensities,
        }

    # ── 轨迹 ──────────────────────────────────────────

    def distance_to(self, other: "EmotionState") -> float:
        """到另一个状态的 PAD 欧氏距离"""
        return math.sqrt(
            (self.pad_p - other.pad_p) ** 2
            + (self.pad_a - other.pad_a) ** 2
            + (self.pad_d - other.pad_d) ** 2
        )

    # ── 序列化 ────────────────────────────────────────

    def to_dict(self) -> dict:
        """序列化为 API 响应格式"""
        return {
            "pad": {"P": round(self.pad_p, 4), "A": round(self.pad_a, 4), "D": round(self.pad_d, 4)},
            "primary_emotion": self.primary_emotion,
            "primary_intensity": round(self.primary_intensity, 4),
            "dimensions": {k: round(v, 4) for k, v in (self.dimensions or {}).items()},
            "timestamp": self.timestamp,
        }

    # ── 内部 ──────────────────────────────────────────

    def _invalidate_cache(self) -> None:
        """清除计算缓存"""
        self.primary_emotion = None
        self.primary_intensity = 0.0
        self.dimensions = None


# ═══════════════════════════════════════════════════════════
# PersonalityModulator — 人格调制器
# ═══════════════════════════════════════════════════════════

@dataclass
class PersonalityModulator:
    """
    昔涟的人格调制 PAD 偏移。

    参数来源：昔涟人格设定"温柔、敏感但不脆弱"的数值化表达。
    """

    empathy_weight: float = 0.85       # 高共情 → 伙伴情绪容易影响她
    resilience: float = 0.6            # 韧性中等 → 不过度波动
    positivity_bias: float = 0.15      # 轻微正偏 → 消极恢复快于积极
    arousal_dampen: float = 0.8        # 唤醒阻尼 → 不那么容易激动

    def modulate(self, raw_pad: tuple[float, float, float]) -> tuple[float, float, float]:
        """
        对原始 PAD 偏移进行人格调制。

        Args:
            raw_pad: 评价映射的原始 (P, A, D)

        Returns:
            调制后的 (P, A, D)
        """
        p, a, d = raw_pad

        # 共情调制 Arousal（伙伴兴奋她也兴奋，但不过度）
        a *= self.empathy_weight * self.arousal_dampen

        # 韧性调制：极端情绪被 tanh 压缩（不跳变）
        p = math.tanh(p / self.resilience) * self.resilience

        # 正偏：消极恢复快，积极维持久
        if p < 0:
            p *= (1 - self.positivity_bias)  # 消极冲击打 85 折
        else:
            p *= (1 + self.positivity_bias)  # 积极事件放大 15%

        # Dominance 也受韧性调制
        d = math.tanh(d / self.resilience) * self.resilience

        return (p, a, d)


# ═══════════════════════════════════════════════════════════
# AppraisalExtractor — 评价变量提取（DS Flash）
# ═══════════════════════════════════════════════════════════

APPRAISAL_SYSTEM_PROMPT = """你是昔涟。分析伙伴的消息，从昔涟的视角感知伙伴的内心状态。

返回 JSON（只返回这个，不要其他文字）：
{
  "relevance": 0.0-1.0,
  "facilitation": -1.0-1.0,
  "coping": -1.0-1.0,
  "reason": "一句话解释为什么这样评价"
}

字段含义：
- relevance: 这件事对伙伴有多重要？（0=无关紧要，1=极其重要）
- facilitation: 对伙伴的目标是促进还是阻碍？（正=促进/好消息，负=阻碍/坏消息）
- coping: 伙伴感到能应对这件事吗？（正=掌控感强/能处理，负=无力/失控）
- reason: 简明解释你的评价逻辑

昔涟的感知风格：
- 敏感但不越界：能看到情绪，但不替伙伴下结论
- 理解语境：考虑当前时间、之前的对话
- 温和准确：把强烈情绪用柔软但准确的语言描述
- 能从简单的词句里感知到伙伴没说出来的情绪波动"""

# 关键词 → 启发式规则（Flash 不可用时的降级方案）
_POSITIVE_KEYWORDS = {
    "开心", "高兴", "快乐", "哈哈", "太好", "棒", "成功", "通过", "及格",
    "喜欢", "爱", "谢谢", "感谢", "感动", "温暖", "期待", "兴奋",
    "完成", "搞定", "买了", "收到", "放假", "休息", "玩",
}
_NEGATIVE_KEYWORDS = {
    "难过", "伤心", "哭", "累", "疲惫", "困", "烦", "焦虑", "紧张",
    "害怕", "恐惧", "恐怖", "吓人", "吓", "诡异", "血腥", "担心",
    "生气", "愤怒", "讨厌", "失望", "失败", "挂了", "痛苦", "窒息",
    "加班", "熬夜", "压力", "崩溃", "不要", "算了", "唉", "哎",
    "绝望", "无助", "孤独", "寂寞", "空虚", "迷茫", "后悔", "愧疚",
}
_COPING_KEYWORDS = {
    "没问题", "我能", "可以", "搞定", "简单", "小事", "没事", "随便",
    "尽全力", "加油", "冲", "算了", "随便吧", "没办法", "不知道",
    "不会", "不太行", "好难", "不会弄", "放弃了",
}


@dataclass
class AppraisalResult:
    """评价提取结果"""
    relevance: float      # 0-1
    facilitation: float   # -1 to +1
    coping: float         # -1 to +1
    reason: str = ""
    source: str = "llm"   # "llm" | "heuristic"

    @classmethod
    def neutral(cls) -> "AppraisalResult":
        """中性评价（降级/空消息）"""
        return cls(0.5, 0.0, 0.0, "无法感知", source="heuristic")


class AppraisalExtractor:
    """
    评价变量提取器。

    主路径：DS V4-Flash（异步，不阻塞回复）
    降级路径：关键词启发式（Flash 不可用时）
    """

    def __init__(self, model_router):
        self._router = model_router

    async def extract(self, user_message: str) -> AppraisalResult:
        """
        从用户消息中提取评价变量。

        Args:
            user_message: 用户原始消息文本

        Returns:
            AppraisalResult
        """
        if not user_message or not user_message.strip():
            return AppraisalResult.neutral()

        # 尝试 LLM 评价
        if self._router:
            try:
                return await self._extract_llm(user_message)
            except Exception as e:
                from loguru import logger
                logger.debug("appraisal.llm_failed_fallback_to_heuristic", error=str(e))

        # 降级到启发式
        return self._extract_heuristic(user_message)

    async def _extract_llm(self, user_message: str) -> AppraisalResult:
        """DS Flash 评价提取"""
        messages = [
            {"role": "system", "content": APPRAISAL_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

        raw = await self._router.route(
            "emotion_analysis",  # 走 Flash（路由表中 emotion_analysis → Flash）
            messages,
            temperature=0.3,  # 低温度保证稳定输出
        )

        # 解析 JSON
        result = self._parse_response(raw)
        if result is None:
            return self._extract_heuristic(user_message)

        result.source = "llm"
        return result

    def _parse_response(self, raw: str) -> Optional[AppraisalResult]:
        """解析 LLM 返回的 JSON"""
        try:
            # 尝试直接解析
            data = json.loads(raw)
        except json.JSONDecodeError:
            # 尝试提取 ```json ... ``` 代码块
            try:
                start = raw.index("{")
                end = raw.rindex("}") + 1
                data = json.loads(raw[start:end])
            except (ValueError, json.JSONDecodeError):
                return None

        rel = data.get("relevance", 0.5)
        fac = data.get("facilitation", 0.0)
        cop = data.get("coping", 0.0)

        # 边界校验
        rel = max(0.0, min(1.0, float(rel)))
        fac = max(-1.0, min(1.0, float(fac)))
        cop = max(-1.0, min(1.0, float(cop)))

        return AppraisalResult(
            relevance=rel,
            facilitation=fac,
            coping=cop,
            reason=data.get("reason", ""),
        )

    def _extract_heuristic(self, text: str) -> AppraisalResult:
        """关键词启发式评价（降级方案）"""
        if not text or not text.strip():
            return AppraisalResult.neutral()

        # relevance：消息长度代理 + 情感词密度
        words = text.strip()
        word_count = len(words)
        relevance = min(word_count / 50.0, 1.0)  # 50字以上视为高相关

        # 检查关键词
        pos_hits = sum(1 for kw in _POSITIVE_KEYWORDS if kw in text)
        neg_hits = sum(1 for kw in _NEGATIVE_KEYWORDS if kw in text)

        # facilitation
        if pos_hits > neg_hits:
            facilitation = min(0.3 + pos_hits * 0.15, 1.0)
        elif neg_hits > pos_hits:
            facilitation = max(-0.3 - neg_hits * 0.15, -1.0)
        else:
            facilitation = 0.0

        # coping
        coping_pos = sum(1 for kw in ["没问题", "我能", "可以", "搞定", "小事"] if kw in text)
        coping_neg = sum(1 for kw in ["没办法", "不知道", "不会", "好难", "放弃了"] if kw in text)
        if coping_pos > coping_neg:
            coping = min(0.3 + coping_pos * 0.15, 1.0)
        elif coping_neg > coping_pos:
            coping = max(-0.3 - coping_neg * 0.15, -1.0)
        else:
            coping = 0.0

        return AppraisalResult(
            relevance=relevance,
            facilitation=facilitation,
            coping=coping,
            reason=f"启发式（关键词匹配）: pos={pos_hits}, neg={neg_hits}",
            source="heuristic",
        )


# ═══════════════════════════════════════════════════════════
# PADMapper — 评价变量 → PAD 坐标
# ═══════════════════════════════════════════════════════════

class PADMapper:
    """
    评价变量 → PAD 三维坐标映射。

    公式来源：Scherer 评价理论简化版。

        P (愉悦度) = facilitation × 0.7 + coping × 0.3
        A (唤醒度) = relevance × (|facilitation| + |coping|) / 2
        D (支配度) = coping × 0.8
    """

    # 映射权重
    P_FACILITATION_WEIGHT = 0.7
    P_COPING_WEIGHT = 0.3
    A_RELEVANCE_WEIGHT = 1.0
    D_COPING_WEIGHT = 0.8

    @classmethod
    def map_to_pad(cls, appraisal: AppraisalResult) -> tuple[float, float, float]:
        """
        Appraisal → PAD 坐标。

        Args:
            appraisal: AppraisalResult

        Returns:
            (P, A, D) tuple
        """
        r = appraisal.relevance
        f = appraisal.facilitation
        c = appraisal.coping

        # P (愉悦度)：促进 + 应对 → 愉快
        p = f * cls.P_FACILITATION_WEIGHT + c * cls.P_COPING_WEIGHT

        # A (唤醒度)：重要性 × 情绪两极程度 → 唤醒
        a = r * (abs(f) + abs(c)) / 2 * cls.A_RELEVANCE_WEIGHT

        # D (支配度)：应对能力 → 掌控感
        d = c * cls.D_COPING_WEIGHT

        return (p, a, d)

    @classmethod
    def map_to_pad_with_modulation(
        cls,
        appraisal: AppraisalResult,
        modulator: PersonalityModulator,
    ) -> tuple[float, float, float]:
        """
        Appraisal → PAD（含人格调制）。

        对外推荐使用此方法：先映射再调制。
        """
        raw_pad = cls.map_to_pad(appraisal)
        return modulator.modulate(raw_pad)


# ═══════════════════════════════════════════════════════════
# EmotionEngine — 统一入口（占位，Week 3 集成时填充）
# ═══════════════════════════════════════════════════════════

class EmotionEngine:
    """
    情感引擎统一入口。

    组合：EmotionState + AppraisalExtractor + PADMapper + PersonalityModulator。
    Week 3 集成 AgentCore 时完整实现。
    """

    def __init__(
        self,
        model_router=None,
        tau: float = DEFAULT_TAU,
        sensitivity: float = DEFAULT_SENSITIVITY,
    ):
        self.state = EmotionState()
        # 时间戳置为 0 确保首条消息的 decay_factor≈0，事件全额生效
        self.state.timestamp = 0.0
        self.appraisal_extractor = AppraisalExtractor(model_router)
        self.modulator = PersonalityModulator()
        self.tau = tau
        self.sensitivity = sensitivity

    async def process_message(self, user_message: str) -> dict:
        """
        处理一条用户消息 → 更新情绪状态。

        Args:
            user_message: 用户消息文本

        Returns:
            当前情绪 profile（11 维 + primary_emotion）
        """
        # 1. 提取评价
        appraisal = await self.appraisal_extractor.extract(user_message)

        # 2. 评价 → PAD（含人格调制）
        event_pad = PADMapper.map_to_pad_with_modulation(appraisal, self.modulator)

        # 3. 更新情绪状态
        self.state.update(event_pad, sensitivity=self.sensitivity, tau=self.tau)

        # 4. 计算 profile
        profile = self.state.compute_profile()
        profile["appraisal"] = {
            "relevance": appraisal.relevance,
            "facilitation": appraisal.facilitation,
            "coping": appraisal.coping,
            "reason": appraisal.reason,
            "source": appraisal.source,
        }

        return profile

    def get_profile(self) -> dict:
        """获取当前情绪快照（不触发更新）"""
        return self.state.compute_profile()
