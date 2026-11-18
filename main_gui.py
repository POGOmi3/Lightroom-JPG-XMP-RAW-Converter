import sys
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QFont
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QVBoxLayout, QWidget, QGroupBox
)

from core import XmpSyncCore, ProcessResult


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
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAcceptDrops(True)
        self.setMinimumHeight(110)
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #666;
                border-radius: 8px;
                background-color: #252526;
                color: #ddd;
                font-size: 13px;
                padding: 16px;
            }
            QLabel:hover {
                border-color: #007acc;
                background-color: #2d2d30;
            }
        """)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
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
        layout.setSpacing(10)

        # 1. ドロップエリア
        self.drop_label = DropAreaLabel()
        self.drop_label.folder_dropped.connect(self.set_folder_path)
        layout.addWidget(self.drop_label)

        # 2. フォルダパス選択行
        path_layout = QHBoxLayout()
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
        self.btn_run = QPushButton("▶ XMP抽出＆RAW引き継ぎを実行")
        self.btn_run.setMinimumHeight(40)
        self.btn_run.setStyleSheet("font-weight: bold; font-size: 14px; background-color: #0e639c; color: white;")
        self.btn_run.clicked.connect(self.start_process)

        self.btn_cancel = QPushButton("■ 中断")
        self.btn_cancel.setMinimumHeight(40)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_process)

        action_layout.addWidget(self.btn_run, stretch=4)
        action_layout.addWidget(self.btn_cancel, stretch=1)
        layout.addLayout(action_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.status_label = QLabel("待機中")
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
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
