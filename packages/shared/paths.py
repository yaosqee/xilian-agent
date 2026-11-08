"""运行期数据目录（开发 / 打包 / 冒烟隔离共用）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    override = os.getenv("XILIAN_HOME")
    if override:
        return Path(override).expanduser().resolve() / "data"
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "data"
    return project_root() / "data"
