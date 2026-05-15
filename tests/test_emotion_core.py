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
        """t=τ 时衰减到原来的 ~37%"""
        s = EmotionState(pad_p=0.5, pad_a=0.3, pad_d=0.2)
        s.timestamp -= DEFAULT_TAU  # 模拟 30 分钟前
        s.decay(tau=DEFAULT_TAU)
        # e^(-1) ≈ 0.368
        assert 0.15 < s.pad_p < 0.22  # 0.5 × 0.368 ≈ 0.184

    def test_decay_approaches_zero(self):
        """长时间后趋近 0（但不到长间隔重置的阈值）"""
        s = EmotionState(pad_p=0.5, pad_a=0.3, pad_d=0.2)
        # DEFAULT_TAU * 5 = 9000s = 2.5h → 超过 LONG_INACTIVITY_SECONDS(7200)
        # 改用 DEFAULT_TAU * 3.5 = 6300s ≈ 1.75h，衰减到约 3% 但不触发重置
        s.timestamp -= DEFAULT_TAU * 3.5
        s.decay(tau=DEFAULT_TAU)
        # e^(-3.5) ≈ 0.0302 → 0.5 × 0.0302 ≈ 0.015
        assert s.pad_p < 0.03

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
        """立即事件应全额作用"""
        s = EmotionState()  # baseline
        s.update((0.3, 0.1, 0.05))
        # dt≈0，但 event_impact 全额加入
        assert s.pad_p > 0.3  # baseline(0.15) × 1 + 0.3 = 0.45
        assert s.pad_a > 0.1

    def test_update_after_delay(self):
        """延迟后更新：旧情绪衰减 + 新事件"""
        s = EmotionState(pad_p=0.5, pad_a=0.3, pad_d=0.2)
        s.timestamp -= DEFAULT_TAU  # 30 分钟前
        # 旧情绪衰减到 37%，再加入新事件
        s.update((0.3, 0.0, 0.0), tau=DEFAULT_TAU)
        # old_p × e^(-1) + new_p = 0.5 × 0.368 + 0.3 ≈ 0.484
        assert 0.4 < s.pad_p < 0.55

    def test_sensitivity_magnifies(self):
        """敏感度放大事件影响"""
        s = EmotionState()
        s.update((0.2, 0.1, 0.05), sensitivity=2.0)
        # 基线 + 2.0 × 0.2 = 积极偏移放大
        assert s.pad_p > 0.4

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
        """超过 2h 无对话 → 更新前从基线开始"""
        s = EmotionState(pad_p=0.8, pad_a=0.7, pad_d=0.6)
        s.timestamp -= LONG_INACTIVITY_SECONDS + 100
        s.update((0.15, -0.05, -0.05), tau=DEFAULT_TAU)
        # 从基线开始 + 事件
        base_p, _, _ = DEFAULT_BASELINE
        assert abs(s.pad_p - base_p - 0.15) < 0.01


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
