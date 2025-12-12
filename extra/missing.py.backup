"""Utility to spot missing panel numbers inside each chapter folder."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from typing import Iterable, List, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

VALID_EXTENSIONS = {".webp", ".png", ".jpg", ".jpeg"}
NUMBER_PATTERN = re.compile(r"(\d+)")
CHAPTER_PATTERN = re.compile(r"chapter\s*(\d+)", re.IGNORECASE)
VOLUME_PATTERN = re.compile(r"volume\s*\d+", re.IGNORECASE)
DEFAULT_DOWNLOAD_BASE = (
	"https://eu2.contabostorage.com/2352a0b47a16442aa2bd93b0a47735ea:manga/"
	"fragrant/Chapter%20{chapter}/{panel}.jpg"
)
WEBP_DOWNLOAD_BASE = (
	"https://eu2.contabostorage.com/2352a0b47a16442aa2bd93b0a47735ea:manga/"
	"fragrant/Chapter%20{chapter}/{panel}.webp"
)
PNG_DOWNLOAD_BASE = (
	"https://eu2.contabostorage.com/2352a0b47a16442aa2bd93b0a47735ea:manga/"
	"fragrant/Chapter%20{chapter}/{panel}.png"
)
DEFAULT_FALLBACK_BASES = (WEBP_DOWNLOAD_BASE, PNG_DOWNLOAD_BASE)


def guess_extension_from_template(template: str, default: str = ".bin") -> str:
	"""Infer the file extension from the tail of a URL template."""
	path_fragment = template.split("?")[0].rsplit("/", 1)[-1]
	if "." in path_fragment:
		ext = path_fragment.rsplit(".", 1)[-1].lower()
		return f".{ext}"
	return default


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
	fallback_download_bases: Sequence[str] | None = None,
	chapter_pad: int = 3,
	panel_pad: int = 2,
	log_path: Path | None = None,
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
		fallback_templates = list(fallback_download_bases or DEFAULT_FALLBACK_BASES)
		download_missing_panels(
			reports,
			download_base,
			fallback_templates,
			chapter_pad=chapter_pad,
			panel_pad=panel_pad,
			log_path=log_path,
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



def log_download_event(log_path: Path | None, message: str) -> None:
	if not log_path:
		return
	log_path.parent.mkdir(parents=True, exist_ok=True)
	timestamp = datetime.now(timezone.utc).isoformat()
	with log_path.open("a", encoding="utf-8") as log_file:
		log_file.write(f"[{timestamp}] {message}\n")


def encode_url_for_request(url: str) -> str:
	"""Percent-encode spaces and other unsafe chars while keeping readable logs."""
	return quote(url, safe=":/?&=%")


def render_progress_bar(completed: int, total: int, width: int = 40) -> str:
	if total <= 0:
		total = 1
	ratio = min(max(completed / total, 0.0), 1.0)
	filled = int(width * ratio)
	bar = "#" * filled + "-" * (width - filled)
	return f"[{bar}] {completed}/{total}"


def normalize_chapter_token_for_url(token: str) -> str:
	"""Drop leading zeros for chapter tokens; keep at least a single digit."""
	stripped = token.lstrip("0")
	return stripped or "0"


def normalize_panel_token_for_url(token: str) -> str:
	"""Convert values like 00X into 0X before embedding in CDN URLs."""
	if len(token) == 3 and token.startswith("00"):
		return token[1:]
	return token


def download_missing_panels(
	reports: Sequence[ChapterReport],
	base_url: str,
	fallback_base_urls: Sequence[str],
	chapter_pad: int,
	panel_pad: int,
	log_path: Path | None = None,
) -> dict[str, List[int]]:
	total_targets = sum(len(report.missing) for report in reports)
	if total_targets == 0:
		print("\nNo missing panels need downloading.")
		return {}
	success_count = 0
	attempt_templates: List[tuple[str, str]] = [
		(base_url, guess_extension_from_template(base_url, ".jpg"))
	]
	attempt_templates.extend(
		(template, guess_extension_from_template(template, ".png"))
		for template in fallback_base_urls
	)
	extension_pool = {ext for _, ext in attempt_templates}
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
		chapter_token_for_url = normalize_chapter_token_for_url(chapter_token)
		for panel in report.missing:
			panel_token = str(panel).zfill(panel_pad)
			if any((report.path / f"{panel_token}{ext}").exists() for ext in extension_pool):
				print(f"  · Skipping {panel_token} (already exists).")
				continue
			panel_token_for_url = normalize_panel_token_for_url(panel_token)
			last_forbidden = True
			attempt_failed = True
			for attempt_index, (template, extension) in enumerate(attempt_templates):
				if attempt_index > 0 and not last_forbidden:
					break
				destination = report.path / f"{panel_token}{extension}"
				if attempt_index > 0:
					label = extension.lstrip('.') or extension
					print(f"  · Retrying as {label.upper()} fallback…")
				raw_url = template.format(
					chapter=chapter_token_for_url,
					panel=panel_token_for_url,
					chapter_raw=chapter_number,
					panel_raw=panel,
				)
				request_url = encode_url_for_request(raw_url)
				success, forbidden = fetch_file(request_url, destination)
				status = "SUCCESS" if success else ("FORBIDDEN" if forbidden else "FAILURE")
				log_download_event(
					log_path,
					f"{report.name} panel {panel_token} ({destination.name}) -> {status} | {raw_url}",
				)
				if success:
					success_count += 1
					print(f"    ✓ Panel {panel_token} saved as {destination.name}.")
					attempt_failed = False
					break
				last_forbidden = forbidden
			if attempt_failed:
				failures.setdefault(report.name, []).append(panel)
	if failures:
		print("\nDownload failures detected:")
		for chapter_name, missing_panels in failures.items():
			print(f"  · {chapter_name}: {', '.join(map(str, missing_panels))}")
	else:
		print("\nAll missing panels downloaded successfully.")
	print("\nProgress summary:")
	print(f"  {render_progress_bar(success_count, total_targets)}")
	print(f"  Successful downloads: {success_count}/{total_targets}")
	return failures


def fetch_file(url: str, destination: Path) -> tuple[bool, bool]:
	req = Request(url, headers={"User-Agent": "waguri-missing-panels/1.0"})
	try:
		with urlopen(req) as response, destination.open("wb") as output:
			chunk = response.read(8192)
			while chunk:
				output.write(chunk)
				chunk = response.read(8192)
		print(f"  · Downloaded {destination.name}")
		return True, False
	except HTTPError as error:
		print(f"  · {destination.name} failed ({error.code} {error.reason}).")
		return False, error.code == 403
	except URLError as error:
		print(f"  · {destination.name} failed ({error.reason}).")
		return False, False
	except OSError as error:
		print(f"  · Unable to write {destination}: {error}.")
		return False, False


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
		"--fallback-download-base",
		action="append",
		dest="fallback_download_bases",
		default=None,
		help=(
			"Fallback URL template (used after a 403). Repeat this flag to define "
			"multiple fallbacks. Defaults to trying WEBP then PNG endpoints."
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
	parser.add_argument(
		"--log-file",
		type=Path,
		help="Optional path for a download log file (defaults to panels_root/missing_panels.log).",
	)
	return parser


def main(argv: Iterable[str] | None = None) -> int:
	parser = build_arg_parser()
	args = parser.parse_args(argv) # type: ignore
	fallback_templates = args.fallback_download_bases or list(DEFAULT_FALLBACK_BASES)
	log_path = args.log_file or (args.root / "missing_panels.log")
	return analyze_panels(
		args.root,
		excel_path=args.excel,
		download_missing=args.download_missing,
		download_base=args.download_base,
		fallback_download_bases=fallback_templates,
		chapter_pad=args.chapter_pad,
		panel_pad=args.panel_pad,
		log_path=log_path if args.download_missing else None,
	)


if __name__ == "__main__":
	raise SystemExit(main())
