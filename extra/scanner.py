"""GUI utility to scan chapters for similar panels and review them side by side."""

from __future__ import annotations

import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Iterable, List, Sequence

try:
	from PIL import Image, ImageTk
except ImportError as exc: # pragma: no cover
	raise SystemExit("scanner.py now requires Pillow. Install it via 'pip install pillow'.") from exc

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "panels"
VALID_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")
HASH_SIZE = 12
RESAMPLE = Image.Resampling.LANCZOS
PREVIEW_SIZE = (420, 640)
DIMENSION_RATIO_TOLERANCE = 0.1


@dataclass(slots=True)
class PanelInfo:
	path: Path
	width: int
	height: int
	hash_value: int


@dataclass(slots=True)
class SimilarPair:
	left: PanelInfo
	right: PanelInfo
	distance: int


def compute_average_hash(image: Image.Image, hash_size: int = HASH_SIZE) -> int:
	gray = image.convert("L").resize((hash_size, hash_size), RESAMPLE)
	pixels = list(gray.getdata()) # type: ignore[arg-type]
	average = sum(pixels) / len(pixels)
	result = 0
	for value in pixels:
		result = (result << 1) | (1 if value >= average else 0)
	return result


def hamming_distance(first: int, second: int) -> int:
	return (first ^ second).bit_count()


def gather_panels(chapter_path: Path, extensions: Sequence[str]) -> List[PanelInfo]:
	records: List[PanelInfo] = []
	for entry in sorted(chapter_path.iterdir()):
		if not entry.is_file() or entry.suffix.lower() not in extensions:
			continue
		try:
			with Image.open(entry) as src:
				image = src.convert("RGB")
				width, height = image.size
				hash_value = compute_average_hash(image)
		except OSError:
			continue
		records.append(PanelInfo(entry, width, height, hash_value))
	return records


def dimensions_close(a: PanelInfo, b: PanelInfo) -> bool:
	width_diff = abs(a.width - b.width)
	height_diff = abs(a.height - b.height)
	max_width = max(a.width, b.width) or 1
	max_height = max(a.height, b.height) or 1
	return (
		width_diff <= max_width * DIMENSION_RATIO_TOLERANCE
		and height_diff <= max_height * DIMENSION_RATIO_TOLERANCE
	)


def find_similar_pairs(records: Sequence[PanelInfo], threshold: int) -> List[SimilarPair]:
	pairs: List[SimilarPair] = []
	sorted_records = sorted(records, key=lambda item: item.width * item.height)
	count = len(sorted_records)
	for idx in range(count):
		left = sorted_records[idx]
		for right in sorted_records[idx + 1 :]:
			if not dimensions_close(left, right):
				continue
			distance = hamming_distance(left.hash_value, right.hash_value)
			if distance <= threshold:
				pairs.append(SimilarPair(left, right, distance))
	return pairs


def scan_repository(
	root_path: Path,
	extensions: Sequence[str],
	threshold: int,
	progress_cb: Callable[[str], None],
) -> List[SimilarPair]:
	pairs: List[SimilarPair] = []
	chapters = sorted((p for p in root_path.iterdir() if p.is_dir()), key=lambda path: path.name.lower())
	if not chapters:
		chapters = [root_path]
	for idx, chapter in enumerate(chapters, start=1):
		progress_cb(f"Scanning {chapter.name} ({idx}/{len(chapters)})…")
		records = gather_panels(chapter, extensions)
		if not records:
			continue
		pairs.extend(find_similar_pairs(records, threshold))
	progress_cb(f"Scan complete: {len(pairs)} similar pair(s) found.")
	return pairs


