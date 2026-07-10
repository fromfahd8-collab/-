"""
KSO Download Turbo Ultra V1.0
برمجة: عبد الله و عبد الرحمن هاني [ KSO ]

Full desktop download manager built with PyQt6 for Windows 10/11.
Run:
    python generate_assets.py   (once, to create app_icon.ico)
    python main.py
"""
import json
import os
import subprocess
import sys
import threading

from PyQt6.QtCore import Qt, QTime, QTimer, QMetaObject, Q_ARG, pyqtSlot
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QToolBar,
    QLabel, QComboBox, QPushButton, QSpinBox, QCheckBox, QLineEdit,
    QListWidget, QListWidgetItem, QTreeWidget, QSplitter, QTabWidget,
    QTableWidget, QTableWidgetItem, QHeaderView, QMenu, QDialog,
    QMessageBox, QFileDialog, QInputDialog, QTimeEdit, QAbstractItemView,
)

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView, QWebEngineDownloadRequest
    HAS_WEBENGINE = True
except Exception:
    HAS_WEBENGINE = False

from plyer import notification
import yt_dlp

from modules.downloader import DownloadJob, get_smart_threads, load_history
from modules import compressor

CONFIG_FILE = "config.json"
LANG_FILE = "lang.json"

DEFAULT_CONFIG = {
    "path": os.path.join(os.path.expanduser("~"), "Downloads"),
    "quality": "1080p",
    "parallel": 4,
    "smart_speed": True,
    "shutdown": False,
    "language": "ar",
    "speed_limit_kbps": 0,
    "app_password": "",
}


class KSOApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = self.load_config()
        self.lang_code = self.config.get("language", "ar")
        self.lang = self.load_lang(self.lang_code)

        if not self.check_password():
            sys.exit(0)

        self.setWindowTitle(self.lang["title"])
        self.resize(1360, 900)
        if os.path.exists("app_icon.ico"):
            self.setWindowIcon(QIcon("app_icon.ico"))

        self.jobs = {}          # job_id -> DownloadJob
        self.row_by_job = {}    # job_id -> table row index
        self.search_query = ""
        self.search_page = 1

        self.init_ui()
        self.init_hotkeys()
        self.update_yt_dlp()
        self.apply_theme()
        self.refresh_history_table()

    # ---------- persistence ----------
    def load_lang(self, code):
        with open(LANG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)[code]

    def load_config(self):
        cfg = dict(DEFAULT_CONFIG)
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg.update(json.load(f))
            except Exception:
                pass
        return cfg

    def save_config(self):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)

    def check_password(self):
        pwd = self.config.get("app_password", "")
        if not pwd:
            return True
        entered, ok = QInputDialog.getText(
            None, "KSO", self.load_lang(self.lang_code)["enter_password"],
            QLineEdit.EchoMode.Password,
        )
        if not ok or entered != pwd:
            if ok:
                QMessageBox.critical(None, "KSO", self.load_lang(self.lang_code)["wrong_password"])
            return False
        return True

    # ---------- UI ----------
    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # Watermark
        self.watermark = QLabel("KSO", central)
        self.watermark.setStyleSheet(
            "font-size: 140px; color: rgba(120,120,120,25); font-weight: 900;"
        )
        self.watermark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.watermark.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.watermark.lower()

        root.addWidget(self.build_toolbar_widget())

        self.browser = self.build_browser()
        if self.browser is not None:
            self.browser_toggle.toggled.connect(self.browser.setVisible)
        self.tabs = self.build_tabs()
        self.downloads_table = self.build_downloads_table()
        self.playlist_tree = QTreeWidget()
        self.playlist_tree.setHeaderLabel("Playlist")

        splitter = QSplitter(Qt.Orientation.Vertical)
        if self.browser is not None:
            splitter.addWidget(self.browser)
        splitter.addWidget(self.tabs)
        splitter.addWidget(self.downloads_table)
        splitter.addWidget(self.playlist_tree)
        splitter.setSizes([350, 220, 260, 100])
        root.addWidget(splitter)

    def build_toolbar_widget(self):
        toolbar = QToolBar()
        self.addToolBar(toolbar)

        toolbar.addWidget(QLabel(self.lang["quality"]))
        self.quality_box = QComboBox()
        self.quality_box.addItems(["8K", "4K", "1080p", "720p", "480p", "MP3 320"])
        self.quality_box.setCurrentText(self.config.get("quality", "1080p"))
        toolbar.addWidget(self.quality_box)

        toolbar.addWidget(QLabel(self.lang["path"]))
        self.path_btn = QPushButton(self.config["path"])
        self.path_btn.clicked.connect(self.browse_path)
        toolbar.addWidget(self.path_btn)

        toolbar.addWidget(QLabel(self.lang["count"]))
        self.parallel_spin = QSpinBox()
        self.parallel_spin.setRange(1, 32)
        self.parallel_spin.setValue(self.config.get("parallel", 4))
        toolbar.addWidget(self.parallel_spin)

        self.smart_speed_check = QCheckBox(self.lang["smart_speed"])
        self.smart_speed_check.setChecked(self.config.get("smart_speed", True))
        toolbar.addWidget(self.smart_speed_check)

        toolbar.addWidget(QLabel(self.lang["speed_limit"]))
        self.speed_limit_spin = QSpinBox()
        self.speed_limit_spin.setRange(0, 1_000_000)
        self.speed_limit_spin.setValue(self.config.get("speed_limit_kbps", 0))
        toolbar.addWidget(self.speed_limit_spin)

        toolbar.addWidget(QLabel(self.lang["schedule"]))
        self.schedule_edit = QTimeEdit()
        self.schedule_edit.setDisplayFormat("HH:mm")
        self.schedule_edit.setTime(QTime.currentTime())
        toolbar.addWidget(self.schedule_edit)
        self.schedule_check = QCheckBox()
        toolbar.addWidget(self.schedule_check)

        self.browser_toggle = QAction(self.lang["browser"], self, checkable=True)
        self.browser_toggle.setChecked(True)
        toolbar.addAction(self.browser_toggle)

        self.shutdown_check = QCheckBox(self.lang["shutdown"])
        self.shutdown_check.setChecked(self.config.get("shutdown", False))
        toolbar.addWidget(self.shutdown_check)

        self.lang_btn = QPushButton(self.lang["lang_btn"])
        self.lang_btn.clicked.connect(self.toggle_language)
        toolbar.addWidget(self.lang_btn)

        settings_action = QAction(self.lang["settings"], self)
        settings_action.triggered.connect(self.show_settings)
        toolbar.addAction(settings_action)

        about_action = QAction(self.lang["about"], self)
        about_action.triggered.connect(self.show_about)
        toolbar.addAction(about_action)

        return toolbar

    def build_browser(self):
        if not HAS_WEBENGINE:
            return QLabel(
                "QtWebEngine غير متاح في هذه البيئة. البرنامج سيعمل بالكامل على Windows 10/11 مع "
                "PyQt6-WebEngine مثبتة."
            )
        from PyQt6.QtCore import QUrl
        browser = QWebEngineView()
        browser.load(QUrl("https://www.youtube.com"))
        browser.urlChanged.connect(self.on_browser_url_changed)
        browser.page().profile().downloadRequested.connect(self.handle_download_request)
        return browser

    def build_tabs(self):
        tabs = QTabWidget()

        # --- Search / All tab ---
        search_tab = QWidget()
        search_layout = QVBoxLayout(search_tab)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.lang["search"])
        self.search_input.returnPressed.connect(lambda: self.search_youtube(reset=True))
        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(self.result_item_clicked)
        self.load_more_btn = QPushButton(self.lang["load_more"])
        self.load_more_btn.clicked.connect(lambda: self.search_youtube(reset=False))
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.results_list)
        search_layout.addWidget(self.load_more_btn)
        tabs.addTab(search_tab, self.lang["tab_all"])
        tabs.addTab(QWidget(), self.lang["tab_videos"])
        tabs.addTab(QWidget(), self.lang["tab_playlists"])
        tabs.addTab(QWidget(), self.lang["tab_shorts"])

        # --- Study tab ---
        study_tab = QWidget()
        study_layout = QVBoxLayout(study_tab)
        self.study_input = QLineEdit()
        self.study_input.setPlaceholderText(self.lang["study_course_placeholder"])
        create_folder_btn = QPushButton(self.lang["create_folder"])
        create_folder_btn.clicked.connect(self.create_study_folder)
        download_playlist_btn = QPushButton(self.lang["download_playlist"])
        download_playlist_btn.clicked.connect(self.download_study_playlist)
        study_layout.addWidget(self.study_input)
        row = QHBoxLayout()
        row.addWidget(create_folder_btn)
        row.addWidget(download_playlist_btn)
        study_layout.addLayout(row)
        tabs.addTab(study_tab, self.lang["tab_study"])

        # --- History tab ---
        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText(self.lang["history_search_placeholder"])
        self.history_search.textChanged.connect(self.filter_history_table)
        self.history_table = QTableWidget(0, 4)
        self.history_table.setHorizontalHeaderLabels(
            [self.lang["col_name"], self.lang["path"], self.lang["col_date"], self.lang["redownload"]]
        )
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        history_layout.addWidget(self.history_search)
        history_layout.addWidget(self.history_table)
        tabs.addTab(history_tab, self.lang["tab_history"])

        return tabs

    def build_downloads_table(self):
        table = QTableWidget(0, 8)
        table.setHorizontalHeaderLabels([
            self.lang["col_name"], self.lang["col_progress"], self.lang["col_speed"],
            self.lang["col_size"], self.lang["col_eta"], self.lang["col_status"],
            self.lang["col_pause"], self.lang["col_delete"],
        ])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        table.customContextMenuRequested.connect(self.show_downloads_context_menu)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        return table

    # ---------- browser / auto-capture ----------
    def on_browser_url_changed(self, qurl):
        url = qurl.toString()
        if "youtube.com/watch" in url or "youtu.be/" in url:
            answer = QMessageBox.question(self, "KSO", self.lang["video_found_q"])
            if answer == QMessageBox.StandardButton.Yes:
                self.queue_download(url)

    def handle_download_request(self, item):
        url = item.url().toString()
        lowered = url.lower()
        if any(ext in lowered for ext in [".exe", ".pdf", ".zip", ".mp4", ".mkv", ".m3u8", ".rar"]):
            item.cancel()
            answer = QMessageBox.question(self, "KSO", self.lang["download_q"] + "\n" + url)
            if answer == QMessageBox.StandardButton.Yes:
                self.queue_download(url)

    # ---------- search ----------
    def search_youtube(self, reset=True):
        query = self.search_input.text().strip()
        if not query:
            return
        if reset:
            self.search_query = query
            self.search_page = 1
            self.results_list.clear()
        else:
            self.search_page += 1

        self.load_more_btn.setEnabled(False)
        count = self.search_page * 20

        def run():
            try:
                ydl_opts = {"extract_flat": "in_playlist", "quiet": True, "skip_download": True}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(f"ytsearch{count}:{self.search_query}", download=False)
                entries = info.get("entries", []) if info else []
                self._populate_results(entries)
            except Exception as exc:
                self._search_error(str(exc))

        threading.Thread(target=run, daemon=True).start()

    @pyqtSlot(list)
    def _populate_results(self, entries):
        QMetaObject.invokeMethod(self, "_populate_results_ui", Qt.ConnectionType.QueuedConnection,
                                  Q_ARG(list, entries))

    @pyqtSlot(list)
    def _populate_results_ui(self, entries):
        self.results_list.clear()
        for entry in entries:
            title = entry.get("title", "?")
            uploader = entry.get("uploader", "?")
            vid_id = entry.get("id", "")
            item = QListWidgetItem(f"{title} | {uploader}")
            item.setData(Qt.ItemDataRole.UserRole, vid_id)
            self.results_list.addItem(item)
        self.load_more_btn.setEnabled(True)

    def _search_error(self, message):
        QMetaObject.invokeMethod(self, "_show_search_error", Qt.ConnectionType.QueuedConnection,
                                  Q_ARG(str, message))

    @pyqtSlot(str)
    def _show_search_error(self, message):
        self.load_more_btn.setEnabled(True)
        QMessageBox.warning(self, "KSO", message)

    def result_item_clicked(self, item):
        vid_id = item.data(Qt.ItemDataRole.UserRole)
        if vid_id:
            self.queue_download(f"https://youtube.com/watch?v={vid_id}")

    # ---------- downloads ----------
    def queue_download(self, url, out_dir=None):
        if self.schedule_check.isChecked():
            target = self.schedule_edit.time()
            now = QTime.currentTime()
            delay_ms = max(0, now.msecsTo(target))
            QTimer.singleShot(delay_ms, lambda: self._start_download(url, out_dir))
            notification.notify(title="KSO", message=f"تمت جدولة التحميل: {url}", timeout=3)
        else:
            self._start_download(url, out_dir)

    def _start_download(self, url, out_dir=None):
        quality = self.quality_box.currentText()
        out_dir = out_dir or self.path_btn.text()
        os.makedirs(out_dir, exist_ok=True)

        job = DownloadJob(
            url=url,
            out_dir=out_dir,
            quality=quality,
            speed_limit_kbps=self.speed_limit_spin.value(),
            smart_mode=self.smart_speed_check.isChecked(),
            manual_threads=self.parallel_spin.value(),
            on_progress=self.on_job_progress,
            on_finished=self.on_job_finished,
            on_error=self.on_job_error,
        )
        self.jobs[job.id] = job

        row = self.downloads_table.rowCount()
        self.downloads_table.insertRow(row)
        self.row_by_job[job.id] = row
        self.downloads_table.setItem(row, 0, QTableWidgetItem(url))
        self.downloads_table.setItem(row, 1, QTableWidgetItem("0"))
        self.downloads_table.setItem(row, 2, QTableWidgetItem("-"))
        self.downloads_table.setItem(row, 3, QTableWidgetItem("-"))
        self.downloads_table.setItem(row, 4, QTableWidgetItem("-"))
        self.downloads_table.setItem(row, 5, QTableWidgetItem(self.lang["status_downloading"]))

        pause_btn = QPushButton(self.lang["pause"])
        pause_btn.clicked.connect(lambda: self.toggle_pause(job.id, pause_btn))
        self.downloads_table.setCellWidget(row, 6, pause_btn)

        delete_btn = QPushButton(self.lang["delete"])
        delete_btn.clicked.connect(lambda: self.delete_job(job.id))
        self.downloads_table.setCellWidget(row, 7, delete_btn)

        job.start()
        notification.notify(title="KSO", message="بدأ التحميل" if self.lang_code == "ar" else "Download started", timeout=3)

    def toggle_pause(self, job_id, btn):
        job = self.jobs.get(job_id)
        if not job:
            return
        if job.paused.is_set():
            job.resume()
            btn.setText(self.lang["pause"])
        else:
            job.pause()
            btn.setText(self.lang["resume"])
        row = self.row_by_job.get(job_id)
        if row is not None:
            status = self.lang["status_paused"] if job.paused.is_set() else self.lang["status_downloading"]
            self.downloads_table.setItem(row, 5, QTableWidgetItem(status))

    def delete_job(self, job_id):
        job = self.jobs.get(job_id)
        if job:
            job.cancel()
        row = self.row_by_job.get(job_id)
        if row is not None:
            self.downloads_table.removeRow(row)
            del self.row_by_job[job_id]
            for jid, r in self.row_by_job.items():
                if r > row:
                    self.row_by_job[jid] = r - 1
        self.jobs.pop(job_id, None)

    def on_job_progress(self, job_id, percent, speed, total, eta):
        QMetaObject.invokeMethod(
            self, "_update_progress_ui", Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, job_id), Q_ARG(float, percent), Q_ARG(float, speed),
            Q_ARG(float, total), Q_ARG(float, eta),
        )

    @pyqtSlot(str, float, float, float, float)
    def _update_progress_ui(self, job_id, percent, speed, total, eta):
        row = self.row_by_job.get(job_id)
        if row is None:
            return
        self.downloads_table.setItem(row, 1, QTableWidgetItem(f"{percent:.1f}"))
        self.downloads_table.setItem(row, 2, QTableWidgetItem(f"{speed / 1024:.0f} KB/s" if speed else "-"))
        self.downloads_table.setItem(row, 3, QTableWidgetItem(f"{total / 1024 / 1024:.1f} MB" if total else "-"))
        self.downloads_table.setItem(row, 4, QTableWidgetItem(f"{int(eta)}s" if eta else "-"))

    def on_job_finished(self, job_id):
        QMetaObject.invokeMethod(self, "_job_finished_ui", Qt.ConnectionType.QueuedConnection, Q_ARG(str, job_id))

    @pyqtSlot(str)
    def _job_finished_ui(self, job_id):
        row = self.row_by_job.get(job_id)
        if row is not None:
            self.downloads_table.setItem(row, 5, QTableWidgetItem(self.lang["status_completed"]))
            self.downloads_table.setItem(row, 1, QTableWidgetItem("100.0"))
        notification.notify(title="KSO", message="تم الانتهاء" if self.lang_code == "ar" else "Download finished", timeout=5)
        self.refresh_history_table()
        if self.shutdown_check.isChecked() and not any(
            not j.cancelled.is_set() and j.thread and j.thread.is_alive() for j in self.jobs.values()
        ):
            os.system("shutdown /s /t 30")

    def on_job_error(self, job_id, message):
        QMetaObject.invokeMethod(self, "_job_error_ui", Qt.ConnectionType.QueuedConnection,
                                  Q_ARG(str, job_id), Q_ARG(str, message))

    @pyqtSlot(str, str)
    def _job_error_ui(self, job_id, message):
        row = self.row_by_job.get(job_id)
        if row is not None:
            self.downloads_table.setItem(row, 5, QTableWidgetItem(self.lang["status_error"]))

    # ---------- converter context menu ----------
    def show_downloads_context_menu(self, pos):
        row = self.downloads_table.rowAt(pos.y())
        if row < 0:
            return
        job_id = None
        for jid, r in self.row_by_job.items():
            if r == row:
                job_id = jid
                break
        job = self.jobs.get(job_id)
        file_path = job.final_filename if job else None
        if not file_path or not os.path.exists(file_path):
            return

        menu = QMenu(self)
        act_mp3 = menu.addAction(self.lang["convert_mp3"])
        act_720 = menu.addAction(self.lang["convert_720p"])
        act_trim = menu.addAction(self.lang["trim_30s"])
        chosen = menu.exec(self.downloads_table.viewport().mapToGlobal(pos))

        def notify_done():
            notification.notify(title="KSO", message="Conversion complete", timeout=4)

        def notify_error(msg):
            QMetaObject.invokeMethod(self, "_show_search_error", Qt.ConnectionType.QueuedConnection, Q_ARG(str, msg))

        if chosen == act_mp3:
            threading.Thread(target=lambda: compressor.convert_to_mp3(file_path, notify_done, notify_error), daemon=True).start()
        elif chosen == act_720:
            threading.Thread(target=lambda: compressor.convert_to_720p(file_path, notify_done, notify_error), daemon=True).start()
        elif chosen == act_trim:
            threading.Thread(target=lambda: compressor.trim_first_30s(file_path, notify_done, notify_error), daemon=True).start()

    # ---------- study tab ----------
    def create_study_folder(self):
        subject = self.study_input.text().strip()
        if not subject:
            return
        folder = os.path.join(self.path_btn.text(), subject)
        os.makedirs(folder, exist_ok=True)
        QMessageBox.information(self, "KSO", self.lang["folder_created"])

    def download_study_playlist(self):
        subject = self.study_input.text().strip()
        if not subject:
            return
        folder = os.path.join(self.path_btn.text(), subject)
        os.makedirs(folder, exist_ok=True)

        def run():
            try:
                ydl_opts = {"extract_flat": "in_playlist", "quiet": True, "skip_download": True}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(f"ytsearch1:{subject} كورس", download=False)
                entries = info.get("entries", []) if info else []
                if entries:
                    vid_id = entries[0].get("id")
                    url = f"https://youtube.com/playlist?list={vid_id}" if vid_id else None
                    if url:
                        from modules.downloader import download_playlist
                        download_playlist(url, folder, self.quality_box.currentText())
                        notification.notify(title="KSO", message="Playlist downloaded", timeout=5)
            except Exception as exc:
                self._search_error(str(exc))

        threading.Thread(target=run, daemon=True).start()

    # ---------- history tab ----------
    def refresh_history_table(self):
        history = load_history()
        self.history_table.setRowCount(0)
        for entry in reversed(history):
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)
            self.history_table.setItem(row, 0, QTableWidgetItem(entry.get("name", "")))
            self.history_table.setItem(row, 1, QTableWidgetItem(entry.get("path", "")))
            self.history_table.setItem(row, 2, QTableWidgetItem(entry.get("date", "")))
            redl_btn = QPushButton(self.lang["redownload"])
            url = entry.get("url", "")
            redl_btn.clicked.connect(lambda checked=False, u=url: self.queue_download(u) if u else None)
            self.history_table.setCellWidget(row, 3, redl_btn)

    def filter_history_table(self, text):
        text = text.lower()
        for row in range(self.history_table.rowCount()):
            name_item = self.history_table.item(row, 0)
            match = text in (name_item.text().lower() if name_item else "")
            self.history_table.setRowHidden(row, not match)

    # ---------- hotkeys ----------
    def init_hotkeys(self):
        try:
            import keyboard
            keyboard.add_hotkey("ctrl+shift+k", self.show_from_hidden)
            keyboard.add_hotkey("ctrl+shift+q", self.quit_app)
            keyboard.add_hotkey("ctrl+shift+d", self.clipboard_download)
            keyboard.add_hotkey("ctrl+shift+h", self.enter_hidden_mode)
        except Exception as exc:
            print("Hotkeys unavailable:", exc)

    def show_from_hidden(self):
        QMetaObject.invokeMethod(self, "_show_from_hidden_ui", Qt.ConnectionType.QueuedConnection)

    @pyqtSlot()
    def _show_from_hidden_ui(self):
        self.setWindowFlags(Qt.WindowType.Window)
        self.show()
        self.raise_()
        self.activateWindow()

    def enter_hidden_mode(self):
        QMetaObject.invokeMethod(self, "_enter_hidden_mode_ui", Qt.ConnectionType.QueuedConnection)

    @pyqtSlot()
    def _enter_hidden_mode_ui(self):
        notification.notify(title="KSO", message=self.lang["hidden_mode_msg"], timeout=4)
        self.setWindowFlags(Qt.WindowType.Tool)
        self.hide()

    def clipboard_download(self):
        QMetaObject.invokeMethod(self, "_clipboard_download_ui", Qt.ConnectionType.QueuedConnection)

    @pyqtSlot()
    def _clipboard_download_ui(self):
        url = QApplication.clipboard().text()
        if url.startswith("http"):
            answer = QMessageBox.question(self, "KSO", self.lang["download_q"] + "\n" + url)
            if answer == QMessageBox.StandardButton.Yes:
                self.queue_download(url)

    # ---------- language ----------
    def toggle_language(self):
        self.lang_code = "en" if self.lang_code == "ar" else "ar"
        self.config["language"] = self.lang_code
        self.save_config()
        QMessageBox.information(
            self, "KSO",
            "الرجاء اعادة تشغيل البرنامج لتطبيق اللغة الجديدة"
            if self.lang_code == "en" else
            "Please restart the app to apply the new language",
        )

    # ---------- settings ----------
    def show_settings(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(self.lang["settings"])
        dlg.resize(400, 150)
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(self.lang["app_password"]))
        pwd_input = QLineEdit(self.config.get("app_password", ""))
        pwd_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(pwd_input)
        save_btn = QPushButton(self.lang["save_settings"])

        def save():
            self.config["app_password"] = pwd_input.text()
            self.config["path"] = self.path_btn.text()
            self.config["parallel"] = self.parallel_spin.value()
            self.config["smart_speed"] = self.smart_speed_check.isChecked()
            self.config["speed_limit_kbps"] = self.speed_limit_spin.value()
            self.config["shutdown"] = self.shutdown_check.isChecked()
            self.config["quality"] = self.quality_box.currentText()
            self.save_config()
            QMessageBox.information(dlg, "KSO", self.lang["settings_saved"])
            dlg.accept()

        save_btn.clicked.connect(save)
        layout.addWidget(save_btn)
        dlg.exec()

    # ---------- about ----------
    def show_about(self):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{self.lang['about']} - KSO")
        dlg.resize(720, 560)
        layout = QVBoxLayout(dlg)
        tabs = QTabWidget()

        intro_label = QLabel(self.lang["about_intro_text"])
        intro_label.setWordWrap(True)
        intro_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        tabs.addTab(intro_label, self.lang["about_intro_title"])

        shortcuts_table = QTableWidget(4, 2)
        shortcuts_table.setHorizontalHeaderLabels(["Shortcut", self.lang["about_catalog_title"]])
        shortcuts_table.horizontalHeader().setStretchLastSection(True)
        rows = [
            ("Ctrl + Shift + K", "Show the app / capture clipboard link"),
            ("Ctrl + Shift + Q", "Quit the app, saving state"),
            ("Ctrl + Shift + D", "Download the link currently in the clipboard"),
            ("Ctrl + Shift + H", "Hide the app from the taskbar (hidden mode)"),
        ]
        for i, (k, v) in enumerate(rows):
            shortcuts_table.setItem(i, 0, QTableWidgetItem(k))
            shortcuts_table.setItem(i, 1, QTableWidgetItem(v))
        tabs.addTab(shortcuts_table, self.lang["about_catalog_title"])

        headers = self.lang["about_compare_headers"]
        compare_rows = self.lang["about_compare_rows"]
        compare_table = QTableWidget(len(compare_rows), len(headers))
        compare_table.setHorizontalHeaderLabels(headers)
        compare_table.horizontalHeader().setStretchLastSection(True)
        for r, row_values in enumerate(compare_rows):
            for c, value in enumerate(row_values):
                compare_table.setItem(r, c, QTableWidgetItem(value))
        tabs.addTab(compare_table, self.lang["about_compare_title"])

        layout.addWidget(tabs)
        thanks_label = QLabel(self.lang["thanks"])
        thanks_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(thanks_label)
        dlg.setLayout(layout)
        dlg.exec()

    # ---------- misc ----------
    def browse_path(self):
        path = QFileDialog.getExistingDirectory(self, self.lang["path"], self.path_btn.text())
        if path:
            self.path_btn.setText(path)
            self.config["path"] = path

    def update_yt_dlp(self):
        subprocess.Popen([sys.executable, "-m", "pip", "install", "-U", "yt-dlp", "--quiet"])

    def apply_theme(self):
        hour = QTime.currentTime().hour()
        if hour >= 18 or hour < 6:
            self.setStyleSheet(
                "QMainWindow { background: #1e1e1e; color: #f0f0f0; }"
                "QToolBar { background: #2d2d2d; }"
                "QTableWidget, QListWidget, QTreeWidget { background: #252525; color: #f0f0f0; }"
            )
        else:
            self.setStyleSheet("")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.watermark.setGeometry(self.centralWidget().rect())

    def closeEvent(self, event):
        self.config["path"] = self.path_btn.text()
        self.config["parallel"] = self.parallel_spin.value()
        self.config["smart_speed"] = self.smart_speed_check.isChecked()
        self.config["speed_limit_kbps"] = self.speed_limit_spin.value()
        self.config["shutdown"] = self.shutdown_check.isChecked()
        self.config["quality"] = self.quality_box.currentText()
        self.save_config()
        if self.shutdown_check.isChecked():
            os.system("shutdown /s /t 30")
        super().closeEvent(event)

    def quit_app(self):
        QMetaObject.invokeMethod(self, "close", Qt.ConnectionType.QueuedConnection)


def main():
    app = QApplication(sys.argv)
    window = KSOApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
