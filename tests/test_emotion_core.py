"""测试 EmotionState + PersonalityModulator 核心算法

2026-05-15：阶段 4 第一周测试——纯算法，不涉及 LLM
"""
import math
import pytest
from packages.agent.emotion_core import (
    EmotionState,
    PersonalityModulator,
    EMOTION_CENTERS,
    DEFAULT_BASELINE,
    DEFAULT_TAU,
    LONG_INACTIVITY_SECONDS,
)


# ═══════════════════════════════════════════════════════
# EmotionState 基础
# ═══════════════════════════════════════════════════════

class TestEmotionStateInit:
    """初始化测试"""

    def test_default_baseline(self):
        s = EmotionState()
        assert s.pad == DEFAULT_BASELINE

    def test_custom_pad(self):
        s = EmotionState(pad_p=0.5, pad_a=0.3, pad_d=0.2)
        assert s.pad == (0.5, 0.3, 0.2)

    def test_initial_cache_empty(self):
        s = EmotionState()
        assert s.primary_emotion is None
        assert s.dimensions is None


class TestPADTo11D:
    """PAD → 11 维映射"""

    def test_baseline_profile(self):
        s = EmotionState()
        prof = s.compute_profile()
        assert "primary_emotion" in prof
        assert "dimensions" in prof
        assert len(prof["dimensions"]) == 11
        assert all(0 <= v <= 1 for v in prof["dimensions"].values())

    def test_joy_center(self):
        """在快乐中心点上 → 快乐应该是主情绪"""
        s = EmotionState(pad_p=0.71, pad_a=0.48, pad_d=0.55)
        prof = s.compute_profile()
        assert prof["primary_emotion"] == "快乐"
        assert prof["primary_intensity"] > 0.9

    def test_sadness_center(self):
        s = EmotionState(pad_p=-0.68, pad_a=-0.25, pad_d=-0.53)
        prof = s.compute_profile()
        assert prof["primary_emotion"] == "悲伤"
        assert prof["primary_intensity"] > 0.9

    def test_distance_based_ordering(self):
        """越近的情绪强度越高"""
        s = EmotionState(pad_p=0.5, pad_a=0.4, pad_d=0.3)
        prof = s.compute_profile()
        # 快乐中心 (0.71, 0.48, 0.55) 应该排最高
        dims = prof["dimensions"]
        assert dims["快乐"] > dims["悲伤"]
        assert dims["快乐"] > dims["焦虑"]

    def test_all_11_dimensions_present(self):
        s = EmotionState()
        prof = s.compute_profile()
        names = set(prof["dimensions"].keys())
        assert names == set(EMOTION_CENTERS.keys())


# ═══════════════════════════════════════════════════════
# 时间衰减
# ═══════════════════════════════════════════════════════

class TestDecay:
    """惯性衰减测试"""

    def test_zero_dt_no_decay(self):
        """dt=0 时不应衰减"""
        s = EmotionState(pad_p=0.5, pad_a=0.3, pad_d=0.2)
        # timestamp 刚设置，decay 立刻调用 → dt≈0
        s.decay(tau=1800)
        assert abs(s.pad_p - 0.5) < 0.01

    def test_half_life_decay(self):
        """t=τ 时衰减到原来的 ~37%，同时拉向基线 ~63%"""
        s = EmotionState(pad_p=0.5, pad_a=0.3, pad_d=0.2)
        s.timestamp -= DEFAULT_TAU  # 模拟 30 分钟前
        s.decay(tau=DEFAULT_TAU)
        # e^(-1) ≈ 0.368
        # 新公式: pad = old * 0.368 + baseline * 0.632
        # pad_p = 0.5 * 0.368 + 0.15 * 0.632 = 0.184 + 0.095 = 0.279
        assert 0.25 < s.pad_p < 0.31

    def test_decay_approaches_baseline(self):
        """长时间后趋近基线而非零（不到长间隔重置阈值）"""
        s = EmotionState(pad_p=0.5, pad_a=0.3, pad_d=0.2)
        s.timestamp -= DEFAULT_TAU * 3.5  # 1.75h，不触发重置
        s.decay(tau=DEFAULT_TAU)
        # e^(-3.5) ≈ 0.0302
        # pad_p = 0.5 * 0.0302 + 0.15 * 0.9698 = 0.0151 + 0.1455 = 0.1606
        assert 0.13 < s.pad_p < 0.19  # 趋近基线 0.15

    def test_long_inactivity_reset(self):
        """> 2h 无对话 → 重置基线"""
        s = EmotionState(pad_p=0.8, pad_a=0.7, pad_d=0.6)
        s.timestamp -= LONG_INACTIVITY_SECONDS + 1
        s.decay()
        assert s.pad == DEFAULT_BASELINE


