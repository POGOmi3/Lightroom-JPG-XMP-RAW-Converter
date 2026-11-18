import sys
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QVBoxLayout, QWidget, QGroupBox
)

from core import XmpSyncCore, ProcessResult


DARK_QSS = """
QWidget {
    background-color: #232323;
    color: #E6E6E6;
    font-family: "Yu Gothic UI", "Segoe UI", sans-serif;
    font-size: 13px;
}

QLabel, QCheckBox {
    background-color: transparent;
}

QLabel {
    color: #E6E6E6;
}

QLabel#statusLabel {
    color: #9E9E9E;
}

DropAreaLabel, QLabel#dropArea {
    background-color: #1B1B1B;
    border: 2px dashed #4A4A4A;
    border-radius: 10px;
    color: #CFCFCF;
    font-size: 13px;
    padding: 16px;
}

DropAreaLabel:hover,
QLabel#dropArea:hover,
DropAreaLabel[dragOver="true"],
QLabel#dropArea[dragOver="true"] {
    border-color: #31A8FF;
    background-color: #202226;
}

QGroupBox {
    background-color: #2A2A2A;
    border: 1px solid #3A3A3A;
    border-radius: 8px;
    margin-top: 14px;
    padding: 12px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    top: 0px;
    padding: 0px 4px;
    color: #9E9E9E;
    font-size: 12px;
    font-weight: 600;
    background-color: transparent;
}

QLineEdit {
    background-color: #1E1E1E;
    color: #E6E6E6;
    border: 1px solid #3F3F3F;
    border-radius: 6px;
    padding: 7px 10px;
    selection-background-color: #31A8FF;
    selection-color: #FFFFFF;
}

QLineEdit:focus {
    border-color: #31A8FF;
}

QPushButton {
    background-color: #3A3A3A;
    color: #E6E6E6;
    border: 1px solid #4A4A4A;
    border-radius: 6px;
    padding: 7px 14px;
}

QPushButton:hover {
    background-color: #454545;
}

QPushButton:pressed {
    background-color: #2E2E2E;
}

QPushButton:disabled {
    background-color: #2C2C2C;
    color: #777777;
    border-color: #383838;
}

QPushButton#primaryButton {
    background-color: #1473E6;
    color: white;
    font-weight: bold;
    font-size: 14px;
    border: none;
    border-radius: 6px;
}

QPushButton#primaryButton:hover {
    background-color: #2B85F0;
}

QPushButton#primaryButton:pressed {
    background-color: #0D66D0;
}

QPushButton#primaryButton:disabled {
    background-color: #33506E;
    color: #8FA6BC;
    border: none;
}

QMessageBox QPushButton {
    min-width: 72px;
}

QCheckBox {
    spacing: 8px;
    color: #E6E6E6;
}

QCheckBox:disabled {
    color: #6E6E6E;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #5A5A5A;
    border-radius: 4px;
    background-color: #1E1E1E;
}

QCheckBox::indicator:hover {
    border-color: #7A7A7A;
}

QCheckBox::indicator:checked {
    background-color: #31A8FF;
    border-color: #31A8FF;
}

QCheckBox::indicator:checked:hover {
    background-color: #4BB5FF;
    border-color: #4BB5FF;
}

QCheckBox::indicator:disabled {
    background-color: #252525;
    border-color: #3E3E3E;
}

QCheckBox::indicator:checked:disabled {
    background-color: #2A5A7A;
    border-color: #2A5A7A;
}

QProgressBar {
    background-color: #1E1E1E;
    border: 1px solid #3A3A3A;
    border-radius: 5px;
    min-height: 8px;
    max-height: 8px;
}

QProgressBar::chunk {
    background-color: #31A8FF;
    border-radius: 4px;
}

QPlainTextEdit {
    background-color: #1A1A1A;
    color: #CFCFCF;
    border: 1px solid #333333;
    border-radius: 6px;
    padding: 8px;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 10pt;
    selection-background-color: #31A8FF;
    selection-color: #FFFFFF;
}

QAbstractScrollArea::corner {
    background: transparent;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background-color: #444444;
    min-height: 24px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background-color: #555555;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
}

QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
}

QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 0px;
}

QScrollBar::handle:horizontal {
    background-color: #444444;
    min-width: 24px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #555555;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0px;
    background: none;
}

QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal {
    background: transparent;
}
"""


class SyncWorker(QThread):
    progress = Signal(int, int, str)
    finished_result = Signal(object)

    def __init__(
        self,
        folder_path: Path,
        exiftool_path: Path | None,
        auto_aspect_crop: bool,
        adjust_mask_coords: bool,
        trash_source_dng: bool
    ):
        super().__init__()
        self.folder_path = folder_path
        self.exiftool_path = exiftool_path
        self.auto_aspect_crop = auto_aspect_crop
        self.adjust_mask_coords = adjust_mask_coords
        self.trash_source_dng = trash_source_dng
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        core = XmpSyncCore(exiftool_path=self.exiftool_path)
        res = core.process_folder(
            folder_path=self.folder_path,
            auto_aspect_crop=self.auto_aspect_crop,
            adjust_mask_coords=self.adjust_mask_coords,
            trash_source_dng=self.trash_source_dng,
            progress_callback=lambda cur, tot, msg: self.progress.emit(cur, tot, msg),
            cancel_check=lambda: self._is_cancelled
        )
        self.finished_result.emit(res)


