"""
列出B站视频的所有可用格式，用于调试和选择正确的音频流。
"""
import os
import yt_dlp

from sheng_wen.downloader.bilibili_yt_dlp import bilibili_ydl_auth_context, sanitize_sessdata


def list_bilibili_formats(video_url: str):
    """
    列出B站视频的所有可用格式。

    :param video_url: B站视频URL
    """
    sessdata = sanitize_sessdata(os.getenv("BILIBILI_SESSDATA") or os.getenv("SESSDATA"))
    ydl_opts = {
        "quiet": False,
        "no_warnings": False,
        "listformats": True,
        "listformats_table": True,
    }

    with bilibili_ydl_auth_context(ydl_opts, sessdata):
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(video_url, download=False)

                print("\n" + "=" * 80)
                print(f"视频标题: {info.get('title', 'N/A')}")
                print(f"视频时长: {info.get('duration', 'N/A')} 秒")
                print("=" * 80)

                print("\n可用格式列表:")
                print("-" * 80)

                for i, fmt in enumerate(info.get("formats", [])):
                    format_id = fmt.get("format_id", "N/A")
                    ext = fmt.get("ext", "N/A")
                    filesize = fmt.get("filesize", 0)
                    filesize_mb = filesize / (1024 * 1024) if filesize else 0

                    has_video = fmt.get("vcodec", "none") != "none"
                    has_audio = fmt.get("acodec", "none") != "none"

                    format_type = (
                        "视频+音频"
                        if (has_video and has_audio)
                        else ("仅音频" if has_audio else "仅视频")
                    )

                    print(
                        f"{i+1:3d}. ID: {format_id:10s} | 扩展名: {ext:5s} | "
                        f"大小: {filesize_mb:7.2f}MB | 类型: {format_type:10s} | "
                        f"分辨率: {fmt.get('resolution', 'N/A'):10s} | FPS: {fmt.get('fps', 'N/A')}"
                    )

                print("-" * 80)

                print("\n音频格式列表:")
                print("-" * 80)
                audio_formats = [
                    f for f in info.get("formats", []) if f.get("acodec", "none") != "none"
                ]

                for i, fmt in enumerate(audio_formats):
                    format_id = fmt.get("format_id", "N/A")
                    ext = fmt.get("ext", "N/A")
                    filesize = fmt.get("filesize", 0)
                    filesize_mb = filesize / (1024 * 1024) if filesize else 0
                    abr = fmt.get("abr", "N/A")

                    print(
                        f"{i+1:3d}. ID: {format_id:10s} | 扩展名: {ext:5s} | "
                        f"大小: {filesize_mb:7.2f}MB | 比特率: {abr}"
                    )

                print("-" * 80)

            except Exception as e:
                print(f"错误: {e}")


if __name__ == "__main__":
    test_url = (
        "https://www.bilibili.com/video/BV1qZ62BhEeX/"
        "?spm_id_from=333.1007.tianma.1-3-3.click"
        "&vd_source=1a7887c189debe2908c9bfb989b12871"
    )

    print("正在获取B站视频格式信息...")
    list_bilibili_formats(test_url)