# ═══════════════════════════════════════════════════════
# 情绪更新
# ═══════════════════════════════════════════════════════

class TestEmotionUpdate:
    """PAD 更新核心公式"""

    def test_immediate_event_impact(self):
        """立即事件（dt≈0）：v2 公式中 event_weight 独立于 dt，事件有固定 40% 权重"""
        s = EmotionState()  # baseline, timestamp=now
        s.update((0.3, 0.1, 0.05))
        # dt≈0 → decay≈1.0, ew=0.4 → P = 0.15×0.6 + 0.15×0.0 + 0.3×0.4 = 0.21
        assert abs(s.pad_p - 0.21) < 0.05
        assert abs(s.pad_a - 0.07) < 0.05
        assert abs(s.pad_d - 0.08) < 0.05

    def test_update_after_delay(self):
        """延迟后更新：衰减+基线回归 + 新事件按权重混合"""
        s = EmotionState(pad_p=0.5, pad_a=0.3, pad_d=0.2)
        s.timestamp -= DEFAULT_TAU  # 30 分钟前 → decay = e^(-1) ≈ 0.368
        s.update((0.3, 0.0, 0.0), tau=DEFAULT_TAU)
        # v2: P = 0.5×0.368×0.6 + 0.15×0.632×0.6 + 0.3×0.4 = 0.110+0.057+0.120=0.287
        assert 0.23 < s.pad_p < 0.35

    def test_sensitivity_magnifies(self):
        """敏感度放大事件影响 — 时间戳设为过去使 decay≈0，impact 全额生效"""
        s = EmotionState()
        s.timestamp = 0.0  # 很久以前 → decay_factor≈0 → impact 全额
        s.update((0.2, 0.1, 0.05), sensitivity=2.0)
        # pad_p = 0.15 * 0 + (0.2 × 2.0) * 1.0 = 0.4
        assert 0.35 < s.pad_p < 0.60

    def test_sensitivity_dampens(self):
        """低敏感度减弱影响"""
        s = EmotionState()
        s.update((0.5, 0.5, 0.3), sensitivity=0.3)
        assert s.pad_p < 0.3  # 被阻尼

    def test_multiple_events_accumulate(self):
        """连续事件情绪累积"""
        s = EmotionState()
        s.update((0.2, 0.1, 0.05))
        p1 = s.pad_p
        s.timestamp -= 3  # 模拟 3 秒后
        s.update((0.2, 0.1, 0.05))
        assert s.pad_p > p1  # 累积

    def test_clamp_range(self):
        """PAD clamp 在 [-0.95, 0.95]"""
        s = EmotionState()
        s.update((2.0, 2.0, 2.0), sensitivity=2.0)
        assert -1 <= s.pad_p <= 1
        assert -1 <= s.pad_a <= 1
        assert -1 <= s.pad_d <= 1

    def test_long_inactivity_before_update(self):
        """超过 2h 无对话 → decay_factor=0，事件全额作用，基线不参与"""
        s = EmotionState(pad_p=0.8, pad_a=0.7, pad_d=0.6)
        s.timestamp -= LONG_INACTIVITY_SECONDS + 100
        s.update((0.15, -0.05, -0.05), tau=DEFAULT_TAU)
        # decay_factor=0: pad_p = baseline * 0 + 0.15 * 1.0 = 0.15
        assert abs(s.pad_p - 0.15) < 0.01


