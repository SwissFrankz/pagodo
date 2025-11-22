"""
Pagodo GUI - Advanced Google Dorking Tool with PyQt6
A powerful, user-friendly interface for automated Google dork searching
"""


import sys
import json
import re
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import urlparse, parse_qs, unquote
from bs4 import BeautifulSoup

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QLineEdit, QPushButton, QTextEdit, QSpinBox,
    QCheckBox, QFileDialog, QGroupBox, QTableWidget, QTableWidgetItem,
    QProgressBar, QStatusBar, QMessageBox, QListWidget, QHeaderView
)
from PyQt6.QtCore import QThread, pyqtSignal


class DorkScraperThread(QThread):
    """Thread for scraping dorks from GHDB."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def run(self):
        try:
            self.progress.emit("Fetching latest dorks from GHDB...")
            dorks_dict = self.scrape_ghdb()
            self.finished.emit(dorks_dict)
        except Exception as exc:  # pragma: no cover - network/GUI path
            self.error.emit(f"Error scraping dorks: {exc}")

    def scrape_ghdb(self) -> Dict:
        """Scrape Google dorks from GHDB."""
        categories = {
            1: "Footholds",
            2: "File Containing Usernames",
            3: "Sensitive Directories",
            4: "Web Server Detection",
            5: "Vulnerable Files",
            6: "Vulnerable Servers",
            7: "Error Messages",
            8: "File Containing Juicy Info",
            9: "File Containing Passwords",
            10: "Sensitive Online Shopping Info",
            11: "Network or Vulnerability Data",
            12: "Pages Containing Login Portals",
            13: "Various Online Devices",
            14: "Advisories and Vulnerabilities",
        }

        all_dorks: List[str] = []
        category_dict: Dict[int, Dict[str, object]] = {}

        for cat_id, cat_name in categories.items():
            self.progress.emit(f"Scraping category: {cat_name}")
            url = f"https://www.exploit-db.com/google-hacking-database?category={cat_id}"

            try:
                response = requests.get(url, timeout=30)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")
                    dork_elements = soup.find_all("td", class_="dork")
                    category_dorks = [elem.text.strip() for elem in dork_elements if elem.text.strip()]

                    all_dorks.extend(category_dorks)
                    category_dict[cat_id] = {
                        "category_name": cat_name,
                        "dorks": category_dorks,
                        "count": len(category_dorks),
                    }

                    time.sleep(1)
            except Exception as exc:  # pragma: no cover - network/GUI path
                self.progress.emit(
                    f"Warning: Could not scrape category {cat_name}: {exc}"
                )

        return {
            "total_dorks": len(all_dorks),
            "extracted_dorks": all_dorks,
            "category_dict": category_dict,
        }


class DorkSearchThread(QThread):
    """Thread for executing dork searches."""

    progress = pyqtSignal(str, int, int)  # message, current, total
    result = pyqtSignal(dict)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, dorks: List[str], domain: str, proxies: List[str],
                 max_results: int, min_delay: int, max_delay: int):
        super().__init__()
        self.dorks = dorks
        self.domain = domain
        self.proxies = proxies
        self.max_results = max_results
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.running = True

    def run(self):  # pragma: no cover - network/GUI path
        try:
            total_dorks = len(self.dorks)
            proxy_index = 0

            for idx, dork in enumerate(self.dorks):
                if not self.running:
                    break

                self.progress.emit(f"Searching: {dork}", idx + 1, total_dorks)
                query = f"{dork} site:{self.domain}" if self.domain else dork

                proxy = None
                if self.proxies:
                    proxy = self.proxies[proxy_index % len(self.proxies)]
                    proxy_index += 1

                urls = self.google_search(query, proxy, self.max_results)

                self.result.emit({"dork": dork, "urls": urls, "count": len(urls)})

                import random
                time.sleep(random.uniform(self.min_delay, self.max_delay))

            self.finished.emit()
        except Exception as exc:
            self.error.emit(f"Search error: {exc}")

    def google_search(self, query: str, proxy: Optional[str], max_results: int) -> List[str]:
        """Perform a simplified Google search and return URLs."""
        urls: List[str] = []

        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }

            proxies_dict = None
            if proxy:
                proxies_dict = {"http": proxy, "https": proxy}

            search_url = f"https://www.google.com/search?q={query}&num={min(max_results, 100)}"
            response = requests.get(search_url, headers=headers, proxies=proxies_dict, timeout=30)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")

                for link in soup.find_all("a"):
                    href = link.get("href", "")
                    if "/url?q=" in href:
                        url = href.split("/url?q=")[1].split("&")[0]
                        url = unquote(url)
                        if url.startswith("http"):
                            urls.append(url)
                            if len(urls) >= max_results:
                                break
        except Exception as exc:  # pragma: no cover - network/GUI path
            print(f"Search error: {exc}")

        return urls

    def stop(self):
        self.running = False


class ParameterExtractor:
    """Extract parameters and patterns from URLs."""

    @staticmethod
    def extract_parameters(url: str) -> Dict:
        """Extract all parameters from a URL."""
        try:
            parsed = urlparse(url)
            params = parse_qs(parsed.query)

            flat_params: Dict[str, object] = {}
            for key, value in params.items():
                flat_params[key] = value[0] if len(value) == 1 else value

            return {
                "url": url,
                "scheme": parsed.scheme,
                "domain": parsed.netloc,
                "path": parsed.path,
                "parameters": flat_params,
                "fragment": parsed.fragment,
            }
        except Exception as exc:
            return {"error": str(exc)}

    @staticmethod
    def extract_sql_patterns(url: str) -> List[str]:
        """Detect potential SQL injection points."""
        patterns = [r"id=\d+", r"page=\d+", r"cat=\d+", r"item=\d+", r"article=\d+", r"product=\d+"]

        return [pattern for pattern in patterns if re.search(pattern, url)]

    @staticmethod
    def is_database_url(url: str) -> bool:
        """Check if URL likely leads to database content."""
        db_indicators = [
            "php",
            "asp",
            "aspx",
            "jsp",
            "id=",
            "page=",
            "cat=",
            "item=",
            "user=",
            "product=",
            "article=",
            "view=",
            "content=",
            "show=",
        ]

        url_lower = url.lower()
        return any(indicator in url_lower for indicator in db_indicators)


class PagodoGUI(QMainWindow):
    """Main GUI application."""

    def __init__(self):
        super().__init__()
        self.dorks: List[str] = []
        self.search_results: List[Dict[str, object]] = []
        self.database_urls: List[str] = []
        self.init_ui()

    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Pagodo Advanced - Google Dorking Tool")
        self.setMinimumSize(1200, 800)

        self.setStyleSheet(
            """
            QMainWindow { background-color: #2b2b2b; }
            QTabWidget::pane { border: 1px solid #3d3d3d; background-color: #2b2b2b; }
            QTabBar::tab { background-color: #3d3d3d; color: #ffffff; padding: 10px 20px; margin-right: 2px; }
            QTabBar::tab:selected { background-color: #4d4d4d; }
            QGroupBox { color: #ffffff; border: 1px solid #3d3d3d; margin-top: 10px; font-weight: bold; }
            QGroupBox::title { subcontrol-origin: margin; padding: 0 5px; }
            QLabel { color: #ffffff; }
            QLineEdit, QTextEdit, QSpinBox, QComboBox { background-color: #3d3d3d; color: #ffffff; border: 1px solid #5d5d5d; padding: 5px; }
            QPushButton { background-color: #0d7377; color: #ffffff; border: none; padding: 8px 15px; font-weight: bold; }
            QPushButton:hover { background-color: #14a3a8; }
            QPushButton:pressed { background-color: #0a5d61; }
            QPushButton:disabled { background-color: #3d3d3d; color: #7d7d7d; }
            QTableWidget { background-color: #3d3d3d; color: #ffffff; gridline-color: #5d5d5d; }
            QHeaderView::section { background-color: #4d4d4d; color: #ffffff; padding: 5px; border: 1px solid #5d5d5d; }
            QProgressBar { border: 1px solid #5d5d5d; background-color: #3d3d3d; text-align: center; color: #ffffff; }
            QProgressBar::chunk { background-color: #0d7377; }
            QListWidget { background-color: #3d3d3d; color: #ffffff; border: 1px solid #5d5d5d; }
            """
        )

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self.create_main_tab()
        self.create_dorks_tab()
        self.create_proxy_tab()
        self.create_results_tab()
        self.create_parameter_tab()
        self.create_database_tab()

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def create_main_tab(self):
        """Create main control tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        config_group = QGroupBox("Search Configuration")
        config_layout = QVBoxLayout()

        domain_layout = QHBoxLayout()
        domain_layout.addWidget(QLabel("Target Domain:"))
        self.domain_input = QLineEdit()
        self.domain_input.setPlaceholderText("example.com (leave empty for all)")
        domain_layout.addWidget(self.domain_input)
        config_layout.addLayout(domain_layout)

        keywords_layout = QHBoxLayout()
        keywords_layout.addWidget(QLabel("Keywords File:"))
        self.keywords_input = QLineEdit()
        self.keywords_input.setPlaceholderText("Select keywords file...")
        keywords_layout.addWidget(self.keywords_input)
        browse_keywords_btn = QPushButton("Browse")
        browse_keywords_btn.clicked.connect(self.browse_keywords)
        keywords_layout.addWidget(browse_keywords_btn)
        config_layout.addLayout(keywords_layout)

        params_layout = QHBoxLayout()
        params_layout.addWidget(QLabel("Max Results per Dork:"))
        self.max_results_spin = QSpinBox()
        self.max_results_spin.setRange(1, 1000)
        self.max_results_spin.setValue(50)
        params_layout.addWidget(self.max_results_spin)

        params_layout.addWidget(QLabel("Min Delay (s):"))
        self.min_delay_spin = QSpinBox()
        self.min_delay_spin.setRange(1, 60)
        self.min_delay_spin.setValue(2)
        params_layout.addWidget(self.min_delay_spin)

        params_layout.addWidget(QLabel("Max Delay (s):"))
        self.max_delay_spin = QSpinBox()
        self.max_delay_spin.setRange(1, 120)
        self.max_delay_spin.setValue(5)
        params_layout.addWidget(self.max_delay_spin)

        config_layout.addLayout(params_layout)

        config_group.setLayout(config_layout)
        layout.addWidget(config_group)

        control_layout = QHBoxLayout()

        self.fetch_dorks_btn = QPushButton("Fetch Latest Dorks")
        self.fetch_dorks_btn.clicked.connect(self.fetch_dorks)
        control_layout.addWidget(self.fetch_dorks_btn)

        self.start_search_btn = QPushButton("Start Search")
        self.start_search_btn.clicked.connect(self.start_search)
        self.start_search_btn.setEnabled(False)
        control_layout.addWidget(self.start_search_btn)

        self.stop_search_btn = QPushButton("Stop Search")
        self.stop_search_btn.clicked.connect(self.stop_search)
        self.stop_search_btn.setEnabled(False)
        control_layout.addWidget(self.stop_search_btn)

        layout.addLayout(control_layout)

        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout()

        self.progress_bar = QProgressBar()
        progress_layout.addWidget(self.progress_bar)

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(200)
        progress_layout.addWidget(self.status_text)

        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)

        layout.addStretch()
        self.tabs.addTab(tab, "Main")

    def create_dorks_tab(self):
        """Create dorks management tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        info_layout = QHBoxLayout()
        self.dorks_count_label = QLabel("Dorks loaded: 0")
        info_layout.addWidget(self.dorks_count_label)
        info_layout.addStretch()

        save_btn = QPushButton("Save Dorks")
        save_btn.clicked.connect(self.save_dorks)
        info_layout.addWidget(save_btn)

        load_btn = QPushButton("Load Dorks")
        load_btn.clicked.connect(self.load_dorks)
        info_layout.addWidget(load_btn)

        layout.addLayout(info_layout)

        self.dorks_list = QListWidget()
        layout.addWidget(self.dorks_list)

        self.tabs.addTab(tab, "Dorks")

    def create_proxy_tab(self):
        """Create proxy configuration tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        proxy_group = QGroupBox("Proxy Configuration")
        proxy_layout = QVBoxLayout()

        self.enable_proxy_check = QCheckBox("Enable Proxies")
        proxy_layout.addWidget(self.enable_proxy_check)

        proxy_layout.addWidget(QLabel("Proxy List (one per line):"))
        proxy_layout.addWidget(
            QLabel("Formats: http://host:port, https://host:port, socks5://host:port")
        )

        self.proxy_text = QTextEdit()
        self.proxy_text.setPlaceholderText(
            "http://proxy1.com:8080\n"
            "https://proxy2.com:8080\n"
            "socks5://127.0.0.1:9050\n"
            "socks5://127.0.0.1:9051"
        )
        proxy_layout.addWidget(self.proxy_text)

        proxy_file_layout = QHBoxLayout()
        proxy_file_layout.addWidget(QLabel("Load from file:"))
        self.proxy_file_input = QLineEdit()
        proxy_file_layout.addWidget(self.proxy_file_input)

        browse_proxy_btn = QPushButton("Browse")
        browse_proxy_btn.clicked.connect(self.browse_proxy_file)
        proxy_file_layout.addWidget(browse_proxy_btn)

        load_proxy_btn = QPushButton("Load")
        load_proxy_btn.clicked.connect(self.load_proxy_file)
        proxy_file_layout.addWidget(load_proxy_btn)

        proxy_layout.addLayout(proxy_file_layout)

        proxy_group.setLayout(proxy_layout)
        layout.addWidget(proxy_group)

        self.tabs.addTab(tab, "Proxies")

    def create_results_tab(self):
        """Create results display tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        info_layout = QHBoxLayout()
        self.results_count_label = QLabel("Results: 0")
        info_layout.addWidget(self.results_count_label)
        info_layout.addStretch()

        export_btn = QPushButton("Export Results")
        export_btn.clicked.connect(self.export_results)
        info_layout.addWidget(export_btn)

        clear_btn = QPushButton("Clear Results")
        clear_btn.clicked.connect(self.clear_results)
        info_layout.addWidget(clear_btn)

        layout.addLayout(info_layout)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(3)
        self.results_table.setHorizontalHeaderLabels(["Dork", "URL", "Parameters"])
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.results_table)

        self.tabs.addTab(tab, "Results")

    def create_parameter_tab(self):
        """Create parameter extraction tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        input_group = QGroupBox("URL Analysis")
        input_layout = QVBoxLayout()

        input_layout.addWidget(QLabel("Enter URL to analyze:"))
        self.param_url_input = QLineEdit()
        input_layout.addWidget(self.param_url_input)

        analyze_btn = QPushButton("Analyze URL")
        analyze_btn.clicked.connect(self.analyze_url)
        input_layout.addWidget(analyze_btn)

        input_group.setLayout(input_layout)
        layout.addWidget(input_group)

        results_group = QGroupBox("Analysis Results")
        results_layout = QVBoxLayout()

        self.param_results = QTextEdit()
        self.param_results.setReadOnly(True)
        results_layout.addWidget(self.param_results)

        results_group.setLayout(results_layout)
        layout.addWidget(results_group)

        self.tabs.addTab(tab, "Parameter Extractor")

    def create_database_tab(self):
        """Create database URLs tab."""
        tab = QWidget()
        layout = QVBoxLayout(tab)

        info_layout = QHBoxLayout()
        self.db_count_label = QLabel("Database URLs: 0")
        info_layout.addWidget(self.db_count_label)
        info_layout.addStretch()

        filter_btn = QPushButton("Filter Database URLs")
        filter_btn.clicked.connect(self.filter_database_urls)
        info_layout.addWidget(filter_btn)

        export_db_btn = QPushButton("Export Database URLs")
        export_db_btn.clicked.connect(self.export_database_urls)
        info_layout.addWidget(export_db_btn)

        layout.addLayout(info_layout)

        self.db_urls_list = QListWidget()
        layout.addWidget(self.db_urls_list)

        self.tabs.addTab(tab, "Database URLs")

    def browse_keywords(self):
        """Browse for keywords file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Keywords File", "", "Text Files (*.txt);;All Files (*.*)"
        )
        if file_path:
            self.keywords_input.setText(file_path)

    def browse_proxy_file(self):
        """Browse for proxy file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Proxy File", "", "Text Files (*.txt);;All Files (*.*)"
        )
        if file_path:
            self.proxy_file_input.setText(file_path)

    def load_proxy_file(self):
        """Load proxies from file."""
        file_path = self.proxy_file_input.text()
        if file_path and Path(file_path).exists():
            try:
                with open(file_path, "r", encoding="utf-8") as proxy_file:
                    proxies = proxy_file.read()
                self.proxy_text.setText(proxies)
                self.log_status(f"Loaded proxies from {file_path}")
            except Exception as exc:
                QMessageBox.warning(self, "Error", f"Failed to load proxy file: {exc}")

    def fetch_dorks(self):
        """Fetch latest dorks from GHDB."""
        self.fetch_dorks_btn.setEnabled(False)
        self.log_status("Starting dork scraper...")

        self.scraper_thread = DorkScraperThread()
        self.scraper_thread.progress.connect(self.log_status)
        self.scraper_thread.finished.connect(self.on_dorks_fetched)
        self.scraper_thread.error.connect(self.on_scraper_error)
        self.scraper_thread.start()

    def on_dorks_fetched(self, dorks_dict):
        """Handle fetched dorks."""
        self.dorks = dorks_dict.get("extracted_dorks", [])
        self.update_dorks_display()
        self.log_status(f"Fetched {len(self.dorks)} dorks successfully!")
        self.fetch_dorks_btn.setEnabled(True)
        self.start_search_btn.setEnabled(len(self.dorks) > 0)

    def on_scraper_error(self, error_msg):
        """Handle scraper error."""
        self.log_status(f"Error: {error_msg}")
        self.fetch_dorks_btn.setEnabled(True)
        QMessageBox.warning(self, "Scraper Error", error_msg)

    def update_dorks_display(self):
        """Update dorks list display."""
        self.dorks_list.clear()
        for dork in self.dorks:
            self.dorks_list.addItem(dork)
        self.dorks_count_label.setText(f"Dorks loaded: {len(self.dorks)}")

    def save_dorks(self):
        """Save dorks to file."""
        if not self.dorks:
            QMessageBox.warning(self, "No Dorks", "No dorks to save!")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Dorks", "dorks.txt", "Text Files (*.txt);;All Files (*.*)"
        )

        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as dorks_file:
                    dorks_file.write("\n".join(self.dorks))
                self.log_status(f"Saved {len(self.dorks)} dorks to {file_path}")
            except Exception as exc:
                QMessageBox.warning(self, "Error", f"Failed to save dorks: {exc}")

    def load_dorks(self):
        """Load dorks from file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Load Dorks", "", "Text Files (*.txt);;All Files (*.*)"
        )

        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as dorks_file:
                    self.dorks = [line.strip() for line in dorks_file if line.strip()]
                self.update_dorks_display()
                self.start_search_btn.setEnabled(len(self.dorks) > 0)
                self.log_status(f"Loaded {len(self.dorks)} dorks from {file_path}")
            except Exception as exc:
                QMessageBox.warning(self, "Error", f"Failed to load dorks: {exc}")

    def start_search(self):
        """Start dork search."""
        if not self.dorks:
            QMessageBox.warning(self, "No Dorks", "Please fetch or load dorks first!")
            return

        domain = self.domain_input.text().strip()

        proxies: List[str] = []
        if self.enable_proxy_check.isChecked():
            proxy_text = self.proxy_text.toPlainText().strip()
            if proxy_text:
                proxies = [proxy.strip() for proxy in proxy_text.split("\n") if proxy.strip()]

        self.search_results.clear()
        self.results_table.setRowCount(0)

        self.search_thread = DorkSearchThread(
            self.dorks,
            domain,
            proxies,
            self.max_results_spin.value(),
            self.min_delay_spin.value(),
            self.max_delay_spin.value(),
        )

        self.search_thread.progress.connect(self.on_search_progress)
        self.search_thread.result.connect(self.on_search_result)
        self.search_thread.finished.connect(self.on_search_finished)
        self.search_thread.error.connect(self.on_search_error)

        self.start_search_btn.setEnabled(False)
        self.stop_search_btn.setEnabled(True)
        self.fetch_dorks_btn.setEnabled(False)

        self.search_thread.start()

    def stop_search(self):
        """Stop search."""
        if hasattr(self, "search_thread"):
            self.search_thread.stop()
            self.log_status("Stopping search...")

    def on_search_progress(self, message, current, total):
        """Update search progress."""
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.log_status(f"[{current}/{total}] {message}")

    def on_search_result(self, result):
        """Handle search result."""
        dork = result["dork"]
        urls = result["urls"]

        for url in urls:
            params = ParameterExtractor.extract_parameters(url).get("parameters", {})
            self.search_results.append({"dork": dork, "url": url, "parameters": params})
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            self.results_table.setItem(row, 0, QTableWidgetItem(dork))
            self.results_table.setItem(row, 1, QTableWidgetItem(url))
            self.results_table.setItem(
                row,
                2,
                QTableWidgetItem(", ".join(f"{key}={value}" for key, value in params.items())),
            )
            if ParameterExtractor.is_database_url(url):
                self.database_urls.append(url)
                self.db_urls_list.addItem(url)
                self.db_count_label.setText(f"Database URLs: {len(self.database_urls)}")
        self.results_count_label.setText(f"Results: {len(self.search_results)}")

    def on_search_finished(self):
        """Handle search completion."""
        self.log_status("Search completed")
        self.status_bar.showMessage("Search completed")
        self.start_search_btn.setEnabled(True)
        self.stop_search_btn.setEnabled(False)
        self.fetch_dorks_btn.setEnabled(True)
        QMessageBox.information(self, "Search complete", "Dork search finished")

    def on_search_error(self, error_msg: str):
        """Handle search error."""
        self.log_status(f"Error: {error_msg}")
        self.status_bar.showMessage("Search error")
        self.start_search_btn.setEnabled(True)
        self.stop_search_btn.setEnabled(False)
        self.fetch_dorks_btn.setEnabled(True)
        QMessageBox.critical(self, "Search error", error_msg)

    def export_results(self):
        """Export search results to JSON."""
        if not self.search_results:
            QMessageBox.information(self, "No results", "There are no results to export yet")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Results", "search_results.json", "JSON Files (*.json);;All Files (*.*)"
        )
        if not file_path:
            return

        try:
            with open(file_path, "w", encoding="utf-8") as results_file:
                json.dump(self.search_results, results_file, indent=2)
            self.log_status(f"Exported {len(self.search_results)} results to {file_path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", f"Failed to export results: {exc}")

    def clear_results(self):
        """Clear in-memory results and tables."""
        self.search_results.clear()
        self.database_urls.clear()
        self.results_table.setRowCount(0)
        self.db_urls_list.clear()
        self.db_count_label.setText("Database URLs: 0")
        self.results_count_label.setText("Results: 0")
        self.log_status("Cleared search results")

    def filter_database_urls(self):
        """Remove duplicate database URLs and refresh list."""
        unique_urls = list(dict.fromkeys(self.database_urls))
        if len(unique_urls) != len(self.database_urls):
            self.database_urls = unique_urls
        self.db_urls_list.clear()
        for url in self.database_urls:
            self.db_urls_list.addItem(url)
        self.db_count_label.setText(f"Database URLs: {len(self.database_urls)}")
        self.log_status("Filtered database URLs for duplicates")

    def export_database_urls(self):
        """Export database-like URLs to a text file."""
        if not self.database_urls:
            QMessageBox.information(self, "No database URLs", "No database URLs detected yet")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Database URLs", "database_urls.txt", "Text Files (*.txt);;All Files (*.*)"
        )
        if not file_path:
            return
        try:
            with open(file_path, "w", encoding="utf-8") as db_file:
                db_file.write("\n".join(self.database_urls))
            self.log_status(f"Exported {len(self.database_urls)} database URLs to {file_path}")
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", f"Failed to export database URLs: {exc}")

    def analyze_url(self):
        """Analyze single URL for parameters and patterns."""
        url = self.param_url_input.text().strip()
        if not url:
            QMessageBox.information(self, "No URL", "Please enter a URL to analyze")
            return
        info = ParameterExtractor.extract_parameters(url)
        sql_patterns = ParameterExtractor.extract_sql_patterns(url)
        is_db = ParameterExtractor.is_database_url(url)

        lines = ["URL Analysis Results:"]
        if "error" in info:
            lines.append(f"Error parsing URL: {info['error']}")
        else:
            lines.append(f"URL: {info['url']}")
            lines.append(f"Scheme: {info['scheme']}")
            lines.append(f"Domain: {info['domain']}")
            lines.append(f"Path: {info['path']}")
            lines.append(f"Fragment: {info['fragment']}")
            lines.append("Parameters:")
            if info["parameters"]:
                for key, value in info["parameters"].items():
                    lines.append(f"  {key} = {value}")
            else:
                lines.append("  None detected")

        if sql_patterns:
            lines.append("Potential SQLi indicators detected:")
            lines.extend([f"  Pattern: {pattern}" for pattern in sql_patterns])
        if is_db:
            lines.append("Database-style URL detected")
            if url not in self.database_urls:
                self.database_urls.append(url)
                self.db_urls_list.addItem(url)
                self.db_count_label.setText(f"Database URLs: {len(self.database_urls)}")

        self.param_results.setPlainText("\n".join(lines))

    def log_status(self, message: str):
        """Append status text to the progress console."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.status_text.append(f"[{timestamp}] {message}")
        self.status_bar.showMessage(message)


def main():
    app = QApplication(sys.argv)
    gui = PagodoGUI()
    gui.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
