"""
help_tab.py — Help tab widget and logic for CARL.

HelpTab builds the sidebar, search bar, and lazy HtmlFrame for the
About > Help tab.  Pass the tab's parent Frame and the About Notebook
to the constructor; everything else is self-contained.
"""

import html as _html
import os
import re
import sys
import tkinter as tk
from tkinter import ttk


class HelpTab:
    """Self-contained Help tab: sidebar nav, search bar, lazy HtmlFrame."""

    MANUAL_FILENAME = "CARL_user_manual.html"

    def __init__(self, parent: tk.Frame, about_notebook: ttk.Notebook):
        parent.grid_rowconfigure(1, weight=1)
        parent.grid_columnconfigure(0, minsize=220)
        parent.grid_columnconfigure(1, weight=1)

        # ── Search bar (row 0, spans both columns) ─────────────────
        _search_frame = tk.Frame(parent)
        _search_frame.grid(row=0, column=0, columnspan=2, sticky="ew",
                           padx=8, pady=(8, 4))
        self.search_var = tk.StringVar()
        _entry = ttk.Entry(_search_frame, textvariable=self.search_var, width=30)
        _entry.pack(side="left", padx=(0, 4))
        ttk.Button(_search_frame, text="Search",
                   command=self.search).pack(side="left", padx=2)
        ttk.Button(_search_frame, text="Next",
                   command=lambda: self.search_nav(1)).pack(side="left", padx=2)
        ttk.Button(_search_frame, text="Previous",
                   command=lambda: self.search_nav(-1)).pack(side="left", padx=2)
        _clear_btn = ttk.Button(_search_frame, text="Clear",
                                command=self.search_clear)
        _clear_btn._carl_tooltip_key = "help.clear"
        _clear_btn.pack(side="left", padx=2)
        self.search_status = tk.Label(_search_frame, text="", fg="gray")
        self.search_status.pack(side="left", padx=8)
        _entry.bind("<Return>", lambda e: self.search())

        # ── Sidebar (row 1, column 0) ───────────────────────────────
        _sb_outer = tk.Frame(parent, bg="#2c3e50")
        _sb_outer.grid(row=1, column=0, sticky="nsew", padx=(8, 0), pady=(0, 8))
        _sb_outer.grid_rowconfigure(1, weight=1)
        _sb_outer.grid_columnconfigure(0, weight=1)
        tk.Label(_sb_outer, text="Contents", bg="#2c3e50", fg="white",
                 font=("TkDefaultFont", 0, "bold")).grid(
            row=0, column=0, sticky="w", padx=10, pady=(10, 6))
        _sb_canvas = tk.Canvas(_sb_outer, bg="#2c3e50", highlightthickness=0)
        _sb_canvas.grid(row=1, column=0, sticky="nsew")
        _sb_vsb = ttk.Scrollbar(_sb_outer, orient="vertical",
                                 command=_sb_canvas.yview)
        _sb_vsb.grid(row=1, column=1, sticky="ns")
        _sb_canvas.configure(yscrollcommand=_sb_vsb.set)
        self.nav_frame = tk.Frame(_sb_canvas, bg="#2c3e50")
        _sb_win = _sb_canvas.create_window((0, 0), window=self.nav_frame,
                                            anchor="nw")
        self.nav_frame.bind(
            "<Configure>",
            lambda e: _sb_canvas.configure(scrollregion=_sb_canvas.bbox("all")))
        _sb_canvas.bind(
            "<Configure>",
            lambda e: _sb_canvas.itemconfig(_sb_win, width=e.width))

        # ── State ───────────────────────────────────────────────────
        self.frame          = None   # HtmlFrame — created lazily on first visit
        self._parent        = parent
        self._search_matches: list = []
        self._search_idx    = -1
        self._path          = None
        self._display_path  = None
        self._loaded        = False

        # Bind tab change to trigger lazy load
        about_notebook.bind("<<NotebookTabChanged>>",
                            lambda e: self.load_on_tab_show(about_notebook))

    # ── Tab-change handler ──────────────────────────────────────────

    def load_on_tab_show(self, notebook: ttk.Notebook):
        """Fired by <<NotebookTabChanged>>; loads manual on first switch to Help tab."""
        if self._loaded:
            return
        try:
            tab_index = notebook.index(notebook.select())
        except Exception:
            return
        if tab_index != 0:   # Help is tab 0
            return

        # Create HtmlFrame lazily — importing tkinterweb loads a native Tcl
        # extension which can take 20–30 s on Windows.
        if self.frame is None:
            from tkinterweb import HtmlFrame
            self.frame = HtmlFrame(self._parent, messages_enabled=False)
            self.frame.grid(row=1, column=1, sticky="nsew",
                            padx=(4, 8), pady=(0, 8))
        self._loaded = True

        base_dir = (os.path.dirname(sys.executable)
                    if getattr(sys, "frozen", False)
                    else os.path.dirname(os.path.abspath(__file__)))
        help_path = os.path.join(base_dir, self.MANUAL_FILENAME)
        self._path = help_path if os.path.exists(help_path) else None

        if self._path:
            with open(help_path, "r", encoding="utf-8", errors="replace") as fh:
                html = fh.read()

            # Extract sidebar region using comment delimiters (avoids nested-div
            # ambiguity that defeats a simple <div class="sidebar">...</div> match)
            sidebar_match = re.search(
                r'<!--\s*SIDEBAR\s*-->(.*?)<!--\s*CONTENT\s*-->',
                html, re.DOTALL | re.IGNORECASE)
            sidebar_html = sidebar_match.group(1) if sidebar_match else ""

            # Populate native nav panel: part labels, section headers, link buttons
            _item_re = re.compile(
                r'<div class="part-lbl"[^>]*>(.*?)</div>'
                r'|<div class="sec-head"[^>]*>(.*?)</div>'
                r'|<a\s+href="(#[^"]+)"([^>]*)>(.*?)</a>',
                re.DOTALL | re.IGNORECASE)
            for widget in self.nav_frame.winfo_children():
                widget.destroy()
            for m in _item_re.finditer(sidebar_html):
                part_lbl, sec_head, href, attrs, link_text = m.groups()
                if part_lbl is not None:
                    text = _html.unescape(
                        re.sub(r"<[^>]+>", "", part_lbl).strip())
                    tk.Label(self.nav_frame, text=text,
                             bg="#2c3e50", fg="#f39c12",
                             font=("TkDefaultFont", 0, "bold"),
                             anchor="w", padx=6
                             ).pack(fill="x", pady=(8, 2))
                elif sec_head is not None:
                    text = _html.unescape(
                        re.sub(r"<[^>]+>", "", sec_head).strip()).upper()
                    tk.Label(self.nav_frame, text=text,
                             bg="#2c3e50", fg="#7f8c8d",
                             font=("TkDefaultFont", 8),
                             anchor="w", padx=6
                             ).pack(fill="x", pady=(6, 1))
                elif href is not None:
                    label = _html.unescape(
                        re.sub(r"<[^>]+>", "", link_text).strip())
                    anchor = href.lstrip("#")
                    indent = 20 if "padding-left" in (attrs or "") else 8
                    tk.Button(
                        self.nav_frame, text=label,
                        bg="#2c3e50", fg="#ecf0f1",
                        activebackground="#3d566e", activeforeground="white",
                        relief="flat", anchor="w", padx=indent, pady=2,
                        wraplength=190, justify="left",
                        command=lambda a=anchor: self.nav_to_anchor(a),
                    ).pack(fill="x")

            # Strip sidebar from the display copy using comment delimiters.
            # The content div is left intact; relative paths resolve because
            # the display file sits alongside CARL_user_manual.html.
            display_html = re.sub(
                r'<!--\s*SIDEBAR\s*-->.*?<!--\s*CONTENT\s*-->',
                '',
                html, count=1, flags=re.DOTALL | re.IGNORECASE)
            display_path = os.path.join(base_dir, "_carl_help_display.html")
            with open(display_path, "w", encoding="utf-8") as fh:
                fh.write(display_html)
            self._display_path = display_path
            self.frame.load_file(display_path)
        else:
            self.frame.load_html(
                "<html><body style='font-family:sans-serif;padding:20px'>"
                "<h2>Help not found</h2>"
                f"<p>Place <code>{self.MANUAL_FILENAME}</code> in the CARL "
                "folder to enable Help.</p>"
                "</body></html>"
            )

    # ── Sidebar navigation ──────────────────────────────────────────

    def nav_to_anchor(self, anchor: str):
        if self.frame is None or not self._display_path:
            return
        uri = self._display_path.replace("\\", "/")
        self.frame.load_url(f"file:///{uri}#{anchor}")

    # ── In-page search ──────────────────────────────────────────────

    def search(self):
        """Search the display HTML for query; navigate to matching sections."""
        query = self.search_var.get().strip()
        self._search_matches = []
        self._search_idx = -1
        if not query:
            self.search_status.config(text="")
            return
        if not self._display_path:
            self.search_status.config(text="Not available")
            return
        try:
            with open(self._display_path, "r", encoding="utf-8") as f:
                source = f.read()
            q_lower = query.lower()
            # Collect all heading anchors and their byte positions
            heading_anchors = [
                (m.start(), m.group(1))
                for m in re.finditer(
                    r'<h[2-4][^>]*\bid="([^"]+)"', source, re.IGNORECASE)
            ]
            matches = []
            for i, (hpos, anchor) in enumerate(heading_anchors):
                end = (heading_anchors[i + 1][0]
                       if i + 1 < len(heading_anchors) else len(source))
                section_text = re.sub(r'<[^>]+>', ' ', source[hpos:end]).lower()
                if q_lower in section_text:
                    matches.append(anchor)
            if matches:
                self._search_matches = matches
                self._search_idx = 0
                n = len(matches)
                self.search_status.config(
                    text=f"1 / {n} section{'s' if n != 1 else ''}")
                self.nav_to_anchor(matches[0])
            else:
                self.search_status.config(text="Not found")
        except Exception:
            self.search_status.config(text="Search unavailable")

    def search_nav(self, direction: int):
        if not self._search_matches:
            return
        self._search_idx = (
            (self._search_idx + direction) % len(self._search_matches))
        self.nav_to_anchor(self._search_matches[self._search_idx])
        n = len(self._search_matches)
        self.search_status.config(
            text=f"{self._search_idx + 1} / {n} section{'s' if n != 1 else ''}")

    def search_clear(self):
        self.search_var.set("")
        self._search_matches = []
        self._search_idx = -1
        self.search_status.config(text="")
