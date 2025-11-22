"""PyQt5 GUI for keeping GHDB dorks current and running pagodo searches.

The interface wraps the existing pagodo modules so users can update GHDB
dorks, pick a dork file, and launch pagodo searches without using the CLI.
All long-running tasks execute in background threads to keep the UI
responsive.
"""

import argparse
import logging
import os
import shutil
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QDoubleSpinBox,
)

from ghdb_scraper import retrieve_google_dorks
from pagodo import Pagodo


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DORKS_DIR = BASE_DIR / "dorks"


@contextmanager
def change_working_directory(path: Path) -> Iterable[None]:
    """Temporarily change the working directory."""

    original_cwd = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(original_cwd)


class GuiLogHandler(logging.Handler):
    """Logging handler that forwards pagodo logs to the GUI."""

    def __init__(self, signal: pyqtSignal):
        super().__init__()
        self.signal = signal

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - GUI wiring
        msg = self.format(record)
        self.signal.emit(msg)


class ScrapeWorker(QObject):
    """Worker object to download GHDB dorks without blocking the UI."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(Path)
    failed = pyqtSignal(str)

    def __init__(self, target_dir: Path):
        super().__init__()
        self.target_dir = target_dir

    def run(self) -> None:  # pragma: no cover - thread target
        try:
            self.progress.emit("Starting GHDB scrape. This may take a moment…")
            DEFAULT_DORKS_DIR.mkdir(parents=True, exist_ok=True)

            with change_working_directory(BASE_DIR):
                retrieve_google_dorks(save_all_dorks_to_file=True)

            downloaded_file = DEFAULT_DORKS_DIR / "all_google_dorks.txt"
            if not downloaded_file.exists():
                raise FileNotFoundError("Expected all_google_dorks.txt was not created")

            if self.target_dir != DEFAULT_DORKS_DIR:
                self.target_dir.mkdir(parents=True, exist_ok=True)
                destination = self.target_dir / downloaded_file.name
                shutil.copy2(downloaded_file, destination)
                self.progress.emit(f"Copied updated dorks to: {destination}")
                downloaded_file = destination

            self.finished.emit(downloaded_file)
        except Exception as exc:  # pragma: no cover - thread target
            self.failed.emit(str(exc))


@dataclass
class PagodoConfig:
    """Container for pagodo search configuration."""

    google_dorks_file: Path
    domain: str
    max_results: int
    proxies: str
    save_json_path: Optional[str]
    save_urls_path: Optional[str]
    min_delay: float
    max_delay: float
    disable_verify_ssl: bool
    verbosity: int


class PagodoWorker(QObject):
    """Runs pagodo searches on a background thread."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(dict, PagodoConfig)
    failed = pyqtSignal(str)

    def __init__(self, config: PagodoConfig):
        super().__init__()
        self.config = config

    def _configure_logger(self) -> GuiLogHandler:
        logger = logging.getLogger("pagodo")
        logger.setLevel((6 - self.config.verbosity) * 10)
        handler = GuiLogHandler(self.progress)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(handler)
        return handler

    def run(self) -> None:  # pragma: no cover - thread target
        try:
            handler = self._configure_logger()
            self.progress.emit("Starting pagodo search…")

            searcher = Pagodo(
                google_dorks_file=str(self.config.google_dorks_file),
                domain=self.config.domain,
                max_search_result_urls_to_return_per_dork=self.config.max_results,
                proxies=self.config.proxies,
                save_pagodo_results_to_json_file=self.config.save_json_path,
                save_urls_to_file=self.config.save_urls_path,
                minimum_delay_between_dork_searches_in_seconds=self.config.min_delay,
                maximum_delay_between_dork_searches_in_seconds=self.config.max_delay,
                disable_verify_ssl=self.config.disable_verify_ssl,
                verbosity=self.config.verbosity,
            )

            results = searcher.go()
            self.progress.emit("Search complete.")
            self.finished.emit(results, self.config)
        except Exception as exc:  # pragma: no cover - thread target
            self.failed.emit(str(exc))
        finally:
            logger = logging.getLogger("pagodo")
            for handler in list(logger.handlers):
                if isinstance(handler, GuiLogHandler):
                    logger.removeHandler(handler)


