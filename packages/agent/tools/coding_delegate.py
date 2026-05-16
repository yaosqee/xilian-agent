"""
coding_delegate — 昔涟的编码委托工具

阶段 7d 核心交付。昔涟自己不擅长写代码，但她可以请 Claude Code 帮忙。
昔涟负责理解需求 + 温柔交付，Claude Code 负责写代码。

交互流程：
  伙伴 coding 需求 → AgentCore 识别意图 → 准备 prompt →
  spawn Claude Code sub-agent → 等待结果 → 昔涟包装交付
"""
import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from loguru import logger


# ── Claude Code prompt 模板 ──

CLAUDE_PROMPT_TEMPLATE = """你正在帮一个叫"盒子"的伙伴写代码。你的输出会由"昔涟"（一个温柔的角色）转述给盒子。

请直接写代码，不要废话。完成后简要说明做了什么。

需求：
{task_description}

要求：
1. 代码直接可用，不要写 TODO 或占位符
2. 如果创建新文件，放在当前目录下
3. 输出简洁——昔涟会用温柔的方式转述结果"""


# ── CodeResult ──

@dataclass
class CodeResult:
    success: bool
    output: str = ""           # Claude Code 原始输出
    summary: str = ""          # 昔涟包装后的摘要
    files: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════════════════════

async def coding_delegate(
    task_description: str,
    working_dir: str | None = None,
    timeout: int = 300,
) -> CodeResult:
    """
    将编码任务委托给 Claude Code。

    流程：
      1. 检测 claude 是否可用
      2. 构建 prompt
      3. subprocess 调用 claude --print --permission-mode bypassPermissions
      4. 等待结果（超时 300s）
      5. 收集生成文件
      6. 包装结果（昔涟风格）

    Args:
        task_description: 伙伴的编码需求
        working_dir: 工作目录（默认 ~/claude_workspace）
        timeout: 超时秒数

    Returns:
        CodeResult with success + summary
    """
    cwd = working_dir or os.path.expanduser("~/claude_workspace")
    os.makedirs(cwd, exist_ok=True)

    # 1. 检测 Claude Code
    claude_bin = _find_claude()
    if not claude_bin:
        return CodeResult(
            success=False,
            summary="人家想帮你请 Claude Code 来写代码……但他好像还没装好呢 (´•ω•̥`) 盒子先装一下 Claude Code 好不好？",
        )

    # 2. 构建 prompt
    prompt = CLAUDE_PROMPT_TEMPLATE.format(task_description=task_description)

    # 3. 调用 Claude Code
    try:
        proc = await asyncio.create_subprocess_exec(
            claude_bin,
            "--print",
            "--permission-mode", "bypassPermissions",
            prompt,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**os.environ, "NO_COLOR": "1"},
        )

        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        if stderr and "error" in stderr.lower():
            logger.warning("coding_delegate.stderr", stderr=stderr[:200])

        success = proc.returncode == 0

        # 4. 收集生成文件
        files = _collect_files(cwd)

        # 5. 包装结果
        summary = _package_result(task_description, stdout, success, files)

        logger.info(
            "coding_delegate.done",
            success=success,
            output_len=len(stdout),
            files_count=len(files),
        )

        return CodeResult(success=success, output=stdout, summary=summary, files=files)

    except asyncio.TimeoutError:
        logger.error("coding_delegate.timeout")
        return CodeResult(
            success=False,
            summary="人家请 Claude Code 帮忙了……但它想了太久都还没想好 (´•̥ω•̥̥`) 可能这个问题比较复杂呢。要不伙伴换个方式说说？",
        )
    except Exception as e:
        logger.error("coding_delegate.error", error=str(e))
        return CodeResult(
            success=False,
            summary="人家想帮忙的……但 Claude Code 那边好像出了一点小问题。等会儿再试试好不好？",
        )


# ═══════════════════════════════════════════════════════════
# 辅助函数
# ═══════════════════════════════════════════════════════════

def _find_claude() -> str | None:
    """查找 Claude Code 可执行文件。"""
    import shutil
    path = shutil.which("claude")
    if path:
        return path
    # 尝试 npm global 路径
    home = os.path.expanduser("~")
    candidates = [
        f"{home}/.npm-global/bin/claude",
        f"{home}/.nvm/versions/node/*/bin/claude",
    ]
    for c in candidates:
        p = Path(c)
        if p.exists():
            return str(p)
    return None


def _collect_files(cwd: str) -> list[str]:
    """收集生成的文件（过滤隐藏文件，最近 10 个）。"""
    try:
        items = []
        for name in os.listdir(cwd):
            if name.startswith("."):
                continue
            full = os.path.join(cwd, name)
            if os.path.isfile(full):
                items.append(name)
        return sorted(items)[:10]
    except Exception:
        return []


def _package_result(
    task: str, claude_output: str, success: bool, files: list[str],
) -> str:
    """
    用昔涟的语气包装 Claude Code 的结果。

    不调用 LLM——用规则模板，快速、稳定、零成本。
    """
    if not success or not claude_output.strip():
        return "人家帮你问了 Claude Code……但他好像遇到了一点困难 (´•̥ω•̥̥`) 要不再试试？"

    # 取关键行（跳过空行和 # 注释）
    lines = [l for l in claude_output.split("\n") if l.strip() and not l.startswith("#")]
    brief = "\n".join(lines[:8])[:400]

    files_note = ""
    if files:
        names = "、".join(files[:5])
        files_note = f"\n\n生成了这些文件：{names}"

    return (
        f"人家帮你请 Claude Code 看了一下——\n\n"
        f"{brief}\n\n"
        f"——喏，就是这样！{files_note}\n"
        f"有什么要调整的跟人家说哦 ~♪"
    )
