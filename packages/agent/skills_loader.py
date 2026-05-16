"""
SkillsLoader — Agent Skills 加载器

阶段 7d 交付。扫描 skills/ 目录，解析 YAML Front Matter + Markdown body。
质量双门控：必填字段校验 + 安全级别校验。
"""
import os
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger


@dataclass
class Skill:
    name: str
    version: str = "0.1.0"
    category: str = "general"
    description: str = ""
    triggers: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    safety: str = "read_only"
    content: str = ""
    file_path: str = ""


@dataclass
class SkillsLoader:
    """
    技能加载器。

    扫描 skills/{manual,auto_generated}/ → 解析 → 质量校验 → 注册。
    """

    _skills: dict[str, Skill] = field(default_factory=dict)
    _skill_dirs: list[str] = field(default_factory=lambda: [
        "skills/manual",
        "skills/auto_generated",
    ])

    def load_all(self) -> dict[str, Skill]:
        """扫描全部技能目录，加载有效技能。"""
        for skill_dir in self._skill_dirs:
            if not os.path.isdir(skill_dir):
                continue
            for fname in os.listdir(skill_dir):
                if fname.endswith(".md"):
                    skill = self._load_skill(os.path.join(skill_dir, fname))
                    if skill:
                        self._skills[skill.name] = skill
                        logger.info("skills.loaded", name=skill.name,
                                    category=skill.category)
        return self._skills

    def _load_skill(self, filepath: str) -> Optional[Skill]:
        """解析单个技能文件 → 质量校验 → 返回 Skill 或 None。"""
        try:
            text = Path(filepath).read_text(encoding="utf-8")
            if not text.startswith("---"):
                logger.warning(f"技能缺少 Front Matter: {filepath}")
                return None

            parts = text.split("---", 2)
            if len(parts) < 3:
                return None

            meta = yaml.safe_load(parts[1])
            content = parts[2].strip()

            if not self._validate(meta):
                return None

            return Skill(
                name=meta.get("name", ""),
                version=meta.get("version", "0.1.0"),
                category=meta.get("category", "general"),
                description=meta.get("description", ""),
                triggers=meta.get("triggers", []),
                tools=meta.get("tools", []),
                safety=meta.get("safety", "read_only"),
                content=content,
                file_path=filepath,
            )
        except Exception as e:
            logger.warning(f"技能加载失败: {filepath} - {e}")
            return None

    def _validate(self, meta: dict) -> bool:
        """质量双门控。"""
        # 门控 1：必填字段
        for field in ("name", "description"):
            if not meta.get(field):
                logger.warning(f"技能校验失败: 缺少 {field}")
                return False
        # 门控 2：安全级别
        safety = meta.get("safety", "read_only")
        if safety not in ("read_only", "read_write", "execute"):
            logger.warning(f"技能安全级别无效: {safety}")
            return False
        return True

    def match(self, user_message: str) -> list[Skill]:
        """根据用户消息匹配技能（trigger 关键字匹配）。"""
        matched = []
        for skill in self._skills.values():
            for trigger in skill.triggers:
                if trigger in user_message:
                    matched.append(skill)
                    break
        return matched

    @property
    def skills(self) -> dict[str, Skill]:
        return self._skills

    @property
    def skill_names(self) -> list[str]:
        return list(self._skills.keys())