class PagodoGUI(QMainWindow):
    """PyQt5 GUI that helps users keep dork files current and run searches."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("pagodo - Dork Manager & Runner")
        self.resize(780, 620)

        self.thread: Optional[QThread] = None
        self.worker: Optional[QObject] = None

        # Dork management widgets
        self.dorks_dir_input = QLineEdit(str(DEFAULT_DORKS_DIR))
        self.dork_selector = QComboBox()

        # Search parameter widgets
        self.domain_input = QLineEdit()
        self.max_results_spin = QSpinBox()
        self.max_results_spin.setRange(1, 1000)
        self.max_results_spin.setValue(100)

        self.min_delay_spin = QDoubleSpinBox()
        self.min_delay_spin.setRange(0.1, 600.0)
        self.min_delay_spin.setValue(37.0)
        self.min_delay_spin.setSingleStep(0.5)

        self.max_delay_spin = QDoubleSpinBox()
        self.max_delay_spin.setRange(0.1, 600.0)
        self.max_delay_spin.setValue(60.0)
        self.max_delay_spin.setSingleStep(0.5)

        self.proxies_input = QLineEdit()
        self.proxies_input.setPlaceholderText("http://proxy1:8080, socks5://proxy2:1080")

        self.save_json_checkbox = QCheckBox("Save JSON results")
        self.save_json_path = QLineEdit()
        self.save_json_path.setPlaceholderText("Leave blank to auto-name the JSON file")

        self.save_urls_checkbox = QCheckBox("Save URLs to text file")
        self.save_urls_path = QLineEdit()
        self.save_urls_path.setPlaceholderText("Leave blank to auto-name the text file")

        self.disable_ssl_checkbox = QCheckBox("Disable SSL verification")
        self.verbosity_spin = QSpinBox()
        self.verbosity_spin.setRange(1, 5)
        self.verbosity_spin.setValue(4)

        # Status and logging widgets
        self.status_label = QLabel("Select a dork file, configure search options, then click 'Run pagodo search'.")
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)

        # Buttons
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self.choose_directory)

        refresh_button = QPushButton("Refresh list")
        refresh_button.clicked.connect(self.populate_dork_selector)

        update_button = QPushButton("Update dorks from GHDB")
        update_button.clicked.connect(self.start_scrape)
        self.update_button = update_button

        run_button = QPushButton("Run pagodo search")
        run_button.clicked.connect(self.start_search)
        self.run_button = run_button

        json_browse = QPushButton("Browse…")
        json_browse.clicked.connect(lambda: self.choose_output_path(self.save_json_path))
        json_browse.setEnabled(False)
        self.save_json_checkbox.toggled.connect(lambda checked: json_browse.setEnabled(checked))
        self.save_json_checkbox.toggled.connect(self.save_json_path.setEnabled)
        self.save_json_path.setEnabled(False)

        urls_browse = QPushButton("Browse…")
        urls_browse.clicked.connect(lambda: self.choose_output_path(self.save_urls_path))
        urls_browse.setEnabled(False)
        self.save_urls_checkbox.toggled.connect(lambda checked: urls_browse.setEnabled(checked))
        self.save_urls_checkbox.toggled.connect(self.save_urls_path.setEnabled)
        self.save_urls_path.setEnabled(False)

        # Layout assembly
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Dorks directory:"))
        top_row.addWidget(self.dorks_dir_input)
        top_row.addWidget(browse_button)

        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Dork file:"))
        selector_row.addWidget(self.dork_selector)
        selector_row.addWidget(refresh_button)

        domain_row = QHBoxLayout()
        domain_row.addWidget(QLabel("Domain (optional):"))
        domain_row.addWidget(self.domain_input)

        results_row = QHBoxLayout()
        results_row.addWidget(QLabel("Max results per dork:"))
        results_row.addWidget(self.max_results_spin)
        results_row.addStretch()
        results_row.addWidget(QLabel("Verbosity (1-5):"))
        results_row.addWidget(self.verbosity_spin)

        delay_row = QHBoxLayout()
        delay_row.addWidget(QLabel("Min delay (s):"))
        delay_row.addWidget(self.min_delay_spin)
        delay_row.addWidget(QLabel("Max delay (s):"))
        delay_row.addWidget(self.max_delay_spin)

        proxy_row = QHBoxLayout()
        proxy_row.addWidget(QLabel("Proxies (comma separated):"))
        proxy_row.addWidget(self.proxies_input)

        json_row = QHBoxLayout()
        json_row.addWidget(self.save_json_checkbox)
        json_row.addWidget(self.save_json_path)
        json_row.addWidget(json_browse)

        urls_row = QHBoxLayout()
        urls_row.addWidget(self.save_urls_checkbox)
        urls_row.addWidget(self.save_urls_path)
        urls_row.addWidget(urls_browse)

        ssl_row = QHBoxLayout()
        ssl_row.addWidget(self.disable_ssl_checkbox)
        ssl_row.addStretch()

        layout = QVBoxLayout()
        layout.addLayout(top_row)
        layout.addLayout(selector_row)
        layout.addLayout(domain_row)
        layout.addLayout(results_row)
        layout.addLayout(delay_row)
        layout.addLayout(proxy_row)
        layout.addLayout(json_row)
        layout.addLayout(urls_row)
        layout.addLayout(ssl_row)
        layout.addWidget(run_button)
        layout.addWidget(update_button)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)
        layout.addWidget(QLabel("Activity:"))
        layout.addWidget(self.log)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.populate_dork_selector()

    def choose_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select dorks directory", str(DEFAULT_DORKS_DIR))
        if directory:
            self.dorks_dir_input.setText(directory)
            self.populate_dork_selector()

    def choose_output_path(self, target_field: QLineEdit) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Select output file", str(BASE_DIR))
        if path:
            target_field.setText(path)

    def populate_dork_selector(self) -> None:
        directory = Path(self.dorks_dir_input.text()).expanduser()
        files = self._discover_dork_files(directory)
        self.dork_selector.clear()
        if not files:
            self.dork_selector.addItem("No dork files found")
            self.dork_selector.setEnabled(False)
            self.status_label.setText(f"No dork files found in {directory}.")
        else:
            self.dork_selector.addItems([str(path) for path in files])
            self.dork_selector.setEnabled(True)
            self.status_label.setText(f"Found {len(files)} dork file(s) in {directory}.")

    def _discover_dork_files(self, directory: Path) -> List[Path]:
        if not directory.exists():
            return []
        results: List[Path] = []
        for pattern in ("*.txt", "*.dorks"):
            results.extend(sorted(directory.glob(pattern)))
        return results

    def start_scrape(self) -> None:
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self, "Update in progress", "Please wait for the current update to finish.")
            return

        target_dir = Path(self.dorks_dir_input.text()).expanduser()
        if not target_dir:
            QMessageBox.warning(self, "Invalid directory", "Please provide a valid directory for dork files.")
            return

        self.append_log(f"Using dorks directory: {target_dir}")
        self.set_busy_state(True)

        self.thread = QThread()
        self.worker = ScrapeWorker(target_dir)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.append_log)
        self.worker.finished.connect(self.scrape_complete)
        self.worker.failed.connect(self.scrape_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.failed.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        self.thread.start()
        self.status_label.setText("Downloading latest GHDB dorks…")

    def start_search(self) -> None:
        if self.thread and self.thread.isRunning():
            QMessageBox.information(self, "Task in progress", "Please wait for the current task to finish.")
            return

        dork_file = Path(self.dork_selector.currentText()).expanduser()
        if not dork_file.exists():
            QMessageBox.warning(self, "Invalid dork file", "Please select a valid dork file before running pagodo.")
            return

        if self.min_delay_spin.value() > self.max_delay_spin.value():
            QMessageBox.warning(
                self,
                "Invalid delays",
                "Minimum delay must be less than or equal to the maximum delay.",
            )
            return

        config = PagodoConfig(
            google_dorks_file=dork_file,
            domain=self.domain_input.text().strip(),
            max_results=int(self.max_results_spin.value()),
            proxies=self.proxies_input.text().strip(),
            save_json_path=self._clean_output_path(self.save_json_checkbox, self.save_json_path),
            save_urls_path=self._clean_output_path(self.save_urls_checkbox, self.save_urls_path),
            min_delay=float(self.min_delay_spin.value()),
            max_delay=float(self.max_delay_spin.value()),
            disable_verify_ssl=self.disable_ssl_checkbox.isChecked(),
            verbosity=int(self.verbosity_spin.value()),
        )

        self.append_log("Launching pagodo with current configuration…")
        self.set_busy_state(True)

        self.thread = QThread()
        self.worker = PagodoWorker(config)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.append_log)
        self.worker.finished.connect(self.search_complete)
        self.worker.failed.connect(self.search_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.failed.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        self.thread.start()
        self.status_label.setText("Running pagodo search…")

    def _clean_output_path(self, checkbox: QCheckBox, field: QLineEdit) -> Optional[str]:
        if not checkbox.isChecked():
            return None
        path = field.text().strip()
        if not path:
            return None
        output_path = Path(path).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        return str(output_path)

    def scrape_complete(self, dorks_file: Path) -> None:
        self.append_log(f"GHDB scrape complete. Latest dorks saved to: {dorks_file}")
        self.status_label.setText("Dorks updated successfully.")
        self.populate_dork_selector()
        QMessageBox.information(self, "Update complete", "Dorks have been updated successfully.")
        self.set_busy_state(False)

    def scrape_failed(self, error_message: str) -> None:
        self.append_log(f"Error updating dorks: {error_message}")
        self.status_label.setText("Failed to update dorks. See activity log for details.")
        QMessageBox.critical(self, "Update failed", error_message)
        self.set_busy_state(False)

    def search_complete(self, results: dict, config: PagodoConfig) -> None:
        total_dorks = len(results.get("dorks", {})) if isinstance(results, dict) else 0
        total_urls = 0
        if isinstance(results, dict):
            total_urls = sum(entry.get("urls_size", 0) for entry in results.get("dorks", {}).values())

        summary_parts = [f"Checked {total_dorks} dork(s)"]
        if total_urls:
            summary_parts.append(f"collected {total_urls} URL(s)")
        if config.save_urls_path:
            summary_parts.append(f"URLs saved to {config.save_urls_path}")
        if config.save_json_path:
            summary_parts.append(f"JSON saved to {config.save_json_path}")

        summary = "; ".join(summary_parts) if summary_parts else "Search complete."
        self.append_log(summary)
        self.status_label.setText(summary)
        QMessageBox.information(self, "Search complete", summary)
        self.set_busy_state(False)

    def search_failed(self, error_message: str) -> None:
        self.append_log(f"Error running pagodo: {error_message}")
        self.status_label.setText("Pagodo search failed. See activity log for details.")
        QMessageBox.critical(self, "Search failed", error_message)
        self.set_busy_state(False)

    def set_busy_state(self, busy: bool) -> None:
        self.update_button.setDisabled(busy)
        self.run_button.setDisabled(busy)
        self.progress_bar.setRange(0, 0 if busy else 1)

    def append_log(self, message: str) -> None:
        self.log.appendPlainText(message)
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())


def main() -> None:
    """Launch the GUI or run a quick offscreen smoke test."""

    parser = argparse.ArgumentParser(description="pagodo GUI helper")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help=(
            "Instantiate the GUI offscreen and exit immediately. Useful for CI or"
            " headless environments to ensure imports and widgets initialize without"
            " errors."
        ),
    )

    args, qt_args = parser.parse_known_args()
    if args.smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app = QApplication([sys.argv[0]] + qt_args)
    gui = PagodoGUI()

    if args.smoke_test:
        gui.show()
        app.processEvents()
        gui.close()
        sys.exit(0)

    gui.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
