"""
BackupManager — 每日数据备份模块

阶段 3 新增。每日凌晨 3:00 备份 SQLite 数据库 + ChromaDB 向量库，
保留最近 7 天，自动清理过期备份。
"""
import asyncio
import json
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from loguru import logger


class BackupManager:
    """每日备份管理器 — cp 级文件备份 + 自动清理"""

    def __init__(
        self,
        db_path: str | Path = "data/xilian.db",
        chroma_path: str | Path = "chroma_data",
        backup_root: str | Path = "backups",
        keep_days: int = 7,
    ):
        self.db_path = Path(db_path)
        self.chroma_path = Path(chroma_path)
        self.backup_root = Path(backup_root)
        self.keep_days = keep_days

    # ============================================================
    # 备份
    # ============================================================

    async def run_backup(self) -> Optional[str]:
        """
        执行一次完整备份：
        1. 创建 backups/YYYY-MM-DD/ 目录
        2. cp SQLite 数据库
        3. cp ChromaDB 数据目录
        4. 写入 backup_manifest.json
        5. 返回备份日期字符串
        """
        date_str = datetime.now().strftime("%Y-%m-%d")
        backup_dir = self.backup_root / date_str

        if backup_dir.exists():
            logger.info("backup.already_exists", date=date_str)
            return date_str

        try:
            backup_dir.mkdir(parents=True, exist_ok=True)

            # 1. 备份 SQLite 数据库
            db_size = 0
            if self.db_path.exists():
                dest_db = backup_dir / self.db_path.name
                db_size = await asyncio.to_thread(
                    lambda: shutil.copy2(str(self.db_path), str(dest_db))
                )
                db_size = Path(dest_db).stat().st_size if Path(dest_db).exists() else 0

            # 2. 备份 ChromaDB 数据
            chroma_size = 0
            if self.chroma_path.exists():
                dest_chroma = backup_dir / self.chroma_path.name
                # 如果目标已存在则先删除
                if dest_chroma.exists():
                    await asyncio.to_thread(
                        lambda: shutil.rmtree(str(dest_chroma))
                    )
                await asyncio.to_thread(
                    lambda: shutil.copytree(
                        str(self.chroma_path),
                        str(dest_chroma),
                        dirs_exist_ok=True,
                    )
                )
                chroma_size = sum(
                    f.stat().st_size
                    for f in dest_chroma.rglob("*")
                    if f.is_file()
                )

            # 3. 写入 manifest
            manifest = {
                "backup_date": date_str,
                "created_at": time.time(),
                "created_at_iso": datetime.now().isoformat(),
                "db_path": str(dest_db) if self.db_path.exists() else None,
                "db_size_bytes": db_size,
                "chroma_path": str(dest_chroma) if self.chroma_path.exists() else None,
                "chroma_size_bytes": chroma_size,
            }
            manifest_path = backup_dir / "backup_manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

            total_mb = (db_size + chroma_size) / (1024 * 1024)
            logger.info(
                "backup.complete",
                date=date_str,
                db_size=btoa(db_size),
                chroma_size=btoa(chroma_size),
                total_mb=round(total_mb, 2),
            )
            return date_str

        except Exception as e:
            logger.error("backup.failed", date=date_str, error=str(e))
            # 清理失败的部分
            if backup_dir.exists():
                try:
                    shutil.rmtree(str(backup_dir))
                except Exception:
                    pass
            return None

    # ============================================================
    # 清理
    # ============================================================

    async def cleanup_old(self) -> int:
        """清理超过 keep_days 天的备份目录，返回清理数"""
        if not self.backup_root.exists():
            return 0

        cutoff = datetime.now() - timedelta(days=self.keep_days)
        cleaned = 0

        for item in sorted(self.backup_root.iterdir()):
            if not item.is_dir():
                continue
            try:
                dir_date = datetime.strptime(item.name, "%Y-%m-%d")
                if dir_date < cutoff:
                    shutil.rmtree(str(item))
                    cleaned += 1
                    logger.info("backup.cleaned", date=item.name)
            except ValueError:
                # 非日期命名的目录跳过
                continue

        if cleaned > 0:
            logger.info("backup.cleanup_complete", cleaned=cleaned, keep_days=self.keep_days)
        return cleaned

    # ============================================================
    # 校验
    # ============================================================

    async def verify_backup(self, date_str: str) -> dict:
        """
        校验指定日期备份的完整性。

        Returns:
            {"valid": bool, "db_ok": bool, "chroma_ok": bool, "manifest_ok": bool}
        """
        backup_dir = self.backup_root / date_str
        result = {"valid": False, "db_ok": False, "chroma_ok": False, "manifest_ok": False}

        if not backup_dir.exists():
            return result

        # 检查 manifest
        manifest_path = backup_dir / "backup_manifest.json"
        if manifest_path.exists():
            result["manifest_ok"] = True

        # 检查数据库
        db_backup = backup_dir / self.db_path.name
        if db_backup.exists() and db_backup.stat().st_size > 0:
            result["db_ok"] = True

        # 检查 ChromaDB
        chroma_backup = backup_dir / self.chroma_path.name
        if chroma_backup.exists() and any(chroma_backup.iterdir()):
            result["chroma_ok"] = True

        result["valid"] = result["db_ok"] and result["chroma_ok"]
        return result

    # ============================================================
    # 恢复
    # ============================================================

    async def restore(self, date_str: str, dry_run: bool = True) -> dict:
        """
        恢复指定日期的备份。

        Args:
            date_str: 备份日期 "YYYY-MM-DD"
            dry_run: True 时只校验不执行

        Returns:
            {"success": bool, "message": str}
        """
        backup_dir = self.backup_root / date_str
        if not backup_dir.exists():
            return {"success": False, "message": f"备份 {date_str} 不存在"}

        verify = await self.verify_backup(date_str)
        if not verify["valid"]:
            return {"success": False, "message": f"备份 {date_str} 不完整"}

        if dry_run:
            return {"success": True, "message": f"备份 {date_str} 校验通过（dry-run）"}

        try:
            # 恢复数据库
            db_backup = backup_dir / self.db_path.name
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(db_backup), str(self.db_path))

            # 恢复 ChromaDB
            chroma_backup = backup_dir / self.chroma_path.name
            if self.chroma_path.exists():
                shutil.rmtree(str(self.chroma_path))
            shutil.copytree(str(chroma_backup), str(self.chroma_path))

            logger.info("backup.restored", date=date_str)
            return {"success": True, "message": f"已从 {date_str} 恢复"}
        except Exception as e:
            logger.error("backup.restore_failed", date=date_str, error=str(e))
            return {"success": False, "message": str(e)}


def btoa(size_bytes: int) -> str:
    """字节数 → 人类可读"""
    if size_bytes < 1024:
        return f"{size_bytes}B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f}KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f}MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f}GB"
