"""测试 BackupManager（2026-05-15 修订：移除 ChromaDB 备份）"""
import os
import json
import pytest
import tempfile
from pathlib import Path

from packages.shared.backup import BackupManager


@pytest.fixture
def tmpdirs():
    """创建临时目录结构"""
    with tempfile.TemporaryDirectory() as root:
        src = Path(root) / "src"
        bak = Path(root) / "backups"
        src.mkdir()
        (src / "data").mkdir()

        # 创建假数据文件
        db = src / "data" / "test.db"
        db.write_text("fake-sqlite-data")

        yield {
            "db_path": db,
            "backup_root": bak,
        }


@pytest.mark.asyncio
async def test_run_backup_creates_dir(tmpdirs):
    """备份创建目录 + manifest"""
    bm = BackupManager(
        db_path=tmpdirs["db_path"],
        backup_root=tmpdirs["backup_root"],
    )
    date_str = await bm.run_backup()
    assert date_str is not None

    backup_dir = tmpdirs["backup_root"] / date_str
    assert backup_dir.exists()
    assert (backup_dir / "test.db").exists()
    assert (backup_dir / "backup_manifest.json").exists()

    # 验证 manifest
    manifest = json.loads((backup_dir / "backup_manifest.json").read_text())
    assert manifest["backup_date"] == date_str
    assert manifest["db_path"] is not None
    assert "db_size_bytes" in manifest


@pytest.mark.asyncio
async def test_run_backup_idempotent(tmpdirs):
    """重复备份同一天不覆盖"""
    bm = BackupManager(
        db_path=tmpdirs["db_path"],
        backup_root=tmpdirs["backup_root"],
    )
    first = await bm.run_backup()
    second = await bm.run_backup()
    assert first == second


@pytest.mark.asyncio
async def test_cleanup_old(tmpdirs):
    """清理过期备份"""
    bm = BackupManager(
        db_path=tmpdirs["db_path"],
        backup_root=tmpdirs["backup_root"],
        keep_days=0,
    )
    await bm.run_backup()
    cleaned = await bm.cleanup_old()
    assert cleaned >= 1


@pytest.mark.asyncio
async def test_verify_backup_valid(tmpdirs):
    """校验有效备份"""
    bm = BackupManager(
        db_path=tmpdirs["db_path"],
        backup_root=tmpdirs["backup_root"],
    )
    date_str = await bm.run_backup()
    result = await bm.verify_backup(date_str)
    assert result["valid"] is True
    assert result["db_ok"] is True
    assert result["manifest_ok"] is True


@pytest.mark.asyncio
async def test_verify_backup_missing(tmpdirs):
    """校验不存在的备份"""
    bm = BackupManager(
        db_path=tmpdirs["db_path"],
        backup_root=tmpdirs["backup_root"],
    )
    result = await bm.verify_backup("2099-01-01")
    assert result["valid"] is False


@pytest.mark.asyncio
async def test_restore_dry_run(tmpdirs):
    """dry-run 恢复"""
    bm = BackupManager(
        db_path=tmpdirs["db_path"],
        backup_root=tmpdirs["backup_root"],
    )
    date_str = await bm.run_backup()
    result = await bm.restore(date_str, dry_run=True)
    assert result["success"] is True


@pytest.mark.asyncio
async def test_backup_missing_db(tmpdirs):
    """数据库文件不存在时的优雅处理"""
    bm = BackupManager(
        db_path=Path(tmpdirs["db_path"]).parent / "nonexistent.db",
        backup_root=tmpdirs["backup_root"],
    )
    date_str = await bm.run_backup()
    assert date_str is not None
