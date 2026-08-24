"""字幕/文稿文件解析器：将 SRT / VTT / ASS / SSA 字幕或 TXT 文稿转为转录文本。

输出格式与 whisper 转录产物保持一致：每行以 6 位时间戳（HHMMSS）开头，紧跟内容，
例如::

    001512hello world

这样下游的 Agent 分块总结、时间戳跳转等功能均可直接复用。
纯文本（TXT）无时间戳，直接原样保留，仅做空行清理。
"""

from __future__ import annotations

import os
import re
from typing import List

from .logger import logger


def parse_subtitle_to_transcript(file_path: str) -> str:
    """解析字幕/文稿文件，返回转录文本（含/不含时间戳）。

    Args:
        file_path: 字幕或文稿文件路径。

    Returns:
        转录文本字符串；解析失败或内容为空时返回 ""。
    """
    ext = os.path.splitext(file_path)[1].lower()
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            raw_text = f.read()
    except OSError as exc:
        logger.warning(f"[SubtitleParser] 读取文件失败: {file_path} ({exc})")
        return ""

    # 优先按 BOM 剔除，避免影响格式判定
    if raw_text.startswith("\ufeff"):
        raw_text = raw_text[1:]

    if ext == ".srt":
        transcript = _parse_srt(raw_text)
    elif ext == ".vtt":
        transcript = _parse_vtt(raw_text)
    elif ext in (".ass", ".ssa"):
        transcript = _parse_ass(raw_text)
    elif ext == ".txt":
        transcript = _parse_txt(raw_text)
    else:
        logger.warning(f"[SubtitleParser] 不支持的扩展名: {ext}")
        return ""

    transcript = (transcript or "").strip()
    if not transcript:
        logger.warning(f"[SubtitleParser] 文件内容为空或无法解析: {file_path}")
    return transcript


def _format_duration(seconds: float) -> str:
    """将秒数格式化为 6 位 HHMMSS 字符串（与 whisper 转录一致，直接截断秒）。"""
    total = max(0, int(float(seconds)))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}{minutes:02d}{secs:02d}"


def _clean_text_block(text: str) -> str:
    """清理字幕文本块：去标签、合并多行为一行。"""
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 去掉常见的 HTML/SSA 标签（VTT 的 <c>、SRT 的 <font> 等）
        line = re.sub(r"<[^>]+>", "", line)
        line = line.replace("\\N", " ").replace("\\n", " ").replace("{\\an8}", "")
        line = line.strip()
        if line:
            lines.append(line)
    if not lines:
        return ""
    return " ".join(lines)


def _parse_srt(raw_text: str) -> str:
    """解析 SRT 字幕，返回带时间戳的转录文本。"""
    # 标准 SRT 时间行: 00:00:01,000 --> 00:00:04,000
    time_re = re.compile(
        r"(\d{1,2}:\d{2}:\d{2})[,.]\d{3}\s*-->\s*(\d{1,2}:\d{2}:\d{2})[,.]\d{3}"
    )
    return _parse_timed_blocks(raw_text, time_re, _parse_srt_timestamp)


def _parse_srt_timestamp(ts: str) -> float:
    parts = ts.strip().split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def _parse_vtt(raw_text: str) -> str:
    """解析 VTT 字幕，返回带时间戳的转录文本。"""
    time_re = re.compile(
        r"(\d{1,2}:\d{2}:\d{2}[,.]\d{3}|\d{1,2}:\d{2}[,.]\d{3})\s*-->\s*"
        r"(\d{1,2}:\d{2}:\d{2}[,.]\d{3}|\d{1,2}:\d{2}[,.]\d{3})"
    )
    return _parse_timed_blocks(raw_text, time_re, _parse_vtt_timestamp)


def _parse_vtt_timestamp(ts: str) -> float:
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
    else:
        hours = 0
        minutes = int(parts[0])
        seconds = float(parts[1])
    return hours * 3600 + minutes * 60 + seconds


def _parse_timed_blocks(raw_text: str, time_re: re.Pattern, ts_parser) -> str:
    """通用字幕块解析：遍历时间行，收集其后文本直到下一个时间行/空白。"""
    lines: List[str] = []
    for match in time_re.finditer(raw_text):
        start_ts = ts_parser(match.group(1))
        # 收集时间行之后的文本，直到下一个时间行或文件结束
        text_start = match.end()
        next_match = time_re.search(raw_text, text_start)
        text_block_end = next_match.start() if next_match else len(raw_text)
        text_block = raw_text[text_start:text_block_end]
        content = _clean_text_block(text_block)
        if content:
            lines.append(f"{_format_duration(start_ts)}{content}")
    return "\n".join(lines)


_ASS_TIME_FIELD = re.compile(
    r"Dialogue:\s*[^,]*,\s*(\d+):(\d{2}):(\d{2})[.]\d{2}\s*,\s*\d+:\d{2}:\d{2}[.]\d{2}\s*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,(.*)$"
)


def _parse_ass(raw_text: str) -> str:
    """解析 ASS/SSA 字幕，返回带时间戳的转录文本。

    Dialogue 格式::
        Dialogue: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
    """
    lines: List[str] = []
    for line in raw_text.splitlines():
        match = _ASS_TIME_FIELD.match(line.strip())
        if not match:
            continue
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        start_sec = hours * 3600 + minutes * 60 + seconds
        content = _clean_text_block(match.group(4))
        if content:
            lines.append(f"{_format_duration(start_sec)}{content}")
    return "\n".join(lines)


def _parse_txt(raw_text: str) -> str:
    """解析纯文本文稿：原样保留内容，仅清理多余空行。"""
    cleaned: List[str] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        cleaned.append(stripped)
    return "\n".join(cleaned)