class ScannerApp:
	def __init__(self) -> None:
		self.root = tk.Tk()
		self.root.title("Panel Similarity Scanner")
		self.root.geometry("1280x800")
		self.root.minsize(1100, 720)

		self.root_path_var = tk.StringVar(value=str(DEFAULT_ROOT))
		self.threshold_var = tk.IntVar(value=4)
		self.status_var = tk.StringVar(value="Idle.")

		self.duplicate_pairs: List[SimilarPair] = []
		self.left_preview: ImageTk.PhotoImage | None = None
		self.right_preview: ImageTk.PhotoImage | None = None
		self.scan_thread: threading.Thread | None = None

		self._build_ui()

	def _build_ui(self) -> None:
		self.root.columnconfigure(1, weight=1)
		self.root.rowconfigure(1, weight=1)

		controls = ttk.Frame(self.root, padding=12)
		controls.grid(row=0, column=0, columnspan=2, sticky="ew")
		controls.columnconfigure(1, weight=1)

		ttk.Label(controls, text="Panels folder:").grid(row=0, column=0, sticky="w")
		path_entry = ttk.Entry(controls, textvariable=self.root_path_var)
		path_entry.grid(row=0, column=1, sticky="ew", padx=6)
		ttk.Button(controls, text="Browse", command=self._choose_directory).grid(row=0, column=2)

		ttk.Label(controls, text="Similarity threshold (lower = stricter):").grid(row=1, column=0, sticky="w", pady=(8, 0))
		threshold_spin = ttk.Spinbox(
			controls,
			from_=1,
			to=32,
			textvariable=self.threshold_var,
			width=6,
		)
		threshold_spin.grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))

		self.scan_button = ttk.Button(controls, text="Start Scan", command=self._start_scan)
		self.scan_button.grid(row=1, column=2, padx=4, pady=(8, 0))

		self.status_label = ttk.Label(controls, textvariable=self.status_var)
		self.status_label.grid(row=2, column=0, columnspan=3, sticky="w", pady=(8, 0))

		list_frame = ttk.Frame(self.root, padding=12)
		list_frame.grid(row=1, column=0, sticky="nsw")
		list_frame.rowconfigure(1, weight=1)
		list_frame.columnconfigure(0, weight=1)

		ttk.Label(list_frame, text="Detected Similar Pairs").grid(row=0, column=0, sticky="w")
		scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
		self.pair_listbox = tk.Listbox(
			list_frame,
			height=30,
			width=45,
			exportselection=False,
			yscrollcommand=scrollbar.set,
		)
		scrollbar.config(command=self.pair_listbox.yview)
		self.pair_listbox.grid(row=1, column=0, sticky="nsew", pady=6)
		scrollbar.grid(row=1, column=1, sticky="ns")
		self.pair_listbox.bind("<<ListboxSelect>>", self._on_pair_select)

		preview = ttk.Frame(self.root, padding=12)
		preview.grid(row=1, column=1, sticky="nsew")
		preview.columnconfigure((0, 1), weight=1)
		preview.rowconfigure(1, weight=1)

		self.left_image_label = ttk.Label(preview, text="Original Panel", anchor="center")
		self.left_image_label.grid(row=0, column=0, sticky="ew")
		self.right_image_label = ttk.Label(preview, text="Potential Duplicate", anchor="center")
		self.right_image_label.grid(row=0, column=1, sticky="ew")

		self.left_canvas = ttk.Label(preview, relief="sunken")
		self.left_canvas.grid(row=1, column=0, padx=6, pady=6, sticky="nsew")
		self.right_canvas = ttk.Label(preview, relief="sunken")
		self.right_canvas.grid(row=1, column=1, padx=6, pady=6, sticky="nsew")

		button_bar = ttk.Frame(preview)
		button_bar.grid(row=2, column=0, columnspan=2, pady=(8, 0))
		self.keep_left_button = ttk.Button(button_bar, text="Keep Left (Delete Right)", command=lambda: self._resolve_pair("right"))
		self.keep_left_button.grid(row=0, column=0, padx=6)
		self.keep_right_button = ttk.Button(button_bar, text="Keep Right (Delete Left)", command=lambda: self._resolve_pair("left"))
		self.keep_right_button.grid(row=0, column=1, padx=6)
		self._update_action_buttons()

	def _choose_directory(self) -> None:
		selection = filedialog.askdirectory(title="Select panels directory", initialdir=self.root_path_var.get())
		if selection:
			self.root_path_var.set(selection)

	def _start_scan(self) -> None:
		if self.scan_thread and self.scan_thread.is_alive():
			return
		root_path = Path(self.root_path_var.get()).expanduser()
		if not root_path.exists():
			messagebox.showerror("Path not found", f"Directory does not exist:\n{root_path}")
			return
		threshold = max(1, min(32, self.threshold_var.get()))
		self.threshold_var.set(threshold)
		self.duplicate_pairs.clear()
		self._clear_listbox()
		self._clear_previews()
		self.status_var.set("Starting scan…")
		self.scan_button.config(state=tk.DISABLED)

		def progress_cb(message: str) -> None:
			self.root.after(0, lambda: self.status_var.set(message))

		def worker() -> None:
			try:
				pairs = scan_repository(root_path, VALID_EXTENSIONS, threshold, progress_cb)
			except Exception as error: # pragma: no cover - GUI feedback path
				self.root.after(0, lambda: self._on_scan_failed(error))
				return
			self.root.after(0, lambda: self._on_scan_complete(pairs))

		self.scan_thread = threading.Thread(target=worker, daemon=True)
		self.scan_thread.start()

	def _on_scan_failed(self, error: Exception) -> None:
		self.scan_button.config(state=tk.NORMAL)
		self.status_var.set("Scan failed. See console for details.")
		messagebox.showerror("Scan failed", str(error))

	def _on_scan_complete(self, pairs: List[SimilarPair]) -> None:
		self.scan_button.config(state=tk.NORMAL)
		self.duplicate_pairs = [pair for pair in pairs if pair.left.path.exists() and pair.right.path.exists()]
		for index, pair in enumerate(self.duplicate_pairs, start=1):
			label = f"{index}. {pair.left.path.name} ↔ {pair.right.path.name} (dist={pair.distance})"
			self.pair_listbox.insert(tk.END, label)
		count = len(self.duplicate_pairs)
		message = "No similar panels detected." if count == 0 else f"Scan complete: {count} pair(s) ready for review."
		self.status_var.set(message)
		if count > 0:
			self.pair_listbox.selection_set(0)
			self._on_pair_select()
		self._update_action_buttons()

	def _clear_listbox(self) -> None:
		self.pair_listbox.delete(0, tk.END)

	def _clear_previews(self) -> None:
		self.left_canvas.config(image="", text="")
		self.right_canvas.config(image="", text="")
		self.left_preview = None
		self.right_preview = None

	def _on_pair_select(self, event: tk.Event | None = None) -> None: # type: ignore[override]
		selection = self.pair_listbox.curselection()
		if not selection:
			self._clear_previews()
			self._update_action_buttons()
			return
		index = selection[0]
		if index >= len(self.duplicate_pairs):
			return
		pair = self.duplicate_pairs[index]
		self.left_preview = self._load_preview(pair.left.path)
		self.right_preview = self._load_preview(pair.right.path)
		left_image: ImageTk.PhotoImage | str = self.left_preview if self.left_preview is not None else ""
		right_image: ImageTk.PhotoImage | str = self.right_preview if self.right_preview is not None else ""
		self.left_canvas.config(image=left_image, text=str(pair.left.path))
		self.right_canvas.config(image=right_image, text=str(pair.right.path))
		self._update_action_buttons()

	def _load_preview(self, path: Path) -> ImageTk.PhotoImage | None:
		if not path.exists():
			return None
		try:
			with Image.open(path) as img:
				preview = img.copy()
				preview.thumbnail(PREVIEW_SIZE, RESAMPLE)
		except OSError:
			return None
		return ImageTk.PhotoImage(preview)

	def _resolve_pair(self, delete_side: str) -> None:
		selection = self.pair_listbox.curselection()
		if not selection:
			return
		index = selection[0]
		if index >= len(self.duplicate_pairs):
			return
		pair = self.duplicate_pairs[index]
		target = pair.left.path if delete_side == "left" else pair.right.path
		if not target.exists():
			messagebox.showwarning("File missing", f"{target} no longer exists.")
			self._remove_pair_at(index)
			return
		if not messagebox.askyesno("Confirm delete", f"Delete {target.name}? This cannot be undone."):
			return
		try:
			target.unlink()
		except OSError as error:
			messagebox.showerror("Delete failed", f"Could not delete {target}: {error}")
			return
		self.status_var.set(f"Deleted {target.name}.")
		self._remove_pair_at(index)

	def _remove_pair_at(self, index: int) -> None:
		if index >= len(self.duplicate_pairs):
			return
		self.duplicate_pairs.pop(index)
		self.pair_listbox.delete(index)
		if self.duplicate_pairs:
			new_index = min(index, len(self.duplicate_pairs) - 1)
			self.pair_listbox.selection_set(new_index)
			self._on_pair_select()
		else:
			self._clear_previews()
		self._update_action_buttons()

	def _update_action_buttons(self) -> None:
		has_selection = bool(self.pair_listbox.curselection())
		state = tk.NORMAL if has_selection else tk.DISABLED
		self.keep_left_button.config(state=state)
		self.keep_right_button.config(state=state)

	def run(self) -> None:
		self.root.mainloop()


def main(_: Iterable[str] | None = None) -> int:
	app = ScannerApp()
	app.run()
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
