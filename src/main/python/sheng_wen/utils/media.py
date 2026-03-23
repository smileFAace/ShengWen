import os

VIDEO_MEDIA_EXTENSIONS = {
    ".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".m4v"
}
AUDIO_MEDIA_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus"
}
SUPPORTED_MEDIA_EXTENSIONS = VIDEO_MEDIA_EXTENSIONS | AUDIO_MEDIA_EXTENSIONS


def get_media_extension(file_path_or_name: str) -> str:
    return os.path.splitext(file_path_or_name)[1].lower()


def is_audio_media(file_path_or_name: str) -> bool:
    return get_media_extension(file_path_or_name) in AUDIO_MEDIA_EXTENSIONS


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

    # 从配置获取总结文件保存目录
    summary_dir = _get_output_dir("summary_dir", output_dir)

    payload = {
        "task_id": task_id,
        "output_file": os.path.join(summary_dir, f"{task_id}_summary.md"),
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


def _get_output_dir(config_key: str, default: str = "temp") -> str:
    """
    从配置获取输出目录，如果未配置则使用默认值。

    Args:
        config_key: 配置键名 (transcript_dir 或 summary_dir)
        default: 默认目录

    Returns:
        输出目录路径
    """
    try:
        from .config.settings import config
        output_dir = getattr(config.output, config_key, None) if hasattr(config, "output") else None
        if not output_dir:
            output_dir = default
        # 确保目录存在
        os.makedirs(output_dir, exist_ok=True)
        return output_dir
    except Exception:
        # 如果配置读取失败，返回默认值
        return default
