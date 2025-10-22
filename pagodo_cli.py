#!/usr/bin/env python3
"""Interactive CLI wrapper for pagodo."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple, Union

from bs4 import BeautifulSoup
from json import JSONDecodeError

from pagodo import Pagodo, __version__


BASE_DIR = Path(__file__).resolve().parent


def clear_screen() -> None:
    """Clear the terminal screen on Windows and POSIX systems."""

    command = "cls" if os.name == "nt" else "clear"
    os.system(command)


def prompt_path(
    prompt: str,
    *,
    allow_empty: bool = False,
    must_exist: bool = False,
    suffixes: Optional[Tuple[str, ...]] = None,
) -> Optional[Path]:
    """Prompt the user for a path value."""

    while True:
        answer = input(prompt).strip().strip('"')
        if not answer:
            if allow_empty:
                return None
            print("A value is required. Please try again.\n")
            continue

        path = (BASE_DIR / answer).resolve() if not Path(answer).is_absolute() else Path(answer)

        if suffixes and path.suffix.lower() not in suffixes:
            print(f"The file must use one of the following extensions: {', '.join(suffixes)}\n")
            continue

        if must_exist and not path.exists():
            print(f"The path '{path}' does not exist. Please try again.\n")
            continue

        if path.is_dir():
            print("Directories are not supported for this option. Please provide a file path.\n")
            continue

        return path


def extract_dorks_from_json(json_path: Path) -> List[str]:
    """Extract Google dorks from a GHDB JSON export."""

    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError) as exc:
        raise ValueError(f"Unable to read JSON file: {exc}") from exc

    dorks: List[str] = []

    if isinstance(payload, dict):
        iterable = payload.get("data")
        if not isinstance(iterable, list):
            iterable = payload.get("extracted_dorks", [])
    else:
        iterable = payload

    if not isinstance(iterable, list):
        raise ValueError("Unrecognized JSON format; expected a list of dorks")

    for entry in iterable:
        if not isinstance(entry, dict):
            continue
        url_title = entry.get("url_title", "")
        if not url_title:
            continue
        soup = BeautifulSoup(url_title, "html.parser")
        anchor = soup.find("a")
        if not anchor:
            continue
        extracted = anchor.get_text(strip=True)
        if extracted:
            dorks.append(extracted)

    if not dorks:
        raise ValueError("No dorks could be extracted from the JSON file")

    return dorks


def convert_dorks_json_to_txt(json_path: Path) -> Path:
    """Convert a GHDB JSON export to a text file of dorks and return the new path."""

    dorks = extract_dorks_from_json(json_path)

    output_name = f"{json_path.stem}_converted.txt"
    output_path = json_path.with_name(output_name)
    try:
        output_path.write_text("\n".join(dorks) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Unable to write converted dorks file: {exc}") from exc

    return output_path


def prompt_int(prompt: str, *, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    """Prompt the user for an integer value."""

    while True:
        answer = input(prompt).strip()
        try:
            value = int(answer)
        except ValueError:
            print("Invalid number. Please try again.\n")
            continue

        if minimum is not None and value < minimum:
            print(f"Value must be greater than or equal to {minimum}.\n")
            continue

        if maximum is not None and value > maximum:
            print(f"Value must be less than or equal to {maximum}.\n")
            continue

        return value


def prompt_yes_no(prompt: str, *, default: bool = False) -> bool:
    """Prompt the user for a yes/no response."""

    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        answer = input(f"{prompt} {suffix} ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please respond with 'y' or 'n'.\n")


def prompt_proxies() -> str:
    """Prompt the user for proxies and return a comma-separated string."""

    print(
        "Provide proxies in a comma-separated format (e.g. https://proxy:8080,socks5h://127.0.0.1:9050).\n"
        "You can also provide a path to a text file containing one proxy per line."
    )

    while True:
        answer = input("Enter proxies or proxy file path (leave blank to disable proxies): ").strip()
        if not answer:
            return ""

        proxy_path = Path(answer)
        if not proxy_path.is_absolute():
            proxy_path = (BASE_DIR / answer).resolve()

        if proxy_path.exists() and proxy_path.is_file():
            proxies = [line.strip() for line in proxy_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            return ",".join(proxies)

        # Treat the answer as a comma-separated proxy list.
        if "," in answer or "://" in answer:
            return answer

        print("Input was neither a file nor a valid proxy string. Please try again.\n")


@dataclass
class MenuItem:
    label: str
    action: Callable[[], None]


class PagodoCLI:
    """Interactive CLI for configuring and running pagodo."""

    def __init__(self) -> None:
        self.config = {
            "google_dorks_file": None,
            "domain": "",
            "minimum_delay_between_dork_searches_in_seconds": 37,
            "maximum_delay_between_dork_searches_in_seconds": 60,
            "disable_verify_ssl": False,
            "max_search_result_urls_to_return_per_dork": 100,
            "proxies": "",
            "save_pagodo_results_to_json_file": None,
            "save_urls_to_file": None,
            "verbosity": 4,
            "specific_log_file_name": "pagodo.py.log",
        }

        self.menu_items: List[MenuItem] = [
            MenuItem("Select Google dorks file", self.set_dorks_file),
            MenuItem("Set domain filter", self.set_domain),
            MenuItem("Configure minimum delay between dork searches", self.set_minimum_delay),
            MenuItem("Configure maximum delay between dork searches", self.set_maximum_delay),
            MenuItem("Toggle SSL/TLS verification", self.toggle_ssl_verification),
            MenuItem("Set maximum results per dork", self.set_max_results),
            MenuItem("Configure proxies", self.configure_proxies),
            MenuItem("Configure JSON results file", self.configure_json_output),
            MenuItem("Configure text results file", self.configure_text_output),
            MenuItem("Set log filename", self.set_log_filename),
            MenuItem("Run pagodo", self.run_pagodo),
        ]

    def display_config(self) -> None:
        """Print the current configuration settings."""

        def format_path(value: Optional[Union[Path, str]]) -> str:
            if value in (None, "", False):
                return "Disabled"
            return str(value)

        print("\nCurrent configuration:")
        print(f"  Google dorks file: {format_path(self.config['google_dorks_file'])}")
        print(f"  Domain filter: {self.config['domain'] or 'Not set'}")
        print(
            "  Min/Max delay (seconds): "
            f"{self.config['minimum_delay_between_dork_searches_in_seconds']} / "
            f"{self.config['maximum_delay_between_dork_searches_in_seconds']}"
        )
        print(f"  Disable SSL verification: {'Yes' if self.config['disable_verify_ssl'] else 'No'}")
        print(f"  Max URLs per dork: {self.config['max_search_result_urls_to_return_per_dork']}")
        print(f"  Proxies: {self.config['proxies'] or 'None'}")
        print(f"  JSON output: {format_path(self.config['save_pagodo_results_to_json_file'])}")
        print(f"  Text output: {format_path(self.config['save_urls_to_file'])}")
        print(f"  Log filename: {self.config['specific_log_file_name']}")

    def run(self) -> None:
        """Main menu loop."""

        while True:
            clear_screen()
            print(f"pagodo interactive CLI v{__version__}\n")
            self.display_config()
            print("\nChoose an option:\n")
            for index, item in enumerate(self.menu_items, start=1):
                print(f"  {index}. {item.label}")
            print("  0. Exit")

            choice = input("\nEnter a number: ").strip()

            if choice == "0":
                print("Exiting...")
                sys.exit(0)

            try:
                selected_index = int(choice) - 1
                self.menu_items[selected_index].action()
            except (ValueError, IndexError):
                input("Invalid choice. Press Enter to continue...")

    def set_dorks_file(self) -> None:
        """Prompt for the Google dorks file."""

        while True:
            path = prompt_path(
                "Enter path to the Google dorks file (.txt or .json): ",
                must_exist=True,
                suffixes=(".txt", ".json"),
            )
            if path is None:
                return

            if path.suffix.lower() == ".json":
                try:
                    converted = convert_dorks_json_to_txt(path)
                except ValueError as exc:
                    print(f"\nFailed to convert JSON file: {exc}\n")
                    if not prompt_yes_no("Would you like to try selecting another file?", default=True):
                        input("Press Enter to continue...")
                        return
                    continue

                print(f"\nConverted '{path.name}' to '{converted.name}'.")
                print("The converted text file will be used for pagodo searches.\n")
                self.config["google_dorks_file"] = converted
                return

            self.config["google_dorks_file"] = path
            return

    def set_domain(self) -> None:
        self.config["domain"] = input("Enter domain to scope searches (leave blank for none): ").strip()

    def set_minimum_delay(self) -> None:
        self.config["minimum_delay_between_dork_searches_in_seconds"] = prompt_int(
            "Enter minimum delay in seconds (>= 0): ", minimum=0
        )

    def set_maximum_delay(self) -> None:
        minimum = self.config["minimum_delay_between_dork_searches_in_seconds"]
        self.config["maximum_delay_between_dork_searches_in_seconds"] = prompt_int(
            f"Enter maximum delay in seconds (> {minimum}): ", minimum=minimum + 1
        )

    def toggle_ssl_verification(self) -> None:
        self.config["disable_verify_ssl"] = not self.config["disable_verify_ssl"]

    def set_max_results(self) -> None:
        self.config["max_search_result_urls_to_return_per_dork"] = prompt_int(
            "Enter maximum URLs to return per dork (>= 1): ", minimum=1
        )

    def configure_proxies(self) -> None:
        self.config["proxies"] = prompt_proxies()

    def configure_json_output(self) -> None:
        if prompt_yes_no("Save results to JSON?", default=self.config["save_pagodo_results_to_json_file"] is not None):
            path = prompt_path(
                "Enter JSON file name (leave blank for automatic name): ",
                allow_empty=True,
                suffixes=(".json",),
            )
            self.config["save_pagodo_results_to_json_file"] = str(path) if path else None
        else:
            self.config["save_pagodo_results_to_json_file"] = False

    def configure_text_output(self) -> None:
        if prompt_yes_no("Save results to text file?", default=self.config["save_urls_to_file"] is not None):
            path = prompt_path(
                "Enter text file name (leave blank for automatic name): ", allow_empty=True, suffixes=(".txt",)
            )
            self.config["save_urls_to_file"] = str(path) if path else None
        else:
            self.config["save_urls_to_file"] = False

    def set_log_filename(self) -> None:
        path = prompt_path("Enter log filename (leave blank for default): ", allow_empty=True)
        self.config["specific_log_file_name"] = str(path) if path else "pagodo.py.log"

    def run_pagodo(self) -> None:
        """Execute pagodo with the current configuration."""

        if not self.config["google_dorks_file"]:
            input("Google dorks file is required. Press Enter to continue...")
            return

        config = self.config.copy()
        config["google_dorks_file"] = str(config["google_dorks_file"])

        print("\nStarting pagodo. Logs will appear below. Press Ctrl+C to stop.\n")

        try:
            pagodo = Pagodo(**config)
            pagodo.go()
        except KeyboardInterrupt:
            print("\nOperation cancelled by user.")
        finally:
            input("\nExecution finished. Press Enter to return to the menu...")


def main() -> None:
    cli = PagodoCLI()
    cli.run()


if __name__ == "__main__":
    main()
