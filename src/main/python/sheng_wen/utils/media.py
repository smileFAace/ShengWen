import os

VIDEO_MEDIA_EXTENSIONS = {
    ".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".m4v"
}
AUDIO_MEDIA_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus"
}
SUPPORTED_MEDIA_EXTENSIONS = VIDEO_MEDIA_EXTENSIONS | AUDIO_MEDIA_EXTENSIONS

# 字幕/文稿文件（直接解析为转录文本，跳过语音识别）
SUBTITLE_TEXT_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa", ".txt"}

# 上传接口可接受的完整扩展名集合
SUPPORTED_UPLOAD_EXTENSIONS = SUPPORTED_MEDIA_EXTENSIONS | SUBTITLE_TEXT_EXTENSIONS


def get_media_extension(file_path_or_name: str) -> str:
    return os.path.splitext(file_path_or_name)[1].lower()


def is_audio_media(file_path_or_name: str) -> bool:
    return get_media_extension(file_path_or_name) in AUDIO_MEDIA_EXTENSIONS


def is_subtitle_text_file(file_path_or_name: str) -> bool:
    """判断是否为字幕/文稿文件（无需语音识别，直接解析文本）。"""
    return get_media_extension(file_path_or_name) in SUBTITLE_TEXT_EXTENSIONS


def build_transcriber_payload(
    task_id: str,
    media_path: str,
    output_dir: str = "temp",
    summary_mode: str | None = None,
) -> dict:
    file_ext = get_media_extension(media_path)
    if file_ext not in SUPPORTED_MEDIA_EXTENSIONS:
        raise ValueError(
            f"不支持的文件格式: {file_ext}。支持的格式: {', '.join(sorted(SUPPORTED_MEDIA_EXTENSIONS))}"
        )

    payload = {
        "task_id": task_id,
        "output_file": os.path.join(output_dir, f"{task_id}_summary.md"),
    }
    if summary_mode:
        payload["summary_mode"] = str(summary_mode)

    # 音频文件可直接转录；视频文件需先提取音频。
    if is_audio_media(media_path):
        payload["video_file"] = None
        payload["audio_file"] = media_path
    else:
        payload["video_file"] = media_path
        payload["audio_file"] = os.path.join(output_dir, f"{task_id}.mp3")

    return payload
