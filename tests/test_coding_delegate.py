"""
coding_delegate 单元测试 — 阶段 7d + 打磨期补全

覆盖：Claude Code 查找 · 结果包装 · 超时 · 错误处理 · 文件收集 · prompt 构建
"""
import sys
sys.path.insert(0, ".")

import os
import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock

from packages.agent.tools.coding_delegate import (
    coding_delegate,
    CodeResult,
    CLAUDE_PROMPT_TEMPLATE,
    _find_claude,
    _collect_files,
    _package_result,
)


# ═══════════════════════════════════════════════════════════
# CodeResult dataclass
# ═══════════════════════════════════════════════════════════

class TestCodeResult:
    def test_success_defaults(self):
        cr = CodeResult(success=True)
        assert cr.success is True
        assert cr.output == ""
        assert cr.summary == ""
        assert cr.files == []

    def test_failure_with_summary(self):
        cr = CodeResult(success=False, summary="出了点问题")
        assert cr.success is False
        assert "问题" in cr.summary

    def test_with_files(self):
        cr = CodeResult(success=True, files=["main.py", "utils.py"])
        assert len(cr.files) == 2


# ═══════════════════════════════════════════════════════════
# _find_claude
# ═══════════════════════════════════════════════════════════

class TestFindClaude:
    def test_finds_via_which(self):
        with patch("shutil.which", return_value="/usr/bin/claude"):
            result = _find_claude()
            assert result == "/usr/bin/claude"

    def test_not_found(self):
        with patch("shutil.which", return_value=None):
            with patch("pathlib.Path.exists", return_value=False):
                result = _find_claude()
                assert result is None

    # not testing npm-global path — it requires filesystem state


# ═══════════════════════════════════════════════════════════
# _collect_files
# ═══════════════════════════════════════════════════════════

class TestCollectFiles:
    def test_collects_files_ignores_hidden(self, tmp_path):
        (tmp_path / "main.py").write_text("code")
        (tmp_path / ".hidden").write_text("secret")
        (tmp_path / "subdir").mkdir()
        files = _collect_files(str(tmp_path))
        assert "main.py" in files
        assert ".hidden" not in files

    def test_empty_dir(self, tmp_path):
        files = _collect_files(str(tmp_path))
        assert files == []

    def test_nonexistent_dir(self):
        files = _collect_files("/nonexistent/path")
        assert files == []

    def test_sorts_alphabetically(self, tmp_path):
        (tmp_path / "zebra.py").write_text("z")
        (tmp_path / "alpha.py").write_text("a")
        files = _collect_files(str(tmp_path))
        assert files[0] == "alpha.py"
        assert files[-1] == "zebra.py"


# ═══════════════════════════════════════════════════════════
# _package_result
# ═══════════════════════════════════════════════════════════

class TestPackageResult:
    def test_success_with_files(self):
        output = "# 生成文件\nprint('hello')\n# 注释\nprint('world')"
        files = ["main.py", "util.py"]
        result = _package_result("创建新项目", output, True, files)
        assert "main.py" in result
        assert "util.py" in result
        assert "print" in result
        assert "Claude Code" in result
        assert "~♪" in result
        assert "#" not in result  # 注释被过滤

    def test_success_no_files(self):
        result = _package_result("修复bug", "done", True, [])
        assert "生成了这些文件" not in result

    def test_failure_output(self):
        result = _package_result("", "", False, [])
        assert "困难" in result or "麻烦" in result

    def test_truncates_long_output(self):
        long_output = "line\n" * 100
        result = _package_result("task", long_output, True, [])
        assert len(result) < 1000  # 应该被截断

    def test_files_capped_at_5(self):
        files = ["a.py", "b.py", "c.py", "d.py", "e.py", "f.py"]
        result = _package_result("task", "done", True, files)
        # 只展示前 5 个
        assert "f.py" not in result


# ═══════════════════════════════════════════════════════════
# CLAUDE_PROMPT_TEMPLATE
# ═══════════════════════════════════════════════════════════

class TestPromptTemplate:
    def test_task_description_injected(self):
        prompt = CLAUDE_PROMPT_TEMPLATE.format(task_description="创建一个 FastAPI 端点")
        assert "FastAPI" in prompt
        assert "盒子" in prompt
        assert "昔涟" in prompt
        assert "TODO" in prompt

    def test_output_requirements(self):
        prompt = CLAUDE_PROMPT_TEMPLATE.format(task_description="finish the code")
        assert "直接可用" in prompt
        assert "不要写 TODO" in prompt


# ═══════════════════════════════════════════════════════════
# coding_delegate 主函数
# ═══════════════════════════════════════════════════════════

