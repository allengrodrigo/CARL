#!/usr/bin/env python3
"""Editable text pop-out for plugin result files: edit, Save, Save As.

A minimal plain-text editor used for text/table/trace results. Keeps its own
dirty state and prompts on close so edits are never lost silently.
"""

from __future__ import annotations

import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


class TextEditorWindow:
    def __init__(self, parent, path: str, mono_font=None):
        self.source = Path(path).expanduser().resolve()
        self._font  = mono_font or ("Courier New", 10)
        self._dirty = False
        self._suppress_modified = False

        self.window = tk.Toplevel(parent)
        self.window.geometry("900x680")
        self.window.minsize(600, 400)

        self._wrap = tk.BooleanVar(value=False)
        self._build_ui()
        self._load()
        self.window.protocol("WM_DELETE_WINDOW", self._close)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        bar = ttk.Frame(self.window, padding=(6, 5))
        bar.pack(fill=tk.X)
        ttk.Button(bar, text="Save",     command=self._save   ).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Save As…", command=self._save_as).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="Reload",   command=self._reload ).pack(side=tk.LEFT, padx=2)
        ttk.Separator(bar, orient="vertical").pack(side=tk.LEFT, fill="y", padx=8, pady=2)
        ttk.Checkbutton(bar, text="Wrap", variable=self._wrap,
                        command=self._toggle_wrap).pack(side=tk.LEFT, padx=2)

        body = ttk.Frame(self.window)
        body.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))
        self.text = tk.Text(body, wrap=tk.NONE, font=self._font, undo=True,
                            bg="#1e1e1e", fg="#d4d4d4", insertbackground="#d4d4d4")
        vsb = ttk.Scrollbar(body, orient="vertical",   command=self.text.yview)
        hsb = ttk.Scrollbar(body, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side=tk.RIGHT,  fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self.text.pack(fill=tk.BOTH, expand=True)
        self.text.bind("<<Modified>>", self._on_modified)

        self.status = tk.StringVar()
        ttk.Label(self.window, textvariable=self.status, anchor="w",
                  padding=(8, 4), foreground="#4c5661").pack(fill=tk.X)

    # ── load / dirty state ──────────────────────────────────────────────────────

    def _load(self):
        try:
            with open(self.source, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except Exception as exc:
            content = f"[Error reading file: {exc}]"
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", content)
        self.text.edit_reset()          # clear undo stack of the initial load
        self._clear_modified()
        self._update_title()
        self.status.set(str(self.source))

    def _on_modified(self, _event=None):
        if self._suppress_modified:
            return
        if self.text.edit_modified():
            self._dirty = True
            self._update_title()

    def _clear_modified(self):
        self._suppress_modified = True
        self.text.edit_modified(False)
        self._suppress_modified = False
        self._dirty = False

    def _update_title(self):
        star = "*" if self._dirty else ""
        self.window.title(f"{star}{self.source.name} — Text Editor")

    def _toggle_wrap(self):
        self.text.configure(wrap=tk.WORD if self._wrap.get() else tk.NONE)

    # ── save / reload ───────────────────────────────────────────────────────────

    def _save(self):
        return self._do_save(self.source)

    def _save_as(self):
        path = filedialog.asksaveasfilename(
            parent=self.window,
            title="Save As",
            initialfile=self.source.name,
            defaultextension=self.source.suffix or ".txt",
            filetypes=[("All files", "*.*")])
        if not path:
            return False
        self.source = Path(path).expanduser().resolve()
        ok = self._do_save(self.source)
        self.status.set(str(self.source))
        return ok

    def _do_save(self, path: Path) -> bool:
        try:
            content = self.text.get("1.0", "end-1c")
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc), parent=self.window)
            return False
        self._clear_modified()
        self._update_title()
        self.status.set(f"Saved: {path}")
        return True

    def _reload(self):
        if self._dirty and not messagebox.askyesno(
                "Reload", "Discard unsaved changes and reload from disk?",
                parent=self.window):
            return
        self._load()

    # ── close ───────────────────────────────────────────────────────────────────

    def _close(self):
        if self._dirty:
            answer = messagebox.askyesnocancel(
                "Unsaved changes",
                f"Save changes to {self.source.name} before closing?",
                parent=self.window)
            if answer is None:               # Cancel
                return
            if answer and not self._save():  # Yes, but save failed
                return
        try:
            self.window.destroy()
        except tk.TclError:
            pass


def open_text_editor(parent, path: str, mono_font=None) -> TextEditorWindow:
    """Open an editable text window for the given file."""
    return TextEditorWindow(parent, path, mono_font=mono_font)
