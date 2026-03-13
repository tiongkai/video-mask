#!/usr/bin/env python3
"""
GUI launcher for video-mask.

Two-tab tkinter window:
  - Annotate: pick videos + config path, then runs annotate.main()
              (blocks tkinter while the OpenCV window is open — by design)
  - Process:  pick videos dir + config + output dir, runs process.main()
              in a background thread with live stdout streaming to a log pane.
"""

import argparse
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from gui_helpers import QueueWriter


# ---------------------------------------------------------------------------
# ffmpeg import guard — process.py calls _find_ffmpeg() at module level,
# which calls sys.exit(1) if ffmpeg is missing. Catch that here so the
# GUI still opens and can show a helpful error message instead.
# ---------------------------------------------------------------------------
try:
    import process as _process_mod
except SystemExit:
    _process_mod = None

import annotate as _annotate_mod


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Video Mask")
        self.resizable(True, True)
        self.minsize(600, 420)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        self._annotate_tab = AnnotateTab(notebook)
        self._process_tab = ProcessTab(notebook)

        notebook.add(self._annotate_tab, text="  Annotate  ")
        notebook.add(self._process_tab, text="  Process  ")


# ---------------------------------------------------------------------------
# Annotate tab
# ---------------------------------------------------------------------------

class AnnotateTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padx=15, pady=15)

        self._videos: list[Path] = []     # list[Path] when files picked
        self._videos_dir: Path | None = None
        self._config_path = tk.StringVar(value=str(Path.cwd() / "config.json"))

        # --- Videos row ---
        tk.Label(self, text="Videos:", anchor="w").grid(
            row=0, column=0, sticky="w", pady=4)
        self._videos_label = tk.Label(
            self, text="(none selected)", anchor="w", fg="grey",
            wraplength=350, justify="left")
        self._videos_label.grid(row=0, column=1, sticky="w", padx=6)

        btn_frame = tk.Frame(self)
        btn_frame.grid(row=0, column=2, sticky="e", padx=4)
        tk.Button(btn_frame, text="Pick files",
                  command=self._pick_video_files).pack(side="left", padx=2)
        tk.Button(btn_frame, text="Pick folder",
                  command=self._pick_video_folder).pack(side="left", padx=2)

        # --- Config row ---
        tk.Label(self, text="Config path:", anchor="w").grid(
            row=1, column=0, sticky="w", pady=4)
        tk.Entry(self, textvariable=self._config_path, width=40).grid(
            row=1, column=1, sticky="ew", padx=6)
        tk.Button(self, text="Browse",
                  command=self._pick_config_save).grid(row=1, column=2, padx=4)

        # --- Run button ---
        tk.Button(self, text="Run Annotate", bg="#2a7", fg="white",
                  font=("", 11, "bold"), command=self._run).grid(
            row=2, column=0, columnspan=3, pady=20, ipadx=20, ipady=6)

        self.columnconfigure(1, weight=1)

    # -- Pickers --

    def _pick_video_files(self):
        paths = filedialog.askopenfilenames(
            title="Select video files",
            filetypes=[("MP4 files", "*.mp4"), ("All files", "*.*")],
        )
        if paths:
            self._videos = [Path(p) for p in paths]
            self._videos_dir = None
            names = ", ".join(p.name for p in self._videos[:3])
            if len(self._videos) > 3:
                names += f" (+{len(self._videos) - 3} more)"
            self._videos_label.config(text=names, fg="black")

    def _pick_video_folder(self):
        folder = filedialog.askdirectory(title="Select videos folder")
        if folder:
            self._videos = []
            self._videos_dir = Path(folder)
            self._videos_label.config(text=str(self._videos_dir), fg="black")

    def _pick_config_save(self):
        path = filedialog.asksaveasfilename(
            title="Config save path",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialfile="config.json",
        )
        if path:
            self._config_path.set(path)

    # -- Validation --

    def _validate(self) -> bool:
        if not self._videos and self._videos_dir is None:
            messagebox.showwarning(
                "No videos",
                "Please pick video files or a folder before running.")
            return False
        config = self._config_path.get().strip()
        if not config:
            messagebox.showwarning(
                "No config path",
                "Please set a config file path before running.")
            return False
        return True

    # -- Run --

    def _run(self):
        if not self._validate():
            return

        config = Path(self._config_path.get())

        if self._videos:
            args = argparse.Namespace(
                videos=list(self._videos),
                videos_dir=Path(self._videos[0]).parent,
                config=config,
            )
        else:
            args = argparse.Namespace(
                videos=None,
                videos_dir=self._videos_dir,
                config=config,
            )

        try:
            _annotate_mod.main(args)
        except Exception as exc:
            messagebox.showerror("Annotate error", str(exc))