class TestCodingDelegate:
    @pytest.fixture
    def mock_subprocess(self):
        proc = AsyncMock()
        proc.communicate.return_value = (b"Generated code", b"")
        proc.returncode = 0
        return proc

    @pytest.mark.asyncio
    async def test_claude_not_found(self):
        with patch("packages.agent.tools.coding_delegate._find_claude", return_value=None):
            result = await coding_delegate("帮我写代码")
            assert result.success is False
            assert "装上" in result.error or "装好" in result.error

    @pytest.mark.asyncio
    async def test_successful_delegation(self, mock_subprocess, tmp_path):
        ws = str(tmp_path / "workspace")
        os.makedirs(ws, exist_ok=True)

        with patch("packages.agent.tools.coding_delegate._find_claude", return_value="/usr/bin/claude"):
            mock_exec = AsyncMock(return_value=mock_subprocess)
            with patch("asyncio.create_subprocess_exec", mock_exec):
                with patch("packages.agent.tools.coding_delegate._collect_files", return_value=[]):
                    result = await coding_delegate("写个hello world", working_dir=ws, timeout=10)

        assert result.success is True
        assert "Generated code" in result.data["output"]

    @pytest.mark.asyncio
    async def test_timeout(self):
        import asyncio as aio_mod

        with patch("packages.agent.tools.coding_delegate._find_claude", return_value="/usr/bin/claude"):
            with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=Mock())):
                with patch("asyncio.wait_for", side_effect=aio_mod.TimeoutError()):
                    result = await coding_delegate("复杂任务", timeout=5)

        assert result.success is False
        assert "太久" in result.error

    @pytest.mark.asyncio
    async def test_subprocess_error(self):
        with patch("packages.agent.tools.coding_delegate._find_claude", return_value="/usr/bin/claude"):
            mock_exec = AsyncMock(side_effect=Exception("Process crashed"))
            with patch("asyncio.create_subprocess_exec", mock_exec):
                result = await coding_delegate("bad task")

        assert result.success is False

    @pytest.mark.asyncio
    async def test_creates_working_dir(self, tmp_path):
        ws = str(tmp_path / "new_workspace")
        assert not os.path.exists(ws)

        with patch("packages.agent.tools.coding_delegate._find_claude", return_value="/usr/bin/claude"):
            proc = AsyncMock()
            proc.communicate.return_value = (b"done", b"")
            proc.returncode = 0
            mock_exec = AsyncMock(return_value=proc)
            with patch("asyncio.create_subprocess_exec", mock_exec):
                with patch("packages.agent.tools.coding_delegate._collect_files", return_value=[]):
                    await coding_delegate("test", working_dir=ws)

        assert os.path.exists(ws)

    @pytest.mark.asyncio
    async def test_default_working_dir(self):
        home = os.path.expanduser("~")

        with patch("packages.agent.tools.coding_delegate._find_claude", return_value="/usr/bin/claude"):
            proc = AsyncMock()
            proc.communicate.return_value = (b"done", b"")
            proc.returncode = 0
            mock_exec = AsyncMock(return_value=proc)
            with patch("asyncio.create_subprocess_exec", mock_exec) as exec_mock:
                with patch("packages.agent.tools.coding_delegate._collect_files", return_value=[]):
                    await coding_delegate("test")

            cwd = exec_mock.call_args[1]["cwd"]
            assert cwd.startswith(home)

    @pytest.mark.asyncio
    async def test_stderr_noted_but_not_fatal(self):
        with patch("packages.agent.tools.coding_delegate._find_claude", return_value="/usr/bin/claude"):
            proc = AsyncMock()
            proc.communicate.return_value = (b"Output still here", b"Some warning: error in module")
            proc.returncode = 0
            mock_exec = AsyncMock(return_value=proc)
            with patch("asyncio.create_subprocess_exec", mock_exec):
                with patch("packages.agent.tools.coding_delegate._collect_files", return_value=[]):
                    result = await coding_delegate("test")

            assert result.success is True

    @pytest.mark.asyncio
    async def test_nonzero_exit_code(self):
        with patch("packages.agent.tools.coding_delegate._find_claude", return_value="/usr/bin/claude"):
            proc = AsyncMock()
            proc.communicate.return_value = (b"Failed to generate", b"Error: something broke")
            proc.returncode = 1
            mock_exec = AsyncMock(return_value=proc)
            with patch("asyncio.create_subprocess_exec", mock_exec):
                with patch("packages.agent.tools.coding_delegate._collect_files", return_value=[]):
                    result = await coding_delegate("test")

            assert result.success is False
            assert len(result.error) > 0
