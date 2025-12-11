"""Utility to spot missing panel numbers inside each chapter folder."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

VALID_EXTENSIONS = {".webp", ".png", ".jpg", ".jpeg"}
NUMBER_PATTERN = re.compile(r"(\d+)")
CHAPTER_PATTERN = re.compile(r"chapter\s*(\d+)", re.IGNORECASE)
VOLUME_PATTERN = re.compile(r"volume\s*\d+", re.IGNORECASE)
DEFAULT_DOWNLOAD_BASE = (
	"https://eu2.contabostorage.com/2352a0b47a16442aa2bd93b0a47735ea:manga/"
	"fragrant/Chapter%20{chapter}/{panel}.jpg"
)


@dataclass
class ChapterReport:
	name: str
	path: Path
	panel_count: int
	min_panel: int | None
	max_panel: int | None
	missing: List[int]
	duplicates: List[int]


def extract_panel_number(path: Path) -> int | None:
	"""Return the last integer found in the filename stem, if any."""
	match = NUMBER_PATTERN.findall(path.stem)
	if not match:
		return None
	return int(match[-1])


def collect_panel_numbers(chapter_path: Path) -> tuple[List[int], List[int]]:
	"""Gather sorted panel numbers and note duplicates within the chapter."""
	numbers: List[int] = []
	duplicates: List[int] = []
	seen = set()
	for file in sorted(chapter_path.iterdir()):
		if not file.is_file():
			continue
		if file.suffix.lower() not in VALID_EXTENSIONS:
			continue
		number = extract_panel_number(file)
		if number is None:
			continue
		numbers.append(number)
		if number in seen and number not in duplicates:
			duplicates.append(number)
		seen.add(number)
	return sorted(numbers), sorted(duplicates)


def find_missing(numbers: Sequence[int]) -> List[int]:
	"""Return a flat list of skipped numbers between the min and max panel."""
	missing: List[int] = []
	if len(numbers) < 2:
		return missing
	for previous, current in zip(numbers, numbers[1:]):
		gap = current - previous
		if gap > 1:
			missing.extend(range(previous + 1, current))
	return missing


def summarize_chapter(chapter: Path) -> ChapterReport:
	numbers, duplicates = collect_panel_numbers(chapter)
	min_panel = numbers[0] if numbers else None
	max_panel = numbers[-1] if numbers else None
	missing = find_missing(numbers)
	return ChapterReport(
		name=chapter.name,
		path=chapter,
		panel_count=len(numbers),
		min_panel=min_panel,
		max_panel=max_panel,
		missing=missing,
		duplicates=duplicates,
	)


def export_to_excel(reports: Sequence[ChapterReport], destination: Path) -> bool:
	try:
		from openpyxl import Workbook
	except ImportError:
		print("openpyxl is required for Excel export. Install it via 'pip install openpyxl'.")
		return False

	destination.parent.mkdir(parents=True, exist_ok=True)
	workbook = Workbook()
	sheet = workbook.active
	sheet.title = "Missing Panels" # pyright: ignore[reportOptionalMemberAccess]
	sheet.append([ # type: ignore
		"Chapter",
		"Panel count",
		"Min",
		"Max",
		"Missing numbers",
		"Duplicate numbers",
	])
	for report in reports:
		sheet.append([ # type: ignore
			report.name,
			report.panel_count,
			report.min_panel if report.min_panel is not None else "",
			report.max_panel if report.max_panel is not None else "",
			", ".join(map(str, report.missing)) if report.missing else "",
			", ".join(map(str, report.duplicates)) if report.duplicates else "",
		])
	workbook.save(destination)
	print(f"Excel report written to {destination}")
	return True


def analyze_panels(
	panels_root: Path,
	excel_path: Path | None = None,
	download_missing: bool = False,
	download_base: str = DEFAULT_DOWNLOAD_BASE,
	chapter_pad: int = 3,
	panel_pad: int = 2,
) -> int:
	if not panels_root.is_dir():
		print(f"Panels directory not found: {panels_root}")
		return 1

	chapters = [entry for entry in panels_root.iterdir() if entry.is_dir()]
	if not chapters:
		print("No chapter folders detected.")
		return 1

	reports = [
		summarize_chapter(chapter)
		for chapter in sorted(chapters, key=lambda path: path.name.lower())
	]
	print_reports(reports)
	if excel_path:
		success = export_to_excel(reports, excel_path)
		if not success:
			return 1
	if download_missing:
		download_missing_panels(
			reports,
			download_base,
			chapter_pad=chapter_pad,
			panel_pad=panel_pad,
		)
	return 0


def print_reports(reports: Sequence[ChapterReport]) -> None:
	for report in reports:
		print(f"\n{report.name}")
		if not report.panel_count:
			print("  · No numeric panel filenames found.")
			continue
		print(
			f"  · Panels detected: {report.panel_count} (min {report.min_panel}, max {report.max_panel})"
		)
		if report.missing:
			print(f"  · Missing numbers: {', '.join(map(str, report.missing))}")
		else:
			print("  · No gaps detected.")
		if report.duplicates:
			print(f"  · Duplicate numbers: {', '.join(map(str, report.duplicates))}")


def normalize_chapter_label(label: str) -> str:
	clean = label.replace("_", " ")
	clean = VOLUME_PATTERN.sub("", clean)
	return re.sub(r"\s+", " ", clean).strip()


def extract_chapter_number(label: str) -> int | None:
	label = normalize_chapter_label(label)
	match = CHAPTER_PATTERN.search(label)
	if match:
		return int(match.group(1))
	digits = NUMBER_PATTERN.findall(label)
	if digits:
		return int(digits[0])
	return None


def download_missing_panels(
	reports: Sequence[ChapterReport],
	base_url: str,
	chapter_pad: int,
	panel_pad: int,
) -> dict[str, List[int]]:
	failures: dict[str, List[int]] = {}
	for report in reports:
		if not report.missing:
			continue
		chapter_number = extract_chapter_number(report.name)
		print(f"\nDownloading missing panels for {report.name}")
		if chapter_number is None:
			print("  · Could not infer chapter number from folder name; skipping.")
			failures[report.name] = report.missing.copy()
			continue
		chapter_token = str(chapter_number).zfill(chapter_pad)
		for panel in report.missing:
			panel_token = str(panel).zfill(panel_pad)
			destination = report.path / f"{panel_token}.jpg"
			if destination.exists():
				print(f"  · Skipping {destination.name} (already exists).")
				continue
			url = base_url.format(
				chapter=chapter_token,
				panel=panel_token,
				chapter_raw=chapter_number,
				panel_raw=panel,
			)
			if not fetch_file(url, destination):
				failures.setdefault(report.name, []).append(panel)
	if failures:
		print("\nDownload failures detected:")
		for chapter_name, missing_panels in failures.items():
			print(f"  · {chapter_name}: {', '.join(map(str, missing_panels))}")
	else:
		print("\nAll missing panels downloaded successfully.")
	return failures


def fetch_file(url: str, destination: Path) -> bool:
	req = Request(url, headers={"User-Agent": "waguri-missing-panels/1.0"})
	try:
		with urlopen(req) as response, destination.open("wb") as output:
			chunk = response.read(8192)
			while chunk:
				output.write(chunk)
				chunk = response.read(8192)
		print(f"  · Downloaded {destination.name}")
		return True
	except HTTPError as error:
		print(f"  · {destination.name} failed ({error.code} {error.reason}).")
		return False
	except URLError as error:
		print(f"  · {destination.name} failed ({error.reason}).")
		return False
	except OSError as error:
		print(f"  · Unable to write {destination}: {error}.")
		return False


def build_arg_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"root",
		type=Path,
		nargs="?",
		default=Path(__file__).resolve().parents[1] / "panels",
		help="Path to the panels directory (defaults to repo_root/panels)",
	)
	parser.add_argument(
		"--excel",
		type=Path,
		help="Optional path to write an Excel report (.xlsx).",
	)
	parser.add_argument(
		"--download-missing",
		action="store_true",
		help="Attempt to fetch missing panels from the configured CDN URL template.",
	)
	parser.add_argument(
		"--download-base",
		default=DEFAULT_DOWNLOAD_BASE,
		help=(
			"Base URL template used for downloading missing panels. Must include "
			"{chapter} and {panel} placeholders."
		),
	)
	parser.add_argument(
		"--chapter-pad",
		type=int,
		default=3,
		help="Zero-padding width to apply to chapter numbers when formatting the URL.",
	)
	parser.add_argument(
		"--panel-pad",
		type=int,
		default=2,
		help="Zero-padding width to apply to panel numbers when formatting the URL.",
	)
	return parser


def main(argv: Iterable[str] | None = None) -> int:
	parser = build_arg_parser()
	args = parser.parse_args(argv)
	return analyze_panels(
		args.root,
		excel_path=args.excel,
		download_missing=args.download_missing,
		download_base=args.download_base,
		chapter_pad=args.chapter_pad,
		panel_pad=args.panel_pad,
	)


if __name__ == "__main__":
	raise SystemExit(main())
