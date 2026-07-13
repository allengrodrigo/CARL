#!/usr/bin/env python3
"""Interactive FigTree-style viewer for phylogenetic trees (Newick/NEXUS)."""

from __future__ import annotations

import copy
import math
import os
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import messagebox, ttk

_CACHE_DIR = Path(tempfile.gettempdir()) / "carl-matplotlib"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_CACHE_DIR))
os.environ.setdefault("XDG_CACHE_HOME", str(_CACHE_DIR))

from Bio import Phylo
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

from phylogeny_tools import parse_node_support
from ui_helpers import add_tooltip


EDGE_COLOR = "#46505b"
ERROR_COLOR = "#c23b3b"
NODE_LABEL_COLOR = "#862d2d"

_OPEN_VIEWERS = {}


def _support_text(clade) -> str:
    """Compact label drawn next to a node — values only (e.g. '98' or '85.6/98')."""
    support = parse_node_support(clade)
    if not support:
        return ""
    return "/".join(f"{v:g}" for v in support.values())


def _support_detail(clade) -> str:
    """Labelled string for the hover/details panel (e.g. 'posterior=0.98')."""
    support = parse_node_support(clade)
    if not support:
        return ""
    if list(support.keys()) == ["support"]:
        return f"{support['support']:g}"
    return ", ".join(f"{k}={v:g}" for k, v in support.items())


