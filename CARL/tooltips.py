"""
tooltips.py — app-wide hover help for CARL.

Single source of truth: tooltips_data.py (a hand-authored dict). The manual's
button/tab-reference tables are GENERATED from that same dict (see
manual_tables.py), so the tooltip and the manual/Help documentation can never
drift apart. `TooltipController` scans the widget tree and shows the resolved
help on hover.

Text resolution order for a widget:
  1. an explicit `_carl_tooltip_text` attribute (override),
  2. `tooltips_data` by explicit `_carl_tooltip_key` (label-less / per-instance /
     colliding-label widgets — see tooltips_data.py's NOTES),
  3. `tooltips_data` by normalized widget label,
  4. a generic sentence generated from the widget type + nearest label.

Opt-out flags:
  * `_carl_disable_tooltips = True` on a widget disables its whole subtree
    (used to exclude the Plugins panel's per-descriptor field inputs, and the
    About > Help Contents sidebar).
  * `_carl_local_tooltip = True` on a widget skips it (it manages its own tip).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def _normalise_label(value: str) -> str:
    value = " ".join((value or "").replace("…", "").split()).strip()
    return value.lower().rstrip(":").replace("▼ ", "").replace("↗", "").strip()


def normalise_label(value: str) -> str:
    """Public alias for label normalization (used by panels applying scoped help)."""
    return _normalise_label(value)


# ── controller ──────────────────────────────────────────────────────────────────

class TooltipController:
    """Attach accessible hover explanations to all current and future controls."""

    _INTERACTIVE = (
        tk.Button, ttk.Button,
        tk.Checkbutton, ttk.Checkbutton,
        tk.Radiobutton, ttk.Radiobutton,
        tk.Entry, ttk.Entry,
        tk.Spinbox, ttk.Spinbox,
        tk.Listbox, tk.Text,
        tk.Scale, ttk.Scale,
        tk.Scrollbar, ttk.Scrollbar,
        tk.Menubutton, ttk.Menubutton,
        ttk.Combobox, ttk.Treeview, ttk.Notebook,
    )

    def __init__(self, root: tk.Misc, delay: int = 550, wrap: int = 380):
        self.root = root
        try:
            from tooltips_data import build_maps
            self._dict_label, self._dict_key, self._dict_tab = build_maps()
        except Exception:
            self._dict_label, self._dict_key, self._dict_tab = {}, {}, {}
        self.delay = delay
        self.wrap = wrap
        self._after_id = None
        self._tip = None
        self._active_widget = None
        self._active_notebook_tab = None
        self._pointer = None
        self._dead = False
        self._scan(root)
        # Dialogs and plugin controls are often created after startup; catch them
        # when they first become visible.
        root.bind_all("<Map>", self._on_map, add="+")

    def teardown(self) -> None:
        """Stop responding and drop live state before the root is destroyed.

        Cancels any pending help, closes an open tip, and removes the global
        <Map> binding — otherwise these dangling Tcl commands break the widget
        destroy cascade at shutdown."""
        self._dead = True
        try:
            self.root.unbind_all("<Map>")
        except Exception:
            pass
        if self._after_id:
            try:
                self.root.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    def _on_map(self, event) -> None:
        if self._dead:
            return
        try:
            self._install(event.widget)
        except (tk.TclError, AttributeError):
            pass

    def _scan(self, widget: tk.Misc) -> None:
        if self._tooltips_disabled(widget):
            return
        self._install(widget)
        for child in widget.winfo_children():
            self._scan(child)

    def _install(self, widget: tk.Misc) -> None:
        if self._tooltips_disabled(widget):
            return
        if getattr(widget, "_carl_local_tooltip", False):
            return
        if (not isinstance(widget, self._INTERACTIVE)
                and not getattr(widget, "_carl_is_control", False)):
            return
        if getattr(widget, "_carl_tooltip_bound", False):
            return
        widget._carl_tooltip_bound = True
        if isinstance(widget, ttk.Notebook):
            widget.bind("<Motion>", lambda event, w=widget: self._notebook_motion(w, event), add="+")
            widget.bind("<Leave>", lambda _event, w=widget: self._hide(w), add="+")
            widget.bind("<ButtonPress>", lambda _event, w=widget: self._hide(w), add="+")
            return
        widget.bind("<Enter>", lambda event, w=widget: self._schedule(w, event), add="+")
        widget.bind("<Leave>", lambda _event, w=widget: self._hide(w), add="+")
        widget.bind("<ButtonPress>", lambda _event, w=widget: self._hide(w), add="+")

    @staticmethod
    def _tooltips_disabled(widget: tk.Misc) -> bool:
        """Return True when this widget belongs to an opted-out panel."""
        current = widget
        while current is not None:
            if getattr(current, "_carl_disable_tooltips", False):
                return True
            try:
                parent_name = current.winfo_parent()
                current = current.nametowidget(parent_name) if parent_name else None
            except (tk.TclError, KeyError, AttributeError):
                return False
        return False

    def _schedule(self, widget: tk.Misc, event=None) -> None:
        if self._dead:
            return
        self._hide()
        if getattr(widget, "_carl_local_tooltip", False):
            return
        self._active_widget = widget
        self._pointer = self._event_pointer(event)
        text = self._tooltip_text(widget, event)
        if text:
            self._after_id = self.root.after(
                self.delay, lambda: self._show(widget, text, self._pointer))

    def _notebook_motion(self, widget: ttk.Notebook, event) -> None:
        """Show help for the individual tab under the pointer, not the notebook."""
        if self._dead:
            return
        try:
            tab_index = widget.index(f"@{event.x},{event.y}")
        except tk.TclError:
            self._hide(widget)
            return
        tab_identity = (str(widget), tab_index)
        if tab_identity == self._active_notebook_tab:
            self._pointer = self._event_pointer(event)
            if self._tip:
                self._place_tip(self._tip, widget, self._pointer)
            return
        self._hide()
        self._active_notebook_tab = tab_identity
        self._active_widget = widget
        self._pointer = self._event_pointer(event)
        text = self._tooltip_text(widget, event)
        if text:
            self._after_id = self.root.after(
                self.delay, lambda: self._show(widget, text, self._pointer))

    def _show(self, widget: tk.Misc, text: str, pointer=None) -> None:
        self._after_id = None
        if self._dead or self._active_widget is not widget or not widget.winfo_exists():
            return
        tip = tk.Toplevel(widget)
        tip.wm_overrideredirect(True)
        try:
            tip.attributes("-topmost", True)
        except tk.TclError:
            pass
        tk.Label(
            tip, text=text, justify="left",
            background="#fff9d9", foreground="#222222",
            relief="solid", borderwidth=1, wraplength=self.wrap,
            padx=7, pady=5,
        ).pack()
        tip.update_idletasks()
        self._place_tip(tip, widget, pointer)
        self._tip = tip

    @staticmethod
    def _event_pointer(event):
        if event is None:
            return None
        try:
            return int(event.x_root), int(event.y_root)
        except (AttributeError, TypeError, ValueError):
            return None

    @staticmethod
    def _place_tip(tip: tk.Toplevel, widget: tk.Misc, pointer=None) -> None:
        """Place a tooltip beside the pointer, flipping at screen edges."""
        if pointer:
            x = pointer[0] + 14
            y = pointer[1] + 18
        else:
            x = widget.winfo_rootx() + 6
            y = widget.winfo_rooty() + widget.winfo_height() + 3
        screen_w = widget.winfo_screenwidth()
        screen_h = widget.winfo_screenheight()
        tip_w = tip.winfo_reqwidth()
        tip_h = tip.winfo_reqheight()
        if x + tip_w > screen_w:
            x = max(0, (pointer[0] - tip_w - 14) if pointer else screen_w - tip_w - 6)
        if y + tip_h > screen_h:
            y = max(0, (pointer[1] - tip_h - 14) if pointer else screen_h - tip_h - 6)
        tip.wm_geometry(f"+{x}+{y}")

    def _hide(self, widget=None) -> None:
        if widget is not None and self._active_widget is not widget:
            return
        if self._after_id:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        if self._tip:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None
        self._active_widget = None
        self._active_notebook_tab = None
        self._pointer = None

    def _tooltip_text(self, widget: tk.Misc, event=None) -> str:
        explicit = getattr(widget, "_carl_tooltip_text", "")
        if explicit:
            return explicit

        # Dict-first: explicit widget key (label-less / per-instance / collisions).
        wkey = getattr(widget, "_carl_tooltip_key", "")
        if wkey and wkey in self._dict_key:
            text = self._dict_key[wkey]
            fmt = getattr(widget, "_carl_tooltip_fmt", None)
            if fmt:
                try:
                    text = text.format(**fmt)
                except Exception:
                    pass
            return text

        label = self._widget_label(widget)
        key = _normalise_label(label)
        if key in self._dict_label:
            return self._dict_label[key]

        setting = self._nearby_label(widget)
        setting = setting or label or "this control"
        setting = " ".join(setting.split()).strip().rstrip(":")

        if isinstance(widget, (tk.Checkbutton, ttk.Checkbutton)):
            return f"Turn {setting} on or off."
        if isinstance(widget, (tk.Radiobutton, ttk.Radiobutton)):
            return f"Select {setting} for this analysis or setting."
        if isinstance(widget, ttk.Combobox):
            return f"Choose the {setting} value from the available list; editable lists also accept typed values."
        if isinstance(widget, (tk.Spinbox, ttk.Spinbox, tk.Scale, ttk.Scale)):
            return f"Set {setting} within the allowed range."
        if isinstance(widget, (tk.Entry, ttk.Entry)):
            return f"Enter or edit {setting}."
        if isinstance(widget, (tk.Button, ttk.Button, tk.Menubutton, ttk.Menubutton)):
            return f"Run the {setting} action."
        if isinstance(widget, ttk.Treeview):
            return f"Select one or more rows in {setting}; use double-click or the context menu where available."
        if isinstance(widget, tk.Listbox):
            return f"Select one or more values in {setting}."
        # tk.Text (display / output panes) get no generic tooltip — they are
        # content areas, and a hover tip over them is distracting. A Text widget
        # that genuinely needs help still gets it via _carl_tooltip_key/_text,
        # which are resolved before these type-based fallbacks.
        if isinstance(widget, ttk.Notebook):
            tab_label = self._notebook_tab_label(widget, event)
            if tab_label:
                nt = _normalise_label(tab_label)
                return (self._dict_tab.get(nt)
                        or f"Open the {tab_label} tools in this section.")
            return "Move over a tab to see what that specific set of tools does."
        if isinstance(widget, (tk.Scrollbar, ttk.Scrollbar)):
            try:
                orientation = str(widget.cget("orient"))
            except tk.TclError:
                orientation = ""
            return f"Scroll this area {orientation or 'to view additional content'}."
        return ""

    @staticmethod
    def _notebook_tab_label(widget: ttk.Notebook, event=None) -> str:
        if event is None:
            return ""
        try:
            tab_index = widget.index(f"@{event.x},{event.y}")
            return str(widget.tab(tab_index, "text")).strip()
        except tk.TclError:
            return ""

    def _widget_label(self, widget: tk.Misc) -> str:
        try:
            return str(widget.cget("text")).strip()
        except tk.TclError:
            return ""

    def _nearby_label(self, widget: tk.Misc) -> str:
        """Find the closest visible label/header that describes a field."""
        parent = widget.nametowidget(widget.winfo_parent())
        try:
            info = widget.grid_info()
        except tk.TclError:
            info = {}
        if info:
            row = int(info.get("row", 0))
            column = int(info.get("column", 0))
            scored = []
            for sibling in parent.winfo_children():
                if not isinstance(sibling, (tk.Label, ttk.Label)):
                    continue
                try:
                    text = str(sibling.cget("text")).strip()
                    sibling_info = sibling.grid_info()
                except tk.TclError:
                    continue
                if not text or not sibling_info:
                    continue
                srow = int(sibling_info.get("row", 0))
                scol = int(sibling_info.get("column", 0))
                if srow == row:
                    score = abs(column - scol) + (0 if scol <= column else 2)
                elif scol == column and srow < row:
                    score = 5 + row - srow
                else:
                    continue
                scored.append((score, text))
            if scored:
                return min(scored, key=lambda item: item[0])[1]

        siblings = parent.winfo_children()
        try:
            index = siblings.index(widget)
        except ValueError:
            return ""
        for sibling in reversed(siblings[:index]):
            if isinstance(sibling, (tk.Label, ttk.Label)):
                try:
                    text = str(sibling.cget("text")).strip()
                except tk.TclError:
                    text = ""
                if text:
                    return text
        return ""
