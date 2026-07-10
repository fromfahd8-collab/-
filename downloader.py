"""
KSO Download Turbo Ultra V1.0 - Downloader module
Handles smart-thread calculation and yt-dlp download jobs with
progress reporting, pause/resume, speed limiting and history logging.
"""
import json
import os
import threading
import time
import uuid

import yt_dlp

MAX_LIMIT = 1000
HISTORY_FILE = "downloads_history.json"

try:
    import speedtest

    HAS_SPEEDTEST = True
except Exception:
    HAS_SPEEDTEST = False


def test_speed():
    """Measures internet speed in Mbps. Falls back to a safe default if
    the speedtest library / network probe is unavailable."""
    if not HAS_SPEEDTEST:
        return 25.0
    try:
        st = speedtest.Speedtest()
        st.get_best_server()
        speed_mbps = st.download() / 1_000_000
        return round(speed_mbps, 1)
    except Exception:
        return 25.0


def get_smart_threads(total_files=1, smart_mode=True, manual_threads=32):
    """Decides how many parallel fragment threads to use per file."""
    if smart_mode:
        speed = test_speed()
        if speed <= 10:
            total_threads = 16
        elif speed <= 30:
            total_threads = 32
        elif speed <= 100:
            total_threads = 64
        elif speed <= 500:
            total_threads = 100
        else:
            total_threads = 200
    else:
        total_threads = manual_threads

    total_threads = min(total_threads, MAX_LIMIT)
    threads_per_file = max(1, total_files)
    per_file = total_threads // threads_per_file
    return max(per_file, 2)


def append_history(name, path, url):
    """Appends a completed download to downloads_history.json."""
    entry = {
        "name": name,
        "path": path,
        "url": url,
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    history = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []
    history.append(entry)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


class DownloadJob:
    """One row in the downloads table. Runs its own yt-dlp download
    inside a background thread and reports progress via callbacks."""

    def __init__(self, url, out_dir, quality, speed_limit_kbps=0,
                 smart_mode=True, manual_threads=32, on_progress=None,
                 on_finished=None, on_error=None):
        self.id = str(uuid.uuid4())
        self.url = url
        self.out_dir = out_dir
        self.quality = quality
        self.speed_limit_kbps = speed_limit_kbps
        self.smart_mode = smart_mode
        self.manual_threads = manual_threads
        self.on_progress = on_progress
        self.on_finished = on_finished
        self.on_error = on_error

        self.paused = threading.Event()
        self.cancelled = threading.Event()
        self.final_filename = None
        self.thread = None

    def _format_selector(self):
        q = self.quality
        if "MP3" in q:
            return "bestaudio/best"
        mapping = {
            "8K": "bestvideo[height<=4320]+bestaudio/best",
            "4K": "bestvideo[height<=2160]+bestaudio/best",
            "1080p": "bestvideo[height<=1080]+bestaudio/best",
            "720p": "bestvideo[height<=720]+bestaudio/best",
            "480p": "bestvideo[height<=480]+bestaudio/best",
        }
        return mapping.get(q, "bestvideo+bestaudio/best")

    def _progress_hook(self, d):
        if self.cancelled.is_set():
            raise yt_dlp.utils.DownloadError("Cancelled by user")

        while self.paused.is_set() and not self.cancelled.is_set():
            time.sleep(0.3)

        if d.get("status") == "downloading" and self.on_progress:
            downloaded = d.get("downloaded_bytes") or 0
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            percent = (downloaded / total * 100) if total else 0.0
            speed = d.get("speed") or 0
            eta = d.get("eta") or 0
            self.on_progress(self.id, percent, speed, total, eta)

        if d.get("status") == "finished" and self.on_progress:
            self.final_filename = d.get("filename")
            self.on_progress(self.id, 100.0, 0, d.get("total_bytes") or 0, 0)

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        threads = get_smart_threads(1, self.smart_mode, self.manual_threads)
        ydl_opts = {
            "outtmpl": os.path.join(self.out_dir, "%(title)s.%(ext)s"),
            "concurrent_fragment_downloads": threads,
            "fragment_retries": 10,
            "retries": 10,
            "merge_output_format": "mp4",
            "format": self._format_selector(),
            "nocheckcertificate": True,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [self._progress_hook],
        }
        if "MP3" in self.quality:
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                }
            ]
        if self.speed_limit_kbps and self.speed_limit_kbps > 0:
            ydl_opts["ratelimit"] = self.speed_limit_kbps * 1024

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])
            if not self.cancelled.is_set():
                append_history(
                    os.path.basename(self.final_filename or self.url),
                    self.final_filename or self.out_dir,
                    self.url,
                )
                if self.on_finished:
                    self.on_finished(self.id)
        except Exception as exc:
            if self.on_error and not self.cancelled.is_set():
                self.on_error(self.id, str(exc))

    def pause(self):
        self.paused.set()

    def resume(self):
        self.paused.clear()

    def cancel(self):
        self.cancelled.set()
        self.paused.clear()


def download_playlist(url, out_dir, quality, on_item_done=None):
    """Downloads an entire playlist into out_dir (used by the Study tab)."""
    ydl_opts = {
        "outtmpl": os.path.join(out_dir, "%(playlist_index)s - %(title)s.%(ext)s"),
        "format": "bestvideo+bestaudio/best" if "MP3" not in quality else "bestaudio/best",
        "merge_output_format": "mp4",
        "noplaylist": False,
        "ignoreerrors": True,
        "quiet": True,
    }
    if on_item_done:
        def hook(d):
            if d.get("status") == "finished":
                on_item_done(d.get("filename"))
        ydl_opts["progress_hooks"] = [hook]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
