"""任务临时文件清理：仅删除 task_id 专属产物，保留共享下载缓存。"""

from __future__ import annotations

import glob
import os
from typing import List

from .logger import logger

DEFAULT_TEMP_DIR = "temp"


def cleanup_task_temp_files(task_id: str, temp_dir: str = DEFAULT_TEMP_DIR) -> List[str]:
    """
    删除 temp 下仅属于该任务的文件：
    - {task_id}_*
    - {task_id}.*

    不删除共享缓存（如 BV*_pN.mp4）。
    """
    normalized = str(task_id or "").strip()
    if not normalized:
        return []
    if not os.path.isdir(temp_dir):
        return []

    deleted: List[str] = []
    patterns = [
        os.path.join(temp_dir, f"{normalized}_*"),
        os.path.join(temp_dir, f"{normalized}.*"),
    ]
    seen: set[str] = set()
    for pattern in patterns:
        for path in glob.glob(pattern):
            abs_path = os.path.abspath(path)
            if abs_path in seen:
                continue
            seen.add(abs_path)
            if not os.path.isfile(path):
                continue
            try:
                os.remove(path)
                deleted.append(path)
            except OSError as exc:
                logger.warning(f"[TempCleanup] 删除失败: {path} ({exc})")

    if deleted:
        logger.info(
            f"[TempCleanup] 已清理任务临时文件: task_id={normalized}, count={len(deleted)}"
        )
    return deleted
