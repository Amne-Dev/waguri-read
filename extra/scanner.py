"""Locate duplicate or nested panel images inside the panels directory."""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Sequence

try:
	from PIL import Image
except ImportError as exc: # pragma: no cover - pillow required for runtime usage
	raise SystemExit("scanner.py requires Pillow. Install it via 'pip install pillow'.") from exc

VALID_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
CHANNELS = 3
DEFAULT_LOG_FILE = Path(__file__).resolve().with_name("scanner.log")
RESAMPLE = Image.Resampling.LANCZOS


class ScannerLogger:
	def __init__(self, log_path: Path | None, verbose: bool = True) -> None:
		self.log_path = log_path
		self.verbose = verbose
		if self.log_path:
			self.log_path.parent.mkdir(parents=True, exist_ok=True)

	def emit(self, message: str) -> None:
		timestamp = datetime.now(timezone.utc).isoformat()
		line = f"[{timestamp}] {message}"
		if self.verbose:
			print(message)
		if self.log_path:
			with self.log_path.open("a", encoding="utf-8") as handle:
				handle.write(f"{line}\n")


@dataclass(slots=True)
class ImageRecord:
	path: Path
	width: int
	height: int
	pixel_hash: str
	pixels: bytes
	stride: int
	perceptual_hash: int

	@property
	def area(self) -> int:
		return self.width * self.height



def compute_average_hash(image: Image.Image, hash_size: int = 8) -> int:
	gray = image.convert("L").resize((hash_size, hash_size), RESAMPLE)
	pixels = list(gray.getdata()) # type: ignore
	average = sum(pixels) / len(pixels)
	result = 0
	for value in pixels:
		result = (result << 1) | (1 if value >= average else 0)
	return result


def load_images(
	root: Path,
	extensions: Sequence[str],
	logger: ScannerLogger,
	perceptual_hash_size: int = 8,
) -> List[ImageRecord]:
	records: List[ImageRecord] = []
	for file_path in sorted(root.rglob("*")):
		if not file_path.is_file():
			continue
		if file_path.suffix.lower() not in extensions:
			continue
		try:
			with Image.open(file_path) as source:
				image = source.convert("RGB")
				pixels = image.tobytes()
				width, height = image.size
				perceptual_hash = compute_average_hash(image, perceptual_hash_size)
		except OSError as error:
			logger.emit(f"Skipping {file_path}: {error}.")
			continue
		stride = width * CHANNELS
		records.append(
			ImageRecord(
				path=file_path,
				width=width,
				height=height,
				pixel_hash=hashlib.sha256(pixels).hexdigest(),
				pixels=pixels,
				stride=stride,
				perceptual_hash=perceptual_hash,
			)
		)
		logger.emit(f"Loaded {file_path} ({width}x{height}).")
	return records


def find_exact_duplicates(records: Sequence[ImageRecord]) -> List[List[ImageRecord]]:
	dupes: List[List[ImageRecord]] = []
	groups: dict[tuple[int, int, str], List[ImageRecord]] = {}
	for record in records:
		key = (record.width, record.height, record.pixel_hash)
		groups.setdefault(key, []).append(record)
	for bucket in groups.values():
		if len(bucket) > 1:
			dupes.append(bucket)
	return dupes


def contains_subimage(container: ImageRecord, candidate: ImageRecord) -> bool:
	if candidate.width > container.width or candidate.height > container.height:
		return False
	if candidate.width == container.width and candidate.height == container.height:
		return False
	big_row_stride = container.stride
	small_row_stride = candidate.stride
	bh = container.height
	sh = candidate.height
	first_row = candidate.pixels[:small_row_stride]
	for y in range(bh - sh + 1):
		row_start = y * big_row_stride
		big_row = container.pixels[row_start:row_start + big_row_stride]
		idx = big_row.find(first_row)
		while idx != -1:
			if idx % CHANNELS != 0:
				idx = big_row.find(first_row, idx + 1)
				continue
			match = True
			for offset in range(1, sh):
				big_offset = row_start + offset * big_row_stride + idx
				small_offset = offset * small_row_stride
				segment_large = container.pixels[big_offset:big_offset + small_row_stride]
				segment_small = candidate.pixels[small_offset:small_offset + small_row_stride]
				if segment_large != segment_small:
					match = False
					break
			if match:
				return True
			idx = big_row.find(first_row, idx + CHANNELS)
	return False


def find_contained_pairs(records: Sequence[ImageRecord]) -> List[tuple[ImageRecord, ImageRecord]]:
	pairs: List[tuple[ImageRecord, ImageRecord]] = []
	sorted_records = sorted(records, key=lambda rec: rec.area)
	for index, candidate in enumerate(sorted_records):
		for container in sorted_records[index + 1 :]:
			if candidate.width > container.width or candidate.height > container.height:
				continue
			if contains_subimage(container, candidate):
				pairs.append((candidate, container))
	return pairs


def hamming_distance(first: int, second: int) -> int:
	return (first ^ second).bit_count()