class PhylogenyViewer:
    def __init__(self, parent, tree_file: str):
        self.source = Path(tree_file).expanduser().resolve()
        self.original_tree = Phylo.read(str(self.source), "newick")
        self.original_tree.rooted = False
        self.window = tk.Toplevel(parent)
        self.window.title(f"Phylogeny Viewer - {self.source.name}")
        self.window.geometry("1280x850")
        self.window.minsize(920, 650)

        self.layout_var = tk.StringVar(value="Rectangular")
        self.branch_var = tk.StringVar(value="Branch lengths")
        self.root_var = tk.StringVar(value="Unrooted")
        self.order_var = tk.StringVar(value="Original")
        self.node_labels_var = tk.BooleanVar(value=True)
        self.tip_labels_var = tk.BooleanVar(value=True)
        self.root_stem_var = tk.DoubleVar(value=0.0)
        self.root_stem_label_var = tk.StringVar(value="0%")
        self._applied_root_mode = "Unrooted"
        self._hover_items = []
        self._annotation = None
        self._redraw_after = None
        self._dragging_root_stem = False
        self._root_drag_info = None

        self._build_ui()
        self._redraw()
        self.window.protocol("WM_DELETE_WINDOW", self.close)

    def is_open(self) -> bool:
        try:
            return bool(self.window.winfo_exists())
        except tk.TclError:
            return False

    def close(self):
        """Close the viewer and all of its owned resources exactly once."""
        if self._redraw_after is not None:
            try:
                self.window.after_cancel(self._redraw_after)
            except tk.TclError:
                pass
            self._redraw_after = None
        try:
            self.figure.clear()
        except (AttributeError, RuntimeError):
            pass
        for key, viewer in list(_OPEN_VIEWERS.items()):
            if viewer is self:
                _OPEN_VIEWERS.pop(key, None)
        try:
            if self.window.winfo_exists():
                self.window.destroy()
        except tk.TclError:
            pass

    def _build_ui(self):
        controls = ttk.Frame(self.window, padding=(7, 6))
        controls.pack(fill=tk.X)

        display_row = ttk.Frame(controls)
        display_row.pack(fill=tk.X)
        self._combo_control(
            display_row, "Layout", self.layout_var, ("Rectangular", "Circular"),
            "Choose a conventional rectangular tree or a circular display.")
        self._combo_control(
            display_row, "Branches", self.branch_var, ("Branch lengths", "Cladogram"),
            "Branch lengths uses the tree's branch lengths; cladogram shows topology only.")
        self._combo_control(
            display_row, "Order", self.order_var, ("Original", "Increasing", "Decreasing"),
            "Reorder sibling clades by descendant count without changing topology.")

        node_cb = ttk.Checkbutton(
            display_row, text="Node labels", variable=self.node_labels_var,
            command=self._schedule_redraw)
        node_cb.pack(side=tk.LEFT, padx=(8, 2))
        add_tooltip(node_cb, "Show internal-node support labels (e.g. bootstrap, posterior, or SH-aLRT/UFBoot).")
        tip_cb = ttk.Checkbutton(
            display_row, text="Tip labels", variable=self.tip_labels_var,
            command=self._schedule_redraw)
        tip_cb.pack(side=tk.LEFT, padx=2)
        add_tooltip(tip_cb, "Show or hide terminal taxon names.")

        root_row = ttk.Frame(controls, padding=(0, 6, 0, 0))
        root_row.pack(fill=tk.X)
        self._combo_control(
            root_row, "Root method", self.root_var, ("Unrooted", "Midpoint", "Outgroup"),
            "Unrooted preserves the tree as read; midpoint is provisional; outgroup uses the selected taxa.",
            auto_redraw=False)
        apply_root_btn = ttk.Button(root_row, text="Apply Root", command=self._apply_root)
        apply_root_btn.pack(side=tk.LEFT, padx=(0, 12))
        add_tooltip(
            apply_root_btn,
            "Apply the selected root method. For Outgroup, first select one or more taxa in the right panel.")
        ttk.Label(root_row, text="Root stem").pack(side=tk.LEFT, padx=(0, 4))
        root_scale = ttk.Scale(
            root_row, from_=0, to=50, variable=self.root_stem_var,
            command=self._root_stem_changed, length=210)
        root_scale.pack(side=tk.LEFT)
        add_tooltip(
            root_scale,
            "Adjust the display-only root stem from 0% to 50% of tree depth. You can also drag its square handle on the tree.")
        ttk.Label(root_row, textvariable=self.root_stem_label_var, width=5).pack(
            side=tk.LEFT, padx=(4, 3))
        reset_stem_btn = ttk.Button(root_row, text="Reset stem", command=self._reset_root_stem)
        reset_stem_btn.pack(side=tk.LEFT)
        add_tooltip(reset_stem_btn, "Return the display-only root stem length to zero.")

        body = ttk.PanedWindow(self.window, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))

        plot_frame = ttk.Frame(body)
        self.figure = Figure(figsize=(9, 7), dpi=100, facecolor="white")
        self.ax = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        toolbar_frame = ttk.Frame(plot_frame)
        toolbar_frame.pack(fill=tk.X)
        self.toolbar = NavigationToolbar2Tk(self.canvas, toolbar_frame, pack_toolbar=False)
        self.toolbar.update()
        self.toolbar.pack(side=tk.LEFT, fill=tk.X)
        add_tooltip(self.canvas.get_tk_widget(),
                    "Hover over a tip or internal node to see taxon membership and node support.")
        body.add(plot_frame, weight=5)

        side = ttk.Frame(body, padding=(7, 3), width=310)
        body.add(side, weight=1)
        outgroup_frame = ttk.LabelFrame(side, text="Outgroup taxa", padding=5)
        outgroup_frame.pack(fill=tk.X)
        ttk.Label(
            outgroup_frame,
            text="Select one taxon or a monophyletic set, then choose Root: Outgroup.",
            wraplength=270,
            justify="left",
        ).pack(fill=tk.X, pady=(0, 4))
        list_frame = ttk.Frame(outgroup_frame)
        list_frame.pack(fill=tk.X)
        self.outgroup_list = tk.Listbox(
            list_frame, selectmode=tk.EXTENDED, exportselection=False, height=9)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.outgroup_list.yview)
        self.outgroup_list.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.outgroup_list.pack(fill=tk.X, expand=True)
        for terminal in self.original_tree.get_terminals():
            self.outgroup_list.insert(tk.END, terminal.name or "")
        self.outgroup_list.bind("<<ListboxSelect>>", lambda _event: self._outgroup_changed())
        add_tooltip(
            self.outgroup_list,
            "Select the taxon or taxa assumed to fall outside the ingroup. This assumption determines the displayed root.")
        outgroup_buttons = ttk.Frame(outgroup_frame)
        outgroup_buttons.pack(fill=tk.X, pady=(4, 0))
        clear_btn = ttk.Button(outgroup_buttons, text="Clear selection", command=self._clear_outgroup)
        clear_btn.pack(side=tk.RIGHT)
        add_tooltip(clear_btn, "Clear all selected outgroup taxa.")
        root_here_btn = ttk.Button(outgroup_buttons, text="Root with selection", command=self._root_with_selection)
        root_here_btn.pack(side=tk.RIGHT, padx=(0, 5))
        add_tooltip(root_here_btn, "Set Root method to Outgroup and root the tree using the selected taxa.")

        details = ttk.LabelFrame(side, text="Node details", padding=5)
        details.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self.detail_text = tk.Text(
            details, height=14, wrap=tk.WORD, font=("TkDefaultFont", 9),
            background="#f6f7f8", relief="flat", padx=5, pady=5)
        self.detail_text.pack(fill=tk.BOTH, expand=True, pady=(7, 0))
        self.detail_text.insert(
            "1.0",
            "Hover over a tip or internal node to inspect taxon membership and node support.",
        )
        self.detail_text.config(state="disabled")

        self.status_var = tk.StringVar()
        status = ttk.Label(
            self.window, textvariable=self.status_var, anchor="w", padding=(8, 4),
            foreground="#4c5661")
        status.pack(fill=tk.X)
        add_tooltip(status, "Explains how the current root and branch geometry should be interpreted.")

        self.canvas.mpl_connect("motion_notify_event", self._on_hover)
        self.canvas.mpl_connect("button_press_event", self._on_canvas_press)
        self.canvas.mpl_connect("button_release_event", self._on_canvas_release)
        self.canvas.mpl_connect("figure_leave_event", self._hide_annotation)

    def _combo_control(self, parent, label, variable, values, tooltip, auto_redraw=True):
        frame = ttk.Frame(parent)
        frame.pack(side=tk.LEFT, padx=(0, 7))
        text = ttk.Label(frame, text=label)
        text.pack(side=tk.LEFT, padx=(0, 3))
        combo = ttk.Combobox(
            frame, textvariable=variable, values=values, state="readonly", width=13)
        combo.pack(side=tk.LEFT)
        if auto_redraw:
            combo.bind("<<ComboboxSelected>>", lambda _event: self._schedule_redraw())
        add_tooltip(text, tooltip)
        add_tooltip(combo, tooltip)

    def _clear_outgroup(self):
        self.outgroup_list.selection_clear(0, tk.END)

    def _root_with_selection(self):
        self.root_var.set("Outgroup")
        self._apply_root()

    def _apply_root(self):
        if self.root_var.get() == "Outgroup" and not self._selected_outgroups():
            messagebox.showwarning(
                "Select an outgroup",
                "Select one or more outgroup taxa in the right panel, then click Apply Root.",
                parent=self.window,
            )
            return
        self._applied_root_mode = self.root_var.get()
        self._redraw()

    def _root_stem_changed(self, value=None):
        current = float(value) if value is not None else self.root_stem_var.get()
        self.root_stem_label_var.set(f"{current:.0f}%")
        self._schedule_redraw()

    def _reset_root_stem(self):
        self.root_stem_var.set(0.0)
        self._root_stem_changed(0.0)

    def _outgroup_changed(self):
        return

    def _schedule_redraw(self):
        if self._redraw_after is not None:
            self.window.after_cancel(self._redraw_after)
        self._redraw_after = self.window.after(40, self._redraw)

    def _selected_outgroups(self) -> list[str]:
        return [self.outgroup_list.get(index) for index in self.outgroup_list.curselection()]

    def _display_tree(self):
        tree = copy.deepcopy(self.original_tree)
        root_mode = self._applied_root_mode
        note = (
            "Original topology shown as unrooted; the displayed base, start angle, "
            "and tip order do not imply a biological root."
        )
        if root_mode == "Midpoint":
            tree.root_at_midpoint()
            tree.rooted = True
            note = "Midpoint root is a provisional display assumption and does not establish evolutionary direction."
        elif root_mode == "Outgroup":
            selected = self._selected_outgroups()
            if not selected:
                raise ValueError("Select at least one outgroup taxon in the right panel.")
            lookup = {terminal.name or "": terminal for terminal in tree.get_terminals()}
            targets = [lookup[name] for name in selected if name in lookup]
            if not targets:
                raise ValueError("The selected outgroup taxa were not found in the tree.")
            tree.root_with_outgroup(*targets)
            tree.rooted = True
            note = "Outgroup root is based on your selected taxa: " + ", ".join(selected)

        order = self.order_var.get()
        if order == "Increasing":
            tree.ladderize(reverse=False)
        elif order == "Decreasing":
            tree.ladderize(reverse=True)
        return tree, note

    def _redraw(self):
        self._redraw_after = None
        self.ax.clear()
        self._hover_items = []
        try:
            tree, note = self._display_tree()
            if self.layout_var.get() == "Circular":
                self._draw_circular(tree)
            else:
                self._draw_rectangular(tree)
            if self._applied_root_mode != "Unrooted":
                note += (
                    f"  Root stem: {self.root_stem_var.get():.0f}% of tree depth "
                    "(display only; drag the square handle to change it)."
                )
            self.status_var.set(note)
        except Exception as exc:
            self.ax.axis("off")
            self.ax.text(0.5, 0.5, str(exc), transform=self.ax.transAxes,
                         ha="center", va="center", color=ERROR_COLOR, fontsize=11)
            self.status_var.set(str(exc))
        self.figure.tight_layout(pad=1.0)
        self.canvas.draw_idle()

    def _radial_positions(self, tree):
        terminals = tree.get_terminals()
        step = 2 * math.pi / max(len(terminals), 1)
        terminal_index = {terminal: index for index, terminal in enumerate(terminals)}
        angles = {terminal: index * step for terminal, index in terminal_index.items()}
        for clade in tree.find_clades(order="postorder"):
            if not clade.is_terminal():
                descendants = clade.get_terminals()
                angles[clade] = sum(terminal_index[item] for item in descendants) / len(descendants) * step

        if self.branch_var.get() == "Branch lengths":
            depths = tree.depths(unit_branch_lengths=False)
            maximum = max(depths.values()) if depths else 1
            if not maximum:
                depths = tree.depths(unit_branch_lengths=True)
                maximum = max(depths.values()) if depths else 1
            radii = {clade: 0.78 * depth / maximum for clade, depth in depths.items()}
        else:
            heights = {}
            for clade in tree.find_clades(order="postorder"):
                heights[clade] = 0 if clade.is_terminal() else 1 + max(
                    heights[child] for child in clade.clades)
            maximum = heights.get(tree.root, 1) or 1
            radii = {clade: 0.78 * (maximum - height) / maximum
                     for clade, height in heights.items()}
        return terminals, angles, radii

    def _draw_circular(self, tree):
        terminals, angles, radii = self._radial_positions(tree)
        self.ax.set_aspect("equal")
        self.ax.axis("off")
        for parent in tree.find_clades(order="preorder"):
            children = list(parent.clades)
            if not children:
                continue
            child_angles = [angles[child] for child in children]
            self._draw_arc(radii[parent], min(child_angles), max(child_angles))
            for child in children:
                angle = angles[child]
                start, end = radii[parent], radii[child]
                self.ax.plot(
                    [start * math.cos(angle), end * math.cos(angle)],
                    [start * math.sin(angle), end * math.sin(angle)],
                    color=EDGE_COLOR, linewidth=1.15, solid_capstyle="round")
                self._add_node_label(child, end * math.cos(angle), end * math.sin(angle))
                self._add_hover_item(child, end * math.cos(angle), end * math.sin(angle))

        self._root_drag_info = None
        if self._applied_root_mode != "Unrooted":
            stem = 0.78 * self.root_stem_var.get() / 100.0
            handle = (-stem, 0.0)
            self.ax.plot([handle[0], 0.0], [0.0, 0.0], color="#222222", linewidth=1.8)
            self.ax.plot([handle[0]], [handle[1]], marker="s", markersize=6,
                         markerfacecolor="white", markeredgecolor="#222222", zorder=8)
            self._root_drag_info = {
                "mode": "circular", "handle": handle, "scale": 0.78,
            }

        if self.tip_labels_var.get():
            label_radius = max(0.84, max(radii.values(), default=0.78) + 0.06)
            for terminal in terminals:
                angle = angles[terminal]
                degrees = math.degrees(angle)
                on_left = 90 < degrees < 270
                rotation = degrees + 180 if on_left else degrees
                self.ax.text(
                    label_radius * math.cos(angle), label_radius * math.sin(angle),
                    terminal.name or "", rotation=rotation, rotation_mode="anchor",
                    ha="right" if on_left else "left", va="center", fontsize=9,
                    color="#151515")
        self.ax.set_xlim(-1.16, 1.16)
        self.ax.set_ylim(-1.16, 1.16)

    def _draw_arc(self, radius, start, end):
        if end < start:
            start, end = end, start
        count = max(12, int((end - start) * 45))
        theta = [start + (end - start) * index / count for index in range(count + 1)]
        self.ax.plot([radius * math.cos(value) for value in theta],
                     [radius * math.sin(value) for value in theta],
                     color=EDGE_COLOR, linewidth=1.0)

    def _rectangular_positions(self, tree):
        terminals = tree.get_terminals()
        y = {terminal: float(len(terminals) - index - 1)
             for index, terminal in enumerate(terminals)}
        for clade in tree.find_clades(order="postorder"):
            if not clade.is_terminal():
                y[clade] = sum(y[child] for child in clade.clades) / len(clade.clades)

        if self.branch_var.get() == "Branch lengths":
            x = tree.depths(unit_branch_lengths=False)
            if not max(x.values(), default=0):
                x = tree.depths(unit_branch_lengths=True)
        else:
            heights = {}
            for clade in tree.find_clades(order="postorder"):
                heights[clade] = 0 if clade.is_terminal() else 1 + max(
                    heights[child] for child in clade.clades)
            maximum = heights.get(tree.root, 1)
            x = {clade: maximum - height for clade, height in heights.items()}
        return terminals, x, y

    def _draw_rectangular(self, tree):
        terminals, x, y = self._rectangular_positions(tree)
        for parent in tree.find_clades(order="preorder"):
            children = list(parent.clades)
            if not children:
                continue
            child_ys = [y[child] for child in children]
            self.ax.plot([x[parent], x[parent]], [min(child_ys), max(child_ys)],
                         color=EDGE_COLOR, linewidth=1.0)
            for child in children:
                self.ax.plot([x[parent], x[child]], [y[child], y[child]],
                             color=EDGE_COLOR, linewidth=1.15, solid_capstyle="round")
                self._add_node_label(child, x[child], y[child], rectangular=True)
                self._add_hover_item(child, x[child], y[child])

        maximum = max(x.values(), default=1) or 1
        self._root_drag_info = None
        minimum_x = -maximum * 0.02
        if self._applied_root_mode != "Unrooted":
            stem = maximum * self.root_stem_var.get() / 100.0
            root_x, root_y = x[tree.root], y[tree.root]
            handle = (root_x - stem, root_y)
            self.ax.plot([handle[0], root_x], [root_y, root_y], color="#222222", linewidth=1.8)
            self.ax.plot([handle[0]], [handle[1]], marker="s", markersize=6,
                         markerfacecolor="white", markeredgecolor="#222222", zorder=8)
            minimum_x = min(minimum_x, handle[0] - maximum * 0.02)
            self._root_drag_info = {
                "mode": "rectangular", "handle": handle,
                "origin_x": root_x, "scale": maximum,
            }
        label_gap = maximum * 0.015
        if self.tip_labels_var.get():
            for terminal in terminals:
                self.ax.text(x[terminal] + label_gap, y[terminal], terminal.name or "",
                             ha="left", va="center", fontsize=9, color="#151515")
        self.ax.set_ylim(-1, max(len(terminals), 1))
        self.ax.set_xlim(minimum_x, maximum * (1.28 if self.tip_labels_var.get() else 1.04))
        self.ax.set_yticks([])
        if self.branch_var.get() == "Branch lengths":
            self.ax.set_xlabel("Substitutions per site / character distance")
        else:
            self.ax.set_xlabel("Topology depth (branch lengths ignored)")
        for side in ("top", "right", "left"):
            self.ax.spines[side].set_visible(False)
        self.ax.tick_params(axis="x", colors="#555555", labelsize=8)

    def _add_node_label(self, clade, x, y, rectangular=False):
        if clade.is_terminal() or not self.node_labels_var.get():
            return
        text = _support_text(clade)
        if not text:
            return
        offset = (4, 4) if rectangular else (3, 3)
        self.ax.annotate(
            text, (x, y), xytext=offset, textcoords="offset points", fontsize=7,
            color=NODE_LABEL_COLOR, ha="left", va="bottom",
            bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.78, "pad": 0.3})

    def _add_hover_item(self, clade, x, y):
        taxa = sorted(terminal.name or "" for terminal in clade.get_terminals())
        if clade.is_terminal():
            text = f"Taxon: {clade.name or ''}"
        else:
            support = _support_detail(clade) or "not labelled"
            shown = ", ".join(taxa[:8]) + ("..." if len(taxa) > 8 else "")
            text = f"Split/clade: {shown}\nDescendant taxa: {len(taxa)}\nNode support: {support}"
        self._hover_items.append({"x": x, "y": y, "text": text})

    def _on_canvas_press(self, event):
        info = self._root_drag_info
        if not info or event.inaxes is not self.ax or event.x is None or event.y is None:
            return
        px, py = self.ax.transData.transform(info["handle"])
        if math.hypot(px - event.x, py - event.y) <= 14:
            self._dragging_root_stem = True

    def _on_canvas_release(self, _event):
        self._dragging_root_stem = False

    def _drag_root_stem(self, event):
        info = self._root_drag_info
        if not info or event.xdata is None:
            return
        if info["mode"] == "rectangular":
            value = (info["origin_x"] - event.xdata) / info["scale"] * 100.0
        else:
            value = max(0.0, -event.xdata) / info["scale"] * 100.0
        value = min(50.0, max(0.0, value))
        self.root_stem_var.set(value)
        self.root_stem_label_var.set(f"{value:.0f}%")
        self._schedule_redraw()

    def _on_hover(self, event):
        if self._dragging_root_stem:
            self._drag_root_stem(event)
            return
        if event.inaxes is not self.ax or event.x is None or event.y is None:
            self._hide_annotation()
            return
        nearest = None
        distance = 13.0
        for item in self._hover_items:
            px, py = self.ax.transData.transform((item["x"], item["y"]))
            candidate = math.hypot(px - event.x, py - event.y)
            if candidate < distance:
                nearest = item
                distance = candidate
        if nearest is None:
            self._hide_annotation()
            return
        if self._annotation is None:
            self._annotation = self.ax.annotate(
                "", xy=(nearest["x"], nearest["y"]), xytext=(14, 14),
                textcoords="offset points", fontsize=8.5, ha="left", va="bottom",
                bbox={"boxstyle": "round,pad=0.45", "facecolor": "#fffdf2",
                      "edgecolor": "#666666", "alpha": 0.96},
                arrowprops={"arrowstyle": "->", "color": "#666666"})
        self._annotation.xy = (nearest["x"], nearest["y"])
        self._annotation.set_text(nearest["text"])
        self._annotation.set_visible(True)
        self._set_detail_text(nearest["text"])
        self.canvas.draw_idle()

    def _hide_annotation(self, _event=None):
        if self._annotation is not None and self._annotation.get_visible():
            self._annotation.set_visible(False)
            self.canvas.draw_idle()

    def _set_detail_text(self, text):
        self.detail_text.config(state="normal")
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert("1.0", text)
        self.detail_text.config(state="disabled")


def open_phylogeny_viewer(parent, tree_file: str):
    """Open or raise the single viewer for this parent and tree file."""

    source = str(Path(tree_file).expanduser().resolve())
    key = (str(parent), source)
    existing = _OPEN_VIEWERS.get(key)
    if existing and existing.is_open():
        existing.window.deiconify()
        existing.window.lift()
        existing.window.focus_set()
        return existing
    _OPEN_VIEWERS.pop(key, None)
    viewer = PhylogenyViewer(parent, source)
    _OPEN_VIEWERS[key] = viewer
    return viewer
