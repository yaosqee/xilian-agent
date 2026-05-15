"""结构化日志配置"""
import sys
from pathlib import Path
from loguru import logger

def setup_logging():
    logger.remove()

    # 默认 trace_id，避免 KeyError
    logger.configure(extra={"trace_id": ""})

    # 控制台：彩色、简洁
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{extra[trace_id]}</cyan> | {message}",
        level="DEBUG",
    )

    # 文件：JSON 结构化（相对于项目根目录）
    project_root = Path(__file__).resolve().parents[2]  # shared → packages → 项目根
    log_path = project_root / "logs" / "xilian_{time:YYYY-MM-DD}.json"
    logger.add(
        str(log_path),
        format="{time} {level} {extra[trace_id]} {message}",
        serialize=True,
        rotation="00:00",
        retention="30 days",
        level="INFO",
        encoding="utf-8",
    )

    logger.info("日志系统就绪")