# ═══════════════════════════════════════════════════════
# PersonalityModulator
# ═══════════════════════════════════════════════════════

class TestPersonalityModulator:
    """人格调制器"""

    def test_modulate_reduces_arousal(self):
        mod = PersonalityModulator(empathy_weight=0.85, arousal_dampen=0.8)
        # 原始 A=0.5 → 0.5 × 0.85 × 0.8 = 0.34
        _, a, _ = mod.modulate((0.0, 0.5, 0.0))
        assert a < 0.5

    def test_positivity_bias(self):
        mod = PersonalityModulator(positivity_bias=0.15)
        # 消极事件打折扣
        p_neg, _, _ = mod.modulate((-0.5, 0.0, 0.0))
        # 积极事件放大
        p_pos, _, _ = mod.modulate((0.5, 0.0, 0.0))

        assert abs(p_neg) < abs(p_pos)  # 消极冲击 < 积极冲击

    def test_resilience_compresses_extremes(self):
        """韧性调制压缩极端情绪"""
        mod = PersonalityModulator(resilience=0.6)
        p, _, _ = mod.modulate((0.9, 0.0, 0.0))
        assert p < 0.9  # 极端值被压缩

    def test_modulate_preserves_zero(self):
        """零输入 → 零输出"""
        mod = PersonalityModulator()
        result = mod.modulate((0.0, 0.0, 0.0))
        assert result == (0.0, 0.0, 0.0)


# ═══════════════════════════════════════════════════════
# EmotionState 辅助方法
# ═══════════════════════════════════════════════════════

class TestEmotionStateHelpers:

    def test_distance_to_self_is_zero(self):
        s = EmotionState()
        assert s.distance_to(s) == 0.0

    def test_distance_symmetric(self):
        a = EmotionState(pad_p=0.5, pad_a=0.3, pad_d=0.2)
        b = EmotionState(pad_p=-0.3, pad_a=0.1, pad_d=-0.4)
        assert a.distance_to(b) == b.distance_to(a)

    def test_set_pad(self):
        s = EmotionState()
        s.set_pad(0.6, 0.4, 0.3)
        assert s.pad == (0.6, 0.4, 0.3)

    def test_to_dict(self):
        s = EmotionState()
        s.compute_profile()
        d = s.to_dict()
        assert "pad" in d
        assert "primary_emotion" in d
        assert "dimensions" in d
        assert len(d["dimensions"]) == 11


# ═══════════════════════════════════════════════════════
# 边界情况
# ═══════════════════════════════════════════════════════

class TestEdgeCases:

    def test_emotion_center_data_integrity(self):
        """验证 11 个情绪参考中心数据完整性"""
        assert len(EMOTION_CENTERS) == 11
        for name, (p, a, d) in EMOTION_CENTERS.items():
            assert -1 <= p <= 1, f"{name} P 越界: {p}"
            assert -1 <= a <= 1, f"{name} A 越界: {a}"
            assert -1 <= d <= 1, f"{name} D 越界: {d}"

    def test_pad_clamp_never_locked(self):
        """clamp 后不应相等（防止锁死）"""
        s = EmotionState(pad_p=0.95, pad_a=0.95, pad_d=0.95)
        s.update((0.1, 0.1, 0.1))  # 已经在边界上，再加
        # 不应超过 clamp 边界
        assert s.pad_p <= 0.95
        assert s.pad_a <= 0.95

    def test_negative_pad_works(self):
        """负 PAD 值正确处理"""
        s = EmotionState(pad_p=-0.3, pad_a=-0.1, pad_d=-0.2)
        s.update((-0.3, 0.2, -0.2))
        prof = s.compute_profile()
        # 应该是偏消极的情绪
        assert prof["dimensions"]["悲伤"] > 0.1 or prof["dimensions"]["焦虑"] > 0.1
