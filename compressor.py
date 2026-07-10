"""
KSO Download Turbo Ultra V1.0 - Compressor / Converter module
Wraps FFmpeg for the "convert to MP3", "convert to 720p" and
"trim first 30 seconds" context-menu actions.
"""
import os
import subprocess


def _run_ffmpeg(args, on_done=None, on_error=None):
    try:
        subprocess.run(
            args,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if on_done:
            on_done()
    except FileNotFoundError:
        if on_error:
            on_error("FFmpeg not found. Install it and add it to PATH.")
    except subprocess.CalledProcessError as exc:
        if on_error:
            on_error(exc.stderr.decode(errors="ignore") if exc.stderr else str(exc))


def convert_to_mp3(input_path, on_done=None, on_error=None):
    output_path = os.path.splitext(input_path)[0] + ".mp3"
    args = ["ffmpeg", "-y", "-i", input_path, "-b:a", "320k", output_path]
    _run_ffmpeg(args, on_done, on_error)
    return output_path


def convert_to_720p(input_path, on_done=None, on_error=None):
    base, ext = os.path.splitext(input_path)
    output_path = f"{base}_720p{ext or '.mp4'}"
    args = [
        "ffmpeg", "-y", "-i", input_path,
        "-vf", "scale=-2:720",
        "-c:v", "libx264", "-crf", "23", "-c:a", "aac",
        output_path,
    ]
    _run_ffmpeg(args, on_done, on_error)
    return output_path


def trim_first_30s(input_path, on_done=None, on_error=None):
    base, ext = os.path.splitext(input_path)
    output_path = f"{base}_trim30{ext or '.mp4'}"
    args = [
        "ffmpeg", "-y", "-i", input_path,
        "-t", "30", "-c", "copy",
        output_path,
    ]
    _run_ffmpeg(args, on_done, on_error)
    return output_path