# ---------------------------------------------------------------------------
# Process tab
# ---------------------------------------------------------------------------

class ProcessTab(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padx=15, pady=15)

        self._videos_dir = tk.StringVar()
        self._config_path = tk.StringVar(value=str(Path.cwd() / "config.json"))
        self._output_dir = tk.StringVar(value=str(Path.cwd() / "out"))

        def _row(label, var, row, pick_fn):
            tk.Label(self, text=label, anchor="w").grid(
                row=row, column=0, sticky="w", pady=4)
            tk.Entry(self, textvariable=var, width=40).grid(
                row=row, column=1, sticky="ew", padx=6)
            tk.Button(self, text="Browse", command=pick_fn).grid(
                row=row, column=2, padx=4)

        _row("Videos dir:", self._videos_dir, 0, self._pick_videos_dir)
        _row("Config:",     self._config_path, 1, self._pick_config)
        _row("Output dir:", self._output_dir,  2, self._pick_output_dir)

        tk.Button(self, text="Run Process", bg="#27a", fg="white",
                  font=("", 11, "bold"), command=self._run).grid(
            row=3, column=0, columnspan=3, pady=12, ipadx=20, ipady=6)

        # Log pane
        log_frame = tk.Frame(self)
        log_frame.grid(row=4, column=0, columnspan=3, sticky="nsew")
        self._log = tk.Text(
            log_frame, height=12, state="disabled",
            bg="#1e1e1e", fg="#d4d4d4", font=("Courier", 9), wrap="word")
        scrollbar = ttk.Scrollbar(log_frame, command=self._log.yview)
        self._log.configure(yscrollcommand=scrollbar.set)
        self._log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.columnconfigure(1, weight=1)
        self.rowconfigure(4, weight=1)

        self._running = False
        self._log_queue: queue.Queue = queue.Queue()

    # -- Pickers --

    def _pick_videos_dir(self):
        folder = filedialog.askdirectory(title="Select videos directory")
        if folder:
            self._videos_dir.set(folder)

    def _pick_config(self):
        path = filedialog.askopenfilename(
            title="Select config JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self._config_path.set(path)

    def _pick_output_dir(self):
        folder = filedialog.askdirectory(title="Select output directory")
        if folder:
            self._output_dir.set(folder)

    # -- Validation --

    def _validate(self) -> bool:
        if _process_mod is None:
            messagebox.showerror(
                "ffmpeg not found",
                "ffmpeg is required for processing.\n\n"
                "Install it and make sure it is on your PATH:\n"
                "  Windows : https://www.gyan.dev/ffmpeg/builds/\n"
                "  Linux   : sudo apt install ffmpeg\n"
                "  macOS   : brew install ffmpeg",
            )
            return False
        vd = self._videos_dir.get().strip()
        cp = self._config_path.get().strip()
        if not vd:
            messagebox.showwarning("Missing input",
                                   "Please select a videos directory.")
            return False
        if not Path(vd).exists():
            messagebox.showwarning("Not found",
                                   f"Videos directory not found:\n{vd}")
            return False
        if not cp:
            messagebox.showwarning("Missing input",
                                   "Please select a config JSON file.")
            return False
        if not Path(cp).exists():
            messagebox.showwarning("Not found",
                                   f"Config file not found:\n{cp}")
            return False
        return True

    # -- Log helpers --

    def _append_log(self, text: str):
        self._log.configure(state="normal")
        self._log.insert("end", text)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _poll_log_queue(self):
        try:
            while True:
                text = self._log_queue.get_nowait()
                self._append_log(text)
        except queue.Empty:
            pass
        if self._running:
            self.after(100, self._poll_log_queue)

    # -- Run --

    def _run(self):
        if self._running:
            return
        if not self._validate():
            return

        args = argparse.Namespace(
            videos_dir=Path(self._videos_dir.get().strip()),
            config=Path(self._config_path.get().strip()),
            output_dir=Path(self._output_dir.get().strip()),
        )

        self._running = True
        self._append_log("=" * 50 + "\nStarting...\n")
        self.after(100, self._poll_log_queue)

        def _worker():
            # sys.stdout is process-global. This redirect is safe only because
            # self._running prevents a second Process run, and Annotate blocks
            # the main thread (so both cannot be active simultaneously).
            writer = QueueWriter(self._log_queue)
            old_stdout = sys.stdout
            sys.stdout = writer
            try:
                _process_mod.main(args)
            except Exception as exc:
                self._log_queue.put(f"\nERROR: {exc}\n")
            finally:
                sys.stdout = old_stdout
                self._log_queue.put("\nDone.\n")   # enqueue BEFORE clearing flag
                self._running = False

        threading.Thread(target=_worker, daemon=True).start()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
