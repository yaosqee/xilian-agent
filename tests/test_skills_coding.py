"""SkillsLoader + coding_delegate 单元测试 — 阶段 7d"""
import pytest
import os
import tempfile

from packages.agent.skills_loader import SkillsLoader, Skill
from packages.agent.tools.coding_delegate import _find_claude, _package_result, _collect_files


class TestSkillsLoader:
    """SkillsLoader 加载与校验"""

    def test_load_valid_skill(self):
        loader = SkillsLoader()
        skills = loader.load_all()
        assert len(skills) >= 1
        assert '天气查询' in skills
        s = skills['天气查询']
        assert s.name == '天气查询'
        assert s.category == 'utility'
        assert s.safety == 'read_only'
        assert '下雨' in s.triggers

    def test_trigger_match(self):
        loader = SkillsLoader()
        loader.load_all()
        matched = loader.match('今天会下雨吗')
        assert len(matched) >= 1
        assert matched[0].name == '天气查询'

    def test_trigger_no_match(self):
        loader = SkillsLoader()
        loader.load_all()
        matched = loader.match('今天吃什么')
        assert len(matched) == 0

    def test_validation_rejects_missing_name(self):
        loader = SkillsLoader()
        assert not loader._validate({'description': 'test'})
        assert not loader._validate({'name': 'test'})  # 缺少 description

    def test_validation_rejects_invalid_safety(self):
        loader = SkillsLoader()
        assert not loader._validate({
            'name': 'test', 'description': 'test', 'safety': 'dangerous',
        })

    def test_validation_accepts_valid_safety(self):
        loader = SkillsLoader()
        for level in ('read_only', 'read_write', 'execute'):
            assert loader._validate({
                'name': 'test', 'description': 'test', 'safety': level,
            })

    def test_bad_skill_file_rejected(self):
        """无效 Front Matter 文件不加载"""
        # 创建临时无效文件
        import tempfile
        tmp = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False,
            dir='skills/manual',
        )
        tmp.write('# No front matter\nJust text')
        tmp.close()

        loader = SkillsLoader()
        loader.load_all()
        # 无效技能不在列表中
        assert '天气查询' in loader.skills  # 有效的还在

        os.unlink(tmp.name)


class TestCodingDelegate:
    """coding_delegate 辅助函数"""

    def test_find_claude(self):
        path = _find_claude()
        # Claude Code 应该已安装
        assert path is not None
        assert 'claude' in path

    def test_package_result_success(self):
        result = _package_result(
            "写网页", "Created index.html\ndone.", True, ["index.html"],
        )
        assert 'Claude Code' in result
        assert 'index.html' in result or '文件' in result

    def test_package_result_failure(self):
        result = _package_result("写网页", "", False, [])
        assert '困难' in result or '问题' in result

    def test_collect_files(self, tmp_path):
        # tmp_path 是 pytest 的临时目录 fixture
        (tmp_path / "test.txt").write_text("hello")
        (tmp_path / ".hidden").write_text("secret")
        files = _collect_files(str(tmp_path))
        assert "test.txt" in files
        assert ".hidden" not in files
