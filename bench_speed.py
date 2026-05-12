"""bench_speed.py — 云端模型延迟对比测试
用法: python bench_speed.py
"""
import asyncio
import time
import sys
import os

# 确保项目根目录在 path
sys.path.insert(0, os.path.dirname(__file__))

from packages.shared.model_router import ModelRouter

TEST_PROMPT = "请用一句话介绍你自己，不要超过30个字。"
ROUNDS = 3  # 每个模型跑几轮取平均


async def bench_one(name: str, call_fn, rounds: int = ROUNDS):
    """对单个模型跑 rounds 轮，返回耗时列表"""
    times = []
    print(f"\n{'='*50}", flush=True)
    print(f"  🎯 测试模型: {name}", flush=True)
    print(f"{'='*50}", flush=True)
    for i in range(rounds):
        start = time.perf_counter()
        try:
            result = await call_fn([
                {"role": "user", "content": TEST_PROMPT}
            ])
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            # 截断输出
            preview = result[:60].replace("\n", " ")
            print(f"  第{i+1}轮: {elapsed:.2f}s → {preview}...", flush=True)
        except Exception as e:
            elapsed = time.perf_counter() - start
            print(f"  第{i+1}轮: ❌ 失败 ({elapsed:.0f}s) — {e}", flush=True)
            times.append(None)
        if i < rounds - 1:
            await asyncio.sleep(0.5)  # 轮间短暂间隔
    return times


async def main():
    router = ModelRouter()

    print("╔══════════════════════════════════════════╗")
    print("║   🦋 昔涟 V3.2 — 云端模型延迟对比测试  ║")
    print("╠══════════════════════════════════════════╣")
    print(f"║  Prompt: {TEST_PROMPT}")
    print(f"║  每模型轮次: {ROUNDS}")
    print("╚══════════════════════════════════════════╝")

    # 先预热一下（排除冷启动）
    print("\n🔥 预热中...")
    try:
        await asyncio.wait_for(router._call_qwen([
            {"role": "user", "content": "hi"}
        ]), timeout=30)
        print("  Qwen 预热完成")
    except Exception as e:
        print(f"  Qwen 预热失败: {e}")

    try:
        await asyncio.wait_for(router._call_ds([
            {"role": "user", "content": "hi"}
        ]), timeout=30)
        print("  DeepSeek 预热完成")
    except Exception as e:
        print(f"  DeepSeek 预热失败: {e}")

    await asyncio.sleep(1)

    # 正式测试
    qwen_times = await bench_one("Qwen3.6-Plus (云端)", router._call_qwen)
    ds_times = await bench_one("DeepSeek-V4-Pro (云端)", router._call_ds)

    # 汇总
    print(f"\n{'='*50}")
    print("  📊 汇总对比")
    print(f"{'='*50}")

    for name, times in [("Qwen3.6-Plus", qwen_times), ("DeepSeek-V4-Pro", ds_times)]:
        valid = [t for t in times if t is not None]
        if valid:
            avg = sum(valid) / len(valid)
            mn, mx = min(valid), max(valid)
            print(f"  {name:20s}  平均 {avg:.2f}s  |  最快 {mn:.2f}s  |  最慢 {mx:.2f}s  |  ({len(valid)}/{len(times)} 成功)")
        else:
            print(f"  {name:20s}  ❌ 全部失败")

    # 胜负
    qv = [t for t in qwen_times if t is not None]
    dv = [t for t in ds_times if t is not None]
    if qv and dv:
        qavg = sum(qv) / len(qv)
        davg = sum(dv) / len(dv)
        faster = "Qwen3.6-Plus 🏆" if qavg < davg else "DeepSeek-V4-Pro 🏆"
        diff = abs(qavg - davg)
        pct = diff / max(qavg, davg) * 100
        print(f"\n  🏆 更快: {faster}")
        print(f"  ⏱️  差距: {diff:.2f}s ({pct:.0f}%)")

    print()


if __name__ == "__main__":
    asyncio.run(main())
