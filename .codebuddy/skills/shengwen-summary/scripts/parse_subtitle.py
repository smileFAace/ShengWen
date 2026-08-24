#!/usr/bin/env python3
"""Parse subtitle/transcript files into plain transcript text.

Supports: .srt, .vtt, .ass, .ssa, .txt, .md

Output format follows whisper transcripts: each line starts with a 6-digit
timestamp (HHMMSS) followed by content, e.g.::

    001512hello world

Plain text (.txt/.md) has no timestamps and is kept as-is (blank lines removed).

Usage:
    python parse_subtitle.py <input_file> [--output <output_file>]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import List


def parse_subtitle_to_transcript(file_path: str) -> str:
    """Parse a subtitle/transcript file into transcript text.

    Args:
        file_path: Path to the subtitle or transcript file.

    Returns:
        Transcript text; returns "" if parsing fails or content is empty.
    """
    ext = os.path.splitext(file_path)[1].lower()
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            raw_text = f.read()
    except OSError as exc:
        print(f"[SubtitleParser] 读取文件失败: {file_path} ({exc})", file=sys.stderr)
        return ""

    # Strip BOM first
    if raw_text.startswith("\ufeff"):
        raw_text = raw_text[1:]

    if ext == ".srt":
        transcript = _parse_srt(raw_text)
    elif ext == ".vtt":
        transcript = _parse_vtt(raw_text)
    elif ext in (".ass", ".ssa"):
        transcript = _parse_ass(raw_text)
    elif ext in (".txt", ".md"):
        transcript = _parse_txt(raw_text)
    else:
        print(f"[SubtitleParser] 不支持的扩展名: {ext}", file=sys.stderr)
        return ""

    transcript = (transcript or "").strip()
    if not transcript:
        print(f"[SubtitleParser] 文件内容为空或无法解析: {file_path}", file=sys.stderr)
    return transcript


def _format_duration(seconds: float) -> str:
    """Format seconds as a 6-digit HHMMSS string (matching whisper output)."""
    total = max(0, int(float(seconds)))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}{minutes:02d}{secs:02d}"


def _clean_text_block(text: str) -> str:
    """Clean a subtitle text block: strip tags, join multi-lines into one."""
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip common HTML/SSA tags (VTT <c>, SRT <font>, etc.)
        line = re.sub(r"<[^>]+>", "", line)
        line = line.replace("\\N", " ").replace("\\n", " ").replace("{\\an8}", "")
        line = line.strip()
        if line:
            lines.append(line)
    if not lines:
        return ""
    return " ".join(lines)


def _parse_srt(raw_text: str) -> str:
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
    lines: List[str] = []
    for match in time_re.finditer(raw_text):
        start_ts = ts_parser(match.group(1))
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
    cleaned: List[str] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        cleaned.append(stripped)
    return "\n".join(cleaned)


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse subtitle/transcript files into plain text.")
    parser.add_argument("input_file", help="Path to the subtitle/transcript file (.srt/.vtt/.ass/.ssa/.txt/.md)")
    parser.add_argument("--output", help="Optional output file path; defaults to stdout")
    args = parser.parse_args()

    if not os.path.exists(args.input_file):
        print(f"错误: 文件不存在: {args.input_file}", file=sys.stderr)
        sys.exit(1)

    result = parse_subtitle_to_transcript(args.input_file)
    if not result:
        print("错误: 解析结果为空", file=sys.stderr)
        sys.exit(1)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result)
        print(f"已写入: {args.output}", file=sys.stderr)
    else:
        print(result)


if __name__ == "__main__":
    main()