def find_perceptual_duplicates(
	records: Sequence[ImageRecord],
	threshold: int,
) -> List[tuple[ImageRecord, ImageRecord, int]]:
	if threshold <= 0:
		return []
	suspects: List[tuple[ImageRecord, ImageRecord, int]] = []
	by_dimensions: dict[tuple[int, int], List[ImageRecord]] = {}
	for record in records:
		key = (record.width, record.height)
		by_dimensions.setdefault(key, []).append(record)
	for bucket in by_dimensions.values():
		count = len(bucket)
		if count < 2:
			continue
		for index in range(count):
			left = bucket[index]
			for right in bucket[index + 1 :]:
				distance = hamming_distance(left.perceptual_hash, right.perceptual_hash)
				if distance <= threshold:
					suspects.append((left, right, distance))
	return suspects


def report_duplicates(duplicate_groups: Sequence[Sequence[ImageRecord]], logger: ScannerLogger) -> None:
	if not duplicate_groups:
		logger.emit("No pixel-perfect duplicates detected.")
		return
	logger.emit("Duplicate images detected (reported before any other checks):")
	for group in duplicate_groups:
		logger.emit("  · group start")
		for record in group:
			logger.emit(f"    - {record.path}")


def report_perceptual_duplicates(
	suspects: Sequence[tuple[ImageRecord, ImageRecord, int]],
	logger: ScannerLogger,
) -> None:
	if not suspects:
		logger.emit("No perceptual duplicates detected (allowing for text differences).")
		return
	logger.emit("Perceptual duplicates detected (similar art, text may differ):")
	for left, right, distance in suspects:
		logger.emit(
			f"  · {left.path} <> {right.path} (hash distance {distance})"
		)


def report_containments(pairs: Sequence[tuple[ImageRecord, ImageRecord]], logger: ScannerLogger) -> None:
	if not pairs:
		logger.emit("No nested (contained) images detected.")
		return
	logger.emit("Nested images detected (child ⊂ parent):")
	for child, parent in pairs:
		logger.emit(f"  · {child.path} is contained within {parent.path}")


def build_parser() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"root",
		type=Path,
		nargs="?",
		default=Path(__file__).resolve().parents[1] / "panels",
		help="Folder containing chapter subdirectories (defaults to repo_root/panels)",
	)
	parser.add_argument(
		"--extensions",
		default=".png,.jpg,.jpeg,.webp",
		help="Comma-separated list of image extensions to inspect.",
	)
	parser.add_argument(
		"--log-file",
		type=Path,
		default=DEFAULT_LOG_FILE,
		help="Path for the verbose scan log (default: scanner.log next to this script).",
	)
	parser.add_argument(
		"--quiet",
		action="store_true",
		help="Suppress console output (still writes to log file).",
	)
	parser.add_argument(
		"--perceptual-threshold",
		type=int,
		default=4,
		help=(
			"Maximum Hamming distance between perceptual hashes to consider panels duplicates."
		),
	)
	return parser


def main(argv: Iterable[str] | None = None) -> int:
	parser = build_parser()
	args = parser.parse_args(argv) # type: ignore[arg-type]
	log_path: Path | None = args.log_file
	logger = ScannerLogger(log_path, verbose=not args.quiet)
	if not args.root.exists():
		logger.emit(f"Panels directory not found: {args.root}")
		return 1
	logger.emit(f"Scanning panels under {args.root} (chapter-by-chapter).")
	extensions = {
		item.strip().lower() if item.strip().startswith(".") else f".{item.strip().lower()}"
		for item in args.extensions.split(",")
		if item.strip()
	}
	if not extensions:
		logger.emit("No extensions configured; nothing to do.")
		return 1
	chapter_dirs = sorted(
		[p for p in args.root.iterdir() if p.is_dir()],
		key=lambda path: path.name.lower(),
	)
	if not chapter_dirs:
		logger.emit("No chapter folders found; scanning root contents instead.")
		chapter_dirs = [args.root]
	status = 0
	for chapter in chapter_dirs:
		logger.emit(f"\n=== Chapter scan: {chapter.relative_to(args.root.parent) if chapter != args.root else chapter} ===")
		records = load_images(chapter, extensions, logger) # type: ignore
		if not records:
			logger.emit("No images detected in this chapter; skipping.")
			continue
		logger.emit(f"Analyzed {len(records)} images in {chapter.name}. Detecting duplicates before other checks…")
		duplicate_groups = find_exact_duplicates(records)
		report_duplicates(duplicate_groups, logger)
		suspects = find_perceptual_duplicates(records, args.perceptual_threshold)
		report_perceptual_duplicates(suspects, logger)
		logger.emit("Proceeding to containment scan once duplicates are reported.")
		containment_pairs = find_contained_pairs(records)
		report_containments(containment_pairs, logger)
	logger.emit("Scan complete.")
	return status


if __name__ == "__main__":
	raise SystemExit(main())