class DropAreaLabel(QLabel):
    folder_dropped = Signal(Path)

    def __init__(self):
        super().__init__("📂 ここに作業フォルダ（.dng と .ORF が入ったフォルダ）をドラッグ＆ドロップ\nまたは下の「フォルダ選択」ボタンから指定してください")
        self.setObjectName("dropArea")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAcceptDrops(True)
        self.setMinimumHeight(110)
        self.setProperty("dragOver", False)

    def _set_drag_over(self, active: bool):
        if self.property("dragOver") != active:
            self.setProperty("dragOver", active)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            self._set_drag_over(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self._set_drag_over(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        self._set_drag_over(False)
        urls = event.mimeData().urls()
        if not urls:
            return
        local_path = Path(urls[0].toLocalFile())
        if local_path.is_file():
            local_path = local_path.parent
        if local_path.is_dir():
            self.folder_dropped.emit(local_path)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Lr Cloud JPG → RAW (ORF) 引き継ぎスタジオ")
        self.resize(760, 620)
        self.worker: SyncWorker | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # 1. ドロップエリア
        self.drop_label = DropAreaLabel()
        self.drop_label.folder_dropped.connect(self.set_folder_path)
        layout.addWidget(self.drop_label)

        # 2. フォルダパス選択行
        path_layout = QHBoxLayout()
        path_layout.setSpacing(8)
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("作業フォルダのパス...")
        btn_browse = QPushButton("フォルダ選択...")
        btn_browse.clicked.connect(self.browse_folder)
        path_layout.addWidget(QLabel("対象フォルダ:"))
        path_layout.addWidget(self.path_edit, stretch=1)
        path_layout.addWidget(btn_browse)
        layout.addLayout(path_layout)

        # 3. オプション設定グループ
        opt_group = QGroupBox("引き継ぎ・安全設定")
        opt_layout = QVBoxLayout(opt_group)
        opt_layout.setContentsMargins(6, 8, 6, 6)
        opt_layout.setSpacing(8)

        self.chk_aspect = QCheckBox("画角の自動補正を行う（カメラ内 3:2 / 16:9 / 1:1 / 縦位置 を判別してRAWへ再現）【推奨】")
        self.chk_aspect.setChecked(True)

        self.chk_mask = QCheckBox("プリセット等のマスク座標（線形グラデーション等）も画角に合わせて位置補正する")
        self.chk_mask.setChecked(False)

        self.chk_trash = QCheckBox("処理成功後に抽出元の .dng ファイルをWindowsのごみ箱へ移動する（容量節約）")
        self.chk_trash.setChecked(False)

        opt_layout.addWidget(self.chk_aspect)
        opt_layout.addWidget(self.chk_mask)
        opt_layout.addWidget(self.chk_trash)
        layout.addWidget(opt_group)

        # 4. 実行・中断ボタンとプログレスバー
        action_layout = QHBoxLayout()
        action_layout.setSpacing(10)
        self.btn_run = QPushButton("▶ XMP抽出＆RAW引き継ぎを実行")
        self.btn_run.setObjectName("primaryButton")
        self.btn_run.setMinimumHeight(44)
        self.btn_run.clicked.connect(self.start_process)

        self.btn_cancel = QPushButton("■ 中断")
        self.btn_cancel.setMinimumHeight(44)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_process)

        action_layout.addWidget(self.btn_run, stretch=4)
        action_layout.addWidget(self.btn_cancel, stretch=1)
        layout.addLayout(action_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.status_label = QLabel("待機中")
        self.status_label.setObjectName("statusLabel")
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)

        # 5. ログ出力エリア
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 10))
        layout.addWidget(self.log_view, stretch=1)

    def set_folder_path(self, path: Path):
        self.path_edit.setText(str(path))
        self.log_view.appendPlainText(f"フォルダ指定: {path}")

    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "作業フォルダを選択")
        if folder:
            self.set_folder_path(Path(folder))

    def start_process(self):
        folder_text = self.path_edit.text().strip()
        if not folder_text:
            QMessageBox.warning(self, "確認", "作業フォルダを指定してください。")
            return

        folder_path = Path(folder_text)
        self.btn_run.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setValue(0)
        self.log_view.clear()
        self.log_view.appendPlainText("=== 処理を開始します ===")

        self.worker = SyncWorker(
            folder_path=folder_path,
            exiftool_path=None,
            auto_aspect_crop=self.chk_aspect.isChecked(),
            adjust_mask_coords=self.chk_mask.isChecked(),
            trash_source_dng=self.chk_trash.isChecked()
        )
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_result.connect(self.on_finished)
        self.worker.start()

    def cancel_process(self):
        if self.worker and self.worker.isRunning():
            self.status_label.setText("中断リクエスト送信中...")
            self.worker.cancel()

    def on_progress(self, current: int, total: int, message: str):
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
        self.status_label.setText(message)

    def on_finished(self, res: ProcessResult):
        self.btn_run.setEnabled(True)
        self.btn_cancel.setEnabled(False)

        for line in res.logs:
            self.log_view.appendPlainText(line)
        for err in res.errors:
            self.log_view.appendPlainText(err)

        summary = (
            f"\n=== 処理完了 ===\n"
            f"・成功: {len(res.success_files)} 件\n"
            f"・警告/未処理スキップ: {len(res.warnings)} 件\n"
            f"・ORFマッチなし: {len(res.unmatched_xmp)} 件\n"
            f"・連番衝突スキップ: {len(res.conflicts)} 件\n"
            f"・エラー: {len(res.errors)} 件"
        )
        if res.cancelled:
            summary += "\n※ユーザー操作により途中中断されました。"

        self.log_view.appendPlainText(summary)
        self.status_label.setText(f"完了: 成功 {len(res.success_files)}件 / 警告 {len(res.warnings)}件 / エラー {len(res.errors)}件")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Yu Gothic UI", 10))
    app.setStyleSheet(DARK_QSS)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
