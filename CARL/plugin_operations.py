"""
plugin_operations.py
Plugins panel for CARL — Run Plugin and Generate Descriptor tabs.
Self-contained; no circular imports with ui_app.py.
"""

import copy
import json
import os
import queue
import re
import shlex
import shutil
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkFont
from tkinter import ttk, filedialog, messagebox, simpledialog

import plugin_manager as _pm

MONO_FONT     = ("Courier New", 9)
LABEL_W       = 26
FIELD_TYPES   = ["string", "integer", "float", "boolean", "choice", "file", "outfile", "directory"]
DISPLAY_MODES = ["terminal", "file", "both"]
SEPARATORS    = [" ", "=", ""]
MULTI_SEPS    = ["", ","]
_NUMERIC      = {"integer", "float"}


# ── module-level helpers ───────────────────────────────────────────────────────

def _field_key(f: dict) -> str:
    flag = f.get("flag", "")
    return flag if flag else f"@pos{f.get('positional_order', 0)}"


def _candidate_executables(descriptor: dict) -> list[str]:
    # Purely descriptor-driven: a plugin declares its fallbacks via
    # alt_executables (e.g. iqtree3/iqtree2/iqtree + .exe). No hard-coded,
    # plugin-specific name lists here — that belongs in the descriptor.
    names = [descriptor.get("executable", "")] + descriptor.get("alt_executables", [])
    seen, out = set(), []
    for name in names:
        name = os.path.expanduser(str(name or "").strip())
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _find_exe(descriptor: dict) -> str | None:
    for name in _candidate_executables(descriptor):
        has_path = (
            os.path.isabs(name) or os.sep in name
            or (os.altsep is not None and os.altsep in name)
        )
        if has_path:
            if os.path.isfile(name) and os.access(name, os.X_OK):
                return name
            continue
        if shutil.which(name):
            return name
    return None


# ══════════════════════════════════════════════════════════════════════════════
# PluginsPanel
# ══════════════════════════════════════════════════════════════════════════════

class PluginsPanel:

    def __init__(self, parent: tk.Frame,
                 ui_font=None, mono_font=None, ui_font_bold=None):
        self._parent        = parent
        self._mono_font     = mono_font     or MONO_FONT
        self._ui_font_bold  = ui_font_bold  # may be None; used for treeview section headers

        # ── Run Plugin state ──────────────────────────────────────────────────
        self._rp_descriptor   = None
        self._rp_field_vars   = {}
        self._rp_field_meta   = {}
        self._rp_field_rows   = {}
        self._rp_mutex_groups = {}
        self._rp_has_common   = False
        self._rp_descriptor_path = None
        self._rp_proc           = None
        self._rp_stopping       = False
        self._rp_output_q       = queue.Queue()
        self._rp_results_files  = []   # list of {"path", "output_type", "description"}
        self._rp_results_mpl_fig = None
        self._rp_res_text_widget = None   # current results Text widget (dynamic)
        self._rp_current_result_idx = None
        self._rp_manual_command = False

        # ── Generate Descriptor state ─────────────────────────────────────────
        self._gd_descriptor  = _empty_descriptor()
        self._gd_filepath    = None
        self._gd_dirty       = False
        self._gd_current_sec = None

        self._build_ui()
        self._rp_poll_output()

    # ── top-level UI ──────────────────────────────────────────────────────────

    def _build_ui(self):
        nb = ttk.Notebook(self._parent)
        nb.pack(fill="both", expand=True)
        self._nb = nb

        run_frame = tk.Frame(nb)
        nb.add(run_frame, text="Run Plugin")
        self._build_run_tab(run_frame)

        gen_frame = tk.Frame(nb)
        nb.add(gen_frame, text="Generate Descriptor")
        self._build_generate_tab(gen_frame)

    # ══════════════════════════════════════════════════════════════════════════
    # RUN PLUGIN TAB
    # ══════════════════════════════════════════════════════════════════════════

    def _build_run_tab(self, parent: tk.Frame):
        # ── info bar ──
        bar = ttk.Frame(parent, padding=(6, 4))
        bar.pack(fill=tk.X)
        ttk.Button(bar, text="Open Descriptor…",
                   command=self._rp_cmd_open).pack(side=tk.LEFT)
        self._rp_lbl_plugin = ttk.Label(bar, text="No descriptor loaded.",
                                        foreground="#777")
        self._rp_lbl_plugin.pack(side=tk.LEFT, padx=12)
        self._rp_lbl_exe = ttk.Label(bar, text="")
        self._rp_lbl_exe.pack(side=tk.LEFT, padx=4)

        # ── horizontal split: left (sections + fields) | right (command + output) ──
        hpw = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        hpw.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        # ── left pane ──
        left = ttk.Frame(hpw)
        hpw.add(left, weight=3)

        sec_frame = ttk.LabelFrame(left, text="Sections")
        sec_frame.pack(fill=tk.X, padx=4, pady=(4, 0))
        self._rp_sec_lb = tk.Listbox(sec_frame, height=6, selectmode=tk.SINGLE,
                                     activestyle="dotbox", exportselection=False)
        self._rp_sec_lb.pack(fill=tk.X, padx=2, pady=2)
        self._rp_sec_lb.bind("<<ListboxSelect>>", self._rp_on_section_select)

        fld_outer  = ttk.LabelFrame(left, text="Fields")
        fld_outer.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        fld_canvas = tk.Canvas(fld_outer, borderwidth=0, highlightthickness=0)
        fld_vsb    = ttk.Scrollbar(fld_outer, orient="vertical", command=fld_canvas.yview)
        fld_canvas.configure(yscrollcommand=fld_vsb.set)
        fld_vsb.pack(side=tk.RIGHT, fill=tk.Y)
        fld_canvas.pack(fill=tk.BOTH, expand=True)
        self._rp_fld_frame = ttk.Frame(fld_canvas)
        _win = fld_canvas.create_window((0, 0), window=self._rp_fld_frame, anchor="nw")
        self._rp_fld_frame.bind("<Configure>",
            lambda e, c=fld_canvas: c.configure(scrollregion=c.bbox("all")))
        fld_canvas.bind("<Configure>",
            lambda e, c=fld_canvas, w=_win: c.itemconfig(w, width=e.width))
        fld_canvas.bind("<MouseWheel>",
            lambda e, c=fld_canvas: c.yview_scroll(int(-1*(e.delta/120)), "units"))
        self._rp_fld_canvas = fld_canvas

        # ── right pane ──
        right = ttk.Frame(hpw)
        hpw.add(right, weight=2)

        # command bar — 3-line wrapped, scrollable, editable command
        cmd_bar = ttk.Frame(right, padding=(4, 3))
        cmd_bar.pack(fill=tk.X)
        ttk.Label(cmd_bar, text="$", font=self._mono_font).pack(
            side=tk.LEFT, padx=(0, 4), anchor="n")
        self._rp_stop_btn = ttk.Button(cmd_bar, text="Stop", command=self._rp_stop,
                                       width=7, state="disabled")
        self._rp_stop_btn.pack(side=tk.RIGHT, anchor="n")
        self._rp_run_btn  = ttk.Button(cmd_bar, text="Run", command=self._rp_run, width=7)
        self._rp_run_btn.pack(side=tk.RIGHT, padx=2, anchor="n")
        self._rp_rebuild_btn = ttk.Button(cmd_bar, text="Rebuild", width=8,
                                          command=self._rp_rebuild_command)
        self._rp_rebuild_btn.pack(side=tk.RIGHT, padx=(0, 4), anchor="n")

        cmd_wrap = ttk.Frame(cmd_bar)
        cmd_wrap.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self._rp_cmd_text = tk.Text(cmd_wrap, height=3, wrap=tk.WORD,
                                    font=self._mono_font, undo=True)
        cmd_sb = ttk.Scrollbar(cmd_wrap, orient="vertical",
                               command=self._rp_cmd_text.yview)
        self._rp_cmd_text.configure(yscrollcommand=cmd_sb.set)
        cmd_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._rp_cmd_text.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._rp_cmd_text.insert("1.0", "(no descriptor loaded)")
        self._rp_cmd_text.bind("<KeyRelease>", self._rp_on_command_edited)
        self._rp_cmd_text.bind("<Return>", self._rp_run_from_entry)

        # vertical split: terminal (top) / results (bottom)
        vpw = ttk.PanedWindow(right, orient=tk.VERTICAL)
        vpw.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 4))
        self._rp_vpw = vpw
        vpw.bind("<Configure>", self._rp_center_sash_once)

        # ── terminal pane ──
        out_pane = ttk.LabelFrame(vpw, text="Output")
        vpw.add(out_pane, weight=1)
        ttk.Button(out_pane, text="Clear",
                   command=self._rp_cmd_clear).pack(side=tk.TOP, anchor="e", padx=4, pady=2)
        self._rp_out_txt = tk.Text(out_pane, wrap=tk.WORD, font=self._mono_font,
                                   state="disabled", bg="#1e1e1e", fg="#d4d4d4",
                                   insertbackground="#d4d4d4")
        ovsb = ttk.Scrollbar(out_pane, orient="vertical", command=self._rp_out_txt.yview)
        self._rp_out_txt.configure(yscrollcommand=ovsb.set)
        ovsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._rp_out_txt.pack(fill=tk.BOTH, expand=True)
        self._rp_out_txt.tag_config("summary", foreground="#e2c08d")
        self._rp_out_txt.tag_config("cmd",     foreground="#9cdcfe")
        self._rp_out_txt.tag_config("error",   foreground="#f48771")
        self._rp_out_txt.tag_config("ok",      foreground="#b5cea8")

        # ── results pane ──
        res_pane = ttk.LabelFrame(vpw, text="Results")
        vpw.add(res_pane, weight=1)
        self._rp_res_lb = tk.Listbox(res_pane, height=4, selectmode=tk.SINGLE,
                                     exportselection=False, activestyle="dotbox",
                                     font=self._mono_font)
        self._rp_res_lb.pack(fill=tk.X, padx=4, pady=(4, 0))
        self._rp_res_lb.bind("<<ListboxSelect>>", self._rp_on_result_select)

        browse_bar = ttk.Frame(res_pane)
        browse_bar.pack(fill=tk.X, padx=4, pady=(2, 0))
        ttk.Label(browse_bar, text="Add:", foreground="#777").pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(browse_bar, text="Text…",  width=7,
                   command=lambda: self._rp_browse_result("text") ).pack(side=tk.LEFT, padx=1)
        ttk.Button(browse_bar, text="Tree…",  width=7,
                   command=lambda: self._rp_browse_result("tree") ).pack(side=tk.LEFT, padx=1)
        ttk.Button(browse_bar, text="Image…", width=7,
                   command=lambda: self._rp_browse_result("image")).pack(side=tk.LEFT, padx=1)
        self._rp_popout_btn = ttk.Button(browse_bar, text="⧉ Pop out", width=10,
                                         command=self._rp_popout_result, state="disabled")
        self._rp_popout_btn.pack(side=tk.RIGHT, padx=1)

        self._rp_res_render = ttk.Frame(res_pane)
        self._rp_res_render.pack(fill=tk.BOTH, expand=True, padx=4, pady=(2, 4))
        ttk.Label(self._rp_res_render, text="Results will appear here after the run.",
                  foreground="#777").pack(expand=True)

    # ── descriptor loading ────────────────────────────────────────────────────

    def _rp_cmd_open(self):
        p = filedialog.askopenfilename(
            title="Open plugin descriptor",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not p:
            return
        try:
            d      = _pm.load(p)
            errors = _pm.validate(d)
            if errors:
                messagebox.showerror("Invalid descriptor",
                    "Descriptor has errors:\n• " + "\n• ".join(errors))
                return
            self._rp_descriptor_path = p
            self._rp_load_descriptor(d)
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))

    def _rp_load_descriptor(self, d: dict):
        self._rp_descriptor   = d
        self._rp_field_vars   = {}
        self._rp_field_meta   = {}
        self._rp_field_rows   = {}
        self._rp_mutex_groups = {}
        self._rp_manual_command = False

        for sec in d.get("sections", []):
            for f in sec.get("fields", []):
                key  = _field_key(f)
                dflt = f.get("default", "")
                var  = (tk.BooleanVar(value=bool(dflt))
                        if f.get("type") == "boolean"
                        else tk.StringVar(value=str(dflt) if dflt not in ("", None) else ""))
                var.trace_add("write", self._rp_on_field_changed)
                self._rp_field_vars[key] = var
                self._rp_field_meta[key] = f
                mg = f.get("mutex_group", "")
                if mg:
                    self._rp_mutex_groups.setdefault(mg, []).append(key)

        name = d.get("name") or d.get("plugin_id") or "Unknown"
        exe  = _find_exe(d)
        self._rp_lbl_plugin.config(text=name, foreground="#000")
        if exe:
            self._rp_lbl_exe.config(text=f"executable: {exe}  ✓", foreground="green")
        else:
            self._rp_lbl_exe.config(
                text=f"executable: {d.get('executable','?')}  (not found on PATH)",
                foreground="#c00")

        self._rp_render_sections_list()
        self._rp_update_command_preview()

    # ── sections list ─────────────────────────────────────────────────────────

    def _rp_render_sections_list(self):
        self._rp_sec_lb.delete(0, tk.END)
        if not self._rp_descriptor:
            return
        secs   = self._rp_descriptor.get("sections", [])
        common = [f for s in secs for f in s.get("fields", []) if f.get("common")]
        self._rp_has_common = bool(common)
        if self._rp_has_common:
            self._rp_sec_lb.insert(tk.END, "★  Common Options")
        for sec in secs:
            name = sec.get("name") or sec.get("id") or "(unnamed)"
            self._rp_sec_lb.insert(tk.END, f"{name}  ({len(sec.get('fields',[]))})")
        if self._rp_sec_lb.size():
            self._rp_sec_lb.selection_set(0)
            self._rp_on_section_select()

    def _rp_on_section_select(self, *_):
        sel = self._rp_sec_lb.curselection()
        if not sel or not self._rp_descriptor:
            return
        idx  = sel[0]
        secs = self._rp_descriptor.get("sections", [])
        if self._rp_has_common and idx == 0:
            fields = [f for s in secs for f in s.get("fields", []) if f.get("common")]
        elif self._rp_has_common:
            fields = secs[idx - 1].get("fields", [])
        else:
            fields = secs[idx].get("fields", [])
        self._rp_render_fields(fields)

    # ── field rendering ───────────────────────────────────────────────────────

    def _rp_render_fields(self, fields: list):
        for w in self._rp_fld_frame.winfo_children():
            w.destroy()
        self._rp_field_rows = {}

        if not fields:
            ttk.Label(self._rp_fld_frame, text="No fields in this section.",
                      foreground="#888").pack(padx=16, pady=16)
            return

        for f in fields:
            key  = _field_key(f)
            var  = self._rp_field_vars.get(key)
            if var is None:
                continue
            ftype = f.get("type", "string")
            label = f.get("label") or f.get("flag") or key
            req   = f.get("required", False)
            hint  = f.get("value_hint", "")
            help_ = f.get("help", "")
            opts  = f.get("options", [])

            row = ttk.Frame(self._rp_fld_frame, padding=(0, 1))
            row.pack(fill=tk.X, padx=8)
            self._rp_field_rows[key] = row

            ttk.Label(row, text=("* " if req else "  ") + label,
                      width=LABEL_W, anchor="e",
                      foreground=("#a00" if req else "#222")).pack(side=tk.LEFT, padx=(0, 8))

            if ftype == "boolean":
                ttk.Checkbutton(row, variable=var).pack(side=tk.LEFT)
            elif ftype == "choice":
                cb = ttk.Combobox(row, textvariable=var, values=opts,
                                  state="readonly", width=24)
                # Only seed a value for required fields; optional choices stay
                # blank (omitted from the command) unless the user picks one.
                if opts and not var.get() and req:
                    var.set(opts[0])
                cb.pack(side=tk.LEFT)
            elif ftype == "file":
                ttk.Entry(row, textvariable=var, width=38).pack(side=tk.LEFT)
                ttk.Button(row, text="Browse…", width=8,
                           command=lambda v=var: v.set(
                               filedialog.askopenfilename() or v.get())
                           ).pack(side=tk.LEFT, padx=4)
            elif ftype == "outfile":
                ttk.Entry(row, textvariable=var, width=38).pack(side=tk.LEFT)
                ttk.Button(row, text="Save As…", width=8,
                           command=lambda v=var, h=hint: v.set(
                               filedialog.asksaveasfilename(initialfile=h) or v.get())
                           ).pack(side=tk.LEFT, padx=4)
            elif ftype == "directory":
                ttk.Entry(row, textvariable=var, width=38).pack(side=tk.LEFT)
                ttk.Button(row, text="Browse…", width=8,
                           command=lambda v=var: v.set(
                               filedialog.askdirectory() or v.get())
                           ).pack(side=tk.LEFT, padx=4)
            elif ftype == "integer":
                ttk.Spinbox(row, textvariable=var, from_=0, to=9999999,
                            width=12).pack(side=tk.LEFT)
            else:
                ttk.Entry(row, textvariable=var, width=38).pack(side=tk.LEFT)

            meta_parts = []
            if hint:  meta_parts.append(f"e.g. {hint}")
            if help_: meta_parts.append(help_[:90] + ("…" if len(help_) > 90 else ""))
            if meta_parts:
                ttk.Label(row, text="  " + "  |  ".join(meta_parts),
                          foreground="#777", font=("TkDefaultFont", 8),
                          wraplength=380, justify="left").pack(side=tk.LEFT, padx=6)

        self._rp_check_conditions()
        self._rp_fld_canvas.configure(scrollregion=self._rp_fld_canvas.bbox("all"))
        self._rp_fld_canvas.yview_moveto(0)

    # ── conditions + command assembly ─────────────────────────────────────────

    def _rp_on_field_changed(self, *_):
        self._rp_check_conditions()
        self._rp_update_command_preview()

    def _rp_check_conditions(self):
        for key, row in self._rp_field_rows.items():
            cond = self._rp_field_meta.get(key, {}).get("condition")
            show = True
            if cond:
                ctrl = self._rp_field_vars.get(cond.get("field", ""))
                if ctrl is not None:
                    v = ctrl.get()
                    if "equals"          in cond: show = str(v) == str(cond["equals"])
                    elif cond.get("present") is False: show = not v
                    else:                             show = bool(v)
            if show: row.pack(fill=tk.X, padx=8)
            else:    row.pack_forget()

    def _rp_active_keys(self) -> set:
        active = set()
        for key, f in self._rp_field_meta.items():
            cond = f.get("condition")
            if not cond:
                active.add(key); continue
            ctrl = self._rp_field_vars.get(cond.get("field", ""))
            if ctrl is None:
                active.add(key); continue
            v = ctrl.get()
            if "equals"          in cond: ok = str(v) == str(cond["equals"])
            elif cond.get("present") is False: ok = not v
            else:                             ok = bool(v)
            if ok: active.add(key)
        return active

    def _rp_resolve_script(self, rel: str) -> str:
        """Locate a script path relative to the descriptor, then the app dir, then cwd."""
        if os.path.isabs(rel) and os.path.isfile(rel):
            return rel
        roots = []
        if self._rp_descriptor_path:
            roots.append(os.path.dirname(self._rp_descriptor_path))
        roots.append(os.path.dirname(os.path.abspath(__file__)))
        roots.append(os.getcwd())
        for root in roots:
            cand = os.path.join(root, rel)
            if os.path.isfile(cand):
                return os.path.abspath(cand)
        return rel   # unresolved — Popen will surface a clear error

    def _rp_launch_prefix(self, exe: str) -> list:
        """A `.py` executable is run through the current interpreter so script
        plugins work without being frozen; anything else runs directly."""
        if exe.lower().endswith(".py"):
            return [sys.executable, self._rp_resolve_script(exe)]
        return [exe]

    def _rp_assemble_command(self) -> list:
        if not self._rp_descriptor:
            return []
        exe = _find_exe(self._rp_descriptor) or self._rp_descriptor.get("executable", "")
        if not exe:
            return []
        active     = self._rp_active_keys()
        named      = []
        pos_list   = []
        emitted_mg = set()
        for sec in self._rp_descriptor.get("sections", []):
            for f in sec.get("fields", []):
                key = _field_key(f)
                if key not in active:
                    continue
                var = self._rp_field_vars.get(key)
                if var is None:
                    continue
                mg = f.get("mutex_group", "")
                if mg:
                    if mg in emitted_mg: continue
                    emitted_mg.add(mg)
                flag  = f.get("flag", "")
                ftype = f.get("type", "string")
                sep   = f.get("separator", " ")
                po    = int(f.get("positional_order", 0))
                val   = var.get()
                if not flag:
                    if val: pos_list.append((po, str(val)))
                    continue
                if ftype == "boolean":
                    if val: named.append(flag)
                elif val not in ("", None, False):
                    sv = str(val)
                    if sep == " ": named.extend([flag, sv])
                    else:          named.append(f"{flag}{sep}{sv}")
        tokens = self._rp_launch_prefix(exe) + named
        for _, v in sorted(pos_list):
            tokens.append(v)
        return tokens

    def _rp_get_command(self) -> str:
        return self._rp_cmd_text.get("1.0", "end-1c")

    def _rp_set_command(self, text: str):
        self._rp_cmd_text.delete("1.0", tk.END)
        self._rp_cmd_text.insert("1.0", text)

    def _rp_update_command_preview(self):
        if self._rp_manual_command:
            return
        tokens = self._rp_assemble_command()
        display = (" ".join(f'"{t}"' if " " in t else t for t in tokens)
                   if tokens else "(no descriptor loaded)")
        self._rp_set_command(display)

    def _rp_center_sash_once(self, event):
        # ttk.PanedWindow honours child natural sizes for the initial sash, so the
        # Output Text widget starts far taller than Results. Center the sash once
        # the pane has a real height, then release control back to the user.
        if event.height > 40:
            self._rp_vpw.unbind("<Configure>")
            self._rp_vpw.sashpos(0, event.height // 2)

    def _rp_on_command_edited(self, _event=None):
        self._rp_manual_command = True

    def _rp_rebuild_command(self):
        self._rp_manual_command = False
        self._rp_update_command_preview()

    def _rp_run_from_entry(self, _event=None):
        self._rp_run()
        return "break"

    def _rp_manual_command_tokens(self) -> list:
        command = self._rp_get_command().strip()
        if not command or command == "(no descriptor loaded)":
            return []
        tokens = shlex.split(command, posix=(sys.platform != "win32"))
        if sys.platform == "win32":
            tokens = [
                token[1:-1]
                if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'"
                else token
                for token in tokens
            ]
        return tokens

    # ── run summary ───────────────────────────────────────────────────────────

    def _rp_build_run_summary(self) -> str:
        d        = self._rp_descriptor
        name     = d.get("name") or d.get("plugin_id") or "Unknown"
        citation = (d.get("citation") or "").strip()
        intro    = f"An analysis with {name}"
        if citation:
            intro += f" ({citation})"
        intro   += " was performed using the following parameters: "

        active     = self._rp_active_keys()
        emitted_mg = set()
        items      = []
        has_dflt   = False

        for sec in d.get("sections", []):
            for f in sec.get("fields", []):
                key = _field_key(f)
                if key not in active:
                    continue
                var = self._rp_field_vars.get(key)
                if var is None:
                    continue
                mg = f.get("mutex_group", "")
                if mg:
                    if mg in emitted_mg: continue
                    emitted_mg.add(mg)
                ftype    = f.get("type", "string")
                label    = f.get("label") or f.get("flag") or key
                flag     = f.get("flag", "")
                dflt     = f.get("default", None)
                val      = var.get()
                if ftype == "boolean":
                    if val: items.append(f"{label} enabled")
                    continue
                if val in ("", None):
                    continue
                sv        = str(val)
                connector = " = " if ftype in _NUMERIC else ": "
                item      = (f"{label} ({flag}){connector}{sv}" if flag
                             else f"{label}{connector}{sv}")
                dflt_str  = str(dflt) if dflt not in (None, "") else None
                if dflt_str is not None and sv == dflt_str:
                    has_dflt = True
                else:
                    items.append(item)

        params   = "; ".join(items) + "." if items else "(no parameters set)"
        sentence = intro + params
        if has_dflt:
            sentence += " All remaining arguments have been set to default values."
        return sentence

    # ── run / stop / output ───────────────────────────────────────────────────

    def _rp_run(self):
        try:
            tokens = (self._rp_manual_command_tokens()
                      if self._rp_manual_command else self._rp_assemble_command())
        except ValueError as exc:
            messagebox.showwarning("Invalid command", str(exc))
            return
        if not tokens:
            messagebox.showwarning("No command",
                                   "Load a descriptor or type a command first.")
            return
        if not self._rp_manual_command:
            missing = [
                self._rp_field_meta[k].get("label", k)
                for k in self._rp_field_meta
                if self._rp_field_meta[k].get("required")
                and not self._rp_field_vars.get(k, tk.StringVar()).get()
            ]
            if missing:
                messagebox.showwarning("Required fields empty",
                    "Please fill in required fields:\n• " + "\n• ".join(missing))
                return

        summary     = ("A manually edited command was executed."
                       if self._rp_manual_command else self._rp_build_run_summary())
        cmd_display = " ".join(f'"{t}"' if " " in t else t for t in tokens)
        self._rp_append_output(summary + "\n\n", "summary")
        self._rp_append_output(f"Command: {cmd_display}\n", "cmd")
        self._rp_append_output("─" * 60 + "\n")

        _fh = None
        sf  = self._rp_descriptor.get("output", {}).get("stdout_file", "").strip()
        if sf:
            try:
                _fh = open(sf, "w", encoding="utf-8")
                self._rp_append_output(f"[stdout -> {sf}]\n", "cmd")
            except Exception as exc:
                self._rp_append_output(f"Cannot open stdout_file '{sf}': {exc}\n", "error")
                return

        kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                      bufsize=1, text=True)
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            self._rp_proc = subprocess.Popen(tokens, **kwargs)
        except FileNotFoundError:
            self._rp_append_output(f"Executable not found: {tokens[0]}\n", "error")
            return
        except Exception as exc:
            self._rp_append_output(f"Failed to start process: {exc}\n", "error")
            return

        self._rp_run_btn.config(state="disabled")
        self._rp_stop_btn.config(state="normal")
        threading.Thread(target=self._rp_stream, args=(_fh,), daemon=True).start()

    def _rp_stream(self, fh):
        proc = self._rp_proc
        try:
            for line in proc.stdout:
                if fh: fh.write(line)
                self._rp_output_q.put(("line", line))
        finally:
            proc.wait()
            if fh: fh.close()
            self._rp_output_q.put(("done", proc.returncode))

    def _rp_stop(self):
        if self._rp_proc and self._rp_proc.poll() is None:
            self._rp_stopping = True
            self._rp_proc.terminate()
            if sys.platform != "win32":
                threading.Timer(3.0, self._rp_sigkill_fallback,
                                args=(self._rp_proc,)).start()

    def _rp_sigkill_fallback(self, proc):
        if proc.poll() is None:
            proc.kill()
            self._rp_output_q.put(
                ("info", "[Process did not respond to SIGTERM — sent SIGKILL]\n"))

    def _rp_poll_output(self):
        try:
            while True:
                tag, val = self._rp_output_q.get_nowait()
                if   tag == "line": self._rp_append_output(val)
                elif tag == "info": self._rp_append_output(val, "cmd")
                elif tag == "done":
                    if self._rp_stopping:
                        self._rp_append_output("\n[Stopped by user]\n", "error")
                        self._rp_stopping = False
                    else:
                        self._rp_append_output(
                            f"\n[Process exited — code {val}]\n",
                            "ok" if val == 0 else "error")
                    self._rp_run_btn.config(state="normal")
                    self._rp_stop_btn.config(state="disabled")
                    self._rp_proc = None
                    self._rp_populate_results()
        except Exception:
            pass
        self._parent.after(100, self._rp_poll_output)

    def _rp_append_output(self, text: str, tag: str = ""):
        self._rp_out_txt.config(state="normal")
        self._rp_out_txt.insert(tk.END, text, tag if tag else ())
        self._rp_out_txt.see(tk.END)
        self._rp_out_txt.config(state="disabled")

    def _rp_cmd_clear(self):
        self._rp_out_txt.config(state="normal")
        self._rp_out_txt.delete("1.0", tk.END)
        self._rp_out_txt.config(state="disabled")

    # ── results pane ─────────────────────────────────────────────────────────

    def _rp_resolve_pattern(self, pattern: str) -> str:
        def replace(m):
            token = m.group(1)
            for candidate in (token, "-" + token, "--" + token):
                v = self._rp_field_vars.get(candidate)
                if v is not None:
                    val = v.get()
                    return str(val) if val not in (None, False) else ""
            return m.group(0)
        return re.sub(r'\{([^}]+)\}', replace, pattern)

    def _rp_populate_results(self):
        if not self._rp_descriptor:
            return
        files_spec = self._rp_descriptor.get("output", {}).get("files", [])
        self._rp_results_files = []
        self._rp_res_lb.delete(0, tk.END)
        self._rp_clear_result_pane()
        self._rp_current_result_idx = None
        self._rp_popout_btn.config(state="disabled")
        if not files_spec:
            ttk.Label(self._rp_res_render,
                      text="No output files configured in descriptor.",
                      foreground="#777").pack(expand=True)
            return
        icons = {"text": "[TXT]", "table": "[TBL]", "image": "[IMG]",
                 "tree": "[TRE]", "trace": "[TRC]"}
        for entry in files_spec:
            pattern = entry.get("pattern", "")
            if not pattern:
                continue
            path = self._rp_resolve_pattern(pattern)
            if not os.path.isfile(path):
                continue
            otype = entry.get("output_type", "text")
            desc  = entry.get("description") or os.path.basename(path)
            self._rp_results_files.append(
                {"path": path, "output_type": otype, "description": desc})
            self._rp_res_lb.insert(
                tk.END, f"{icons.get(otype, '[ ? ]')}  {desc}")
        if self._rp_results_files:
            self._rp_res_lb.selection_set(0)
            self._rp_show_result(0)
        else:
            ttk.Label(self._rp_res_render,
                      text="No output files found on disk.",
                      foreground="#777").pack(expand=True)

    def _rp_on_result_select(self, *_):
        sel = self._rp_res_lb.curselection()
        if sel and self._rp_results_files:
            self._rp_show_result(sel[0])

    # ── public: manual-sourced tooltips ──────────────────────────────────────

    def apply_manual_tooltips(self, manual_path: str = None):
        """Give the panel's static buttons help from tooltips_data.py's "Plugins
        tab" group, and exclude the per-descriptor field inputs (which vary by
        descriptor and aren't documented). Called once after the panel is built,
        before the global TooltipController scans the tree. `manual_path` is
        accepted for call-site compatibility but no longer used (the manual's
        Plugins table is generated FROM this same dict, not parsed back)."""
        try:
            from tooltips_data import GROUPS, _normalise, _tooltip_text_for
            self._manual_tooltip_map = {
                _normalise(e["label"]): _tooltip_text_for(e)
                for e in GROUPS.get("Plugins tab", []) if e.get("label")
            }
        except Exception:
            self._manual_tooltip_map = {}
        # The Run Plugin field area holds the per-descriptor inputs — exclude it.
        try:
            self._rp_fld_frame._carl_disable_tooltips = True
        except Exception:
            pass
        self._apply_manual_text(self._parent)

    def _apply_manual_text(self, root):
        """Set _carl_tooltip_text on any button whose label matches the Plugins
        table. Safe to call repeatedly (e.g. after a dynamic editor rebuilds)."""
        mapping = getattr(self, "_manual_tooltip_map", None)
        if not mapping:
            return
        from tooltips import normalise_label
        stack = [root]
        while stack:
            widget = stack.pop()
            for child in widget.winfo_children():
                if isinstance(child, (ttk.Button, tk.Button, ttk.Menubutton, tk.Menubutton)):
                    try:
                        key = normalise_label(str(child.cget("text")))
                    except tk.TclError:
                        key = ""
                    if key in mapping and not getattr(child, "_carl_tooltip_text", ""):
                        child._carl_tooltip_text = mapping[key]
                stack.append(child)

    # ── public: font preference refresh ──────────────────────────────────────

    def refresh_fonts(self):
        """Force-refresh the panel's mono-font widgets after a font-size change.

        The shared Font object updates size automatically, but on Windows tk.Text
        can lag until re-configured. Covers both the persistent widgets and the
        dynamically-created results Text widget."""
        for w in (getattr(self, "_rp_cmd_text", None),
                  getattr(self, "_rp_out_txt", None),
                  getattr(self, "_gd_json_txt", None),
                  getattr(self, "_gd_cmd_txt", None),
                  getattr(self, "_rp_res_lb", None),
                  self._rp_res_text_widget):
            if w is not None:
                try:
                    w.configure(font=self._mono_font)
                except Exception:
                    pass

    def _rp_browse_result(self, output_type: str):
        filetypes = {
            "text":  [("Text / log files", "*.txt *.log *.iqtree *.out *.csv *.tsv *.fasta *.fa"),
                      ("All files", "*.*")],
            "tree":  [("Tree files", "*.treefile *.nwk *.nex *.nexus *.tree *.phy"),
                      ("All files", "*.*")],
            "image": [("Image files", "*.png *.jpg *.jpeg *.svg *.tif *.tiff *.bmp"),
                      ("All files", "*.*")],
        }
        path = filedialog.askopenfilename(
            title=f"Select {output_type} file",
            filetypes=filetypes.get(output_type, [("All files", "*.*")]))
        if not path or not os.path.isfile(path):
            return
        icons = {"text": "[TXT]", "image": "[IMG]", "tree": "[TRE]"}
        desc  = os.path.basename(path)
        self._rp_results_files.append(
            {"path": path, "output_type": output_type, "description": desc})
        self._rp_res_lb.insert(
            tk.END, f"{icons.get(output_type, '[ ? ]')}  {desc}")
        idx = len(self._rp_results_files) - 1
        self._rp_res_lb.selection_clear(0, tk.END)
        self._rp_res_lb.selection_set(idx)
        self._rp_show_result(idx)

    def _rp_show_result(self, idx: int):
        if idx >= len(self._rp_results_files):
            return
        f = self._rp_results_files[idx]
        self._rp_clear_result_pane()
        self._rp_current_result_idx = idx
        self._rp_popout_btn.config(state="normal")
        otype = f["output_type"]
        if otype in ("text", "table", "trace"):
            self._rp_show_text_result(f["path"])
        elif otype == "tree":
            self._rp_show_tree_result(f["path"])
        elif otype == "image":
            self._rp_show_image_result(f["path"])
        else:
            self._rp_show_text_result(f["path"])

    def _rp_clear_result_pane(self):
        if self._rp_results_mpl_fig is not None:
            try:
                import matplotlib.pyplot as plt
                plt.close(self._rp_results_mpl_fig)
            except Exception:
                pass
            self._rp_results_mpl_fig = None
        self._rp_res_text_widget = None
        for w in self._rp_res_render.winfo_children():
            w.destroy()

    def _rp_show_text_result(self, path: str):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except Exception as exc:
            content = f"[Error reading file: {exc}]"
        inner = ttk.Frame(self._rp_res_render)
        inner.pack(fill=tk.BOTH, expand=True)
        txt  = tk.Text(inner, wrap=tk.NONE, font=self._mono_font,
                       state="normal", bg="#1e1e1e", fg="#d4d4d4")
        vsb  = ttk.Scrollbar(inner, orient="vertical",   command=txt.yview)
        hsb  = ttk.Scrollbar(inner, orient="horizontal", command=txt.xview)
        txt.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side=tk.RIGHT,  fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        txt.pack(fill=tk.BOTH, expand=True)
        txt.insert("1.0", content)
        txt.config(state="disabled")
        self._rp_res_text_widget = txt

    def _rp_show_tree_result(self, path: str):
        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
            from Bio import Phylo
        except ImportError as exc:
            ttk.Label(self._rp_res_render, text=f"Missing library: {exc}",
                      foreground="#c00").pack(expand=True)
            return
        ext = os.path.splitext(path)[1].lower()
        fmt = "nexus" if ext in (".nex", ".nexus") else "newick"
        try:
            tree = Phylo.read(path, fmt)
        except Exception:
            try:
                tree = Phylo.read(path, "newick" if fmt == "nexus" else "nexus")
            except Exception as exc:
                ttk.Label(self._rp_res_render,
                          text=f"Could not parse tree:\n{exc}",
                          foreground="#c00", wraplength=240, justify="center"
                          ).pack(expand=True)
                return
        n_tips = tree.count_terminals()
        fig_h  = max(3.5, n_tips * 0.22)
        fig    = Figure(figsize=(7, fig_h), dpi=100, tight_layout=True)
        ax     = fig.add_subplot(111)
        try:
            Phylo.draw(tree, axes=ax, do_show=False)
        except Exception as exc:
            ttk.Label(self._rp_res_render, text=f"Draw error:\n{exc}",
                      foreground="#c00", wraplength=240, justify="center"
                      ).pack(expand=True)
            return
        self._rp_results_mpl_fig = fig
        canvas = FigureCanvasTkAgg(fig, master=self._rp_res_render)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    def _rp_show_image_result(self, path: str):
        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
            from PIL import Image
            import numpy as np
        except ImportError as exc:
            ttk.Label(self._rp_res_render, text=f"Missing library: {exc}",
                      foreground="#c00").pack(expand=True)
            return
        try:
            img = Image.open(path)
            img.load()
        except Exception as exc:
            ttk.Label(self._rp_res_render,
                      text=f"Could not open image:\n{exc}",
                      foreground="#c00", wraplength=240, justify="center"
                      ).pack(expand=True)
            return
        fig = Figure(figsize=(7, 5), dpi=100, tight_layout=True)
        ax  = fig.add_subplot(111)
        ax.imshow(np.array(img))
        ax.axis("off")
        self._rp_results_mpl_fig = fig
        canvas = FigureCanvasTkAgg(fig, master=self._rp_res_render)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    # ── pop-out: open current result in a dedicated window ───────────────────

    def _rp_popout_result(self):
        idx = self._rp_current_result_idx
        if idx is None or idx >= len(self._rp_results_files):
            return
        f = self._rp_results_files[idx]
        otype, path = f["output_type"], f["path"]
        if otype == "tree":
            self._rp_popout_tree(path)
        elif otype == "image":
            self._rp_popout_image(path)
        else:
            self._rp_popout_text(path, f["description"])

    def _rp_popout_tree(self, path: str):
        try:
            from phylogeny_viewer import open_phylogeny_viewer
            open_phylogeny_viewer(self._parent.winfo_toplevel(), path)
        except Exception as exc:
            messagebox.showerror("Phylogeny Viewer", str(exc),
                                 parent=self._parent.winfo_toplevel())

    def _rp_popout_text(self, path: str, title: str):
        try:
            from text_editor import open_text_editor
            open_text_editor(self._parent.winfo_toplevel(), path,
                             mono_font=self._mono_font)
        except Exception as exc:
            messagebox.showerror("Text Editor", str(exc),
                                 parent=self._parent.winfo_toplevel())

    def _rp_popout_image(self, path: str):
        try:
            from image_viewer import open_image_viewer
            open_image_viewer(self._parent.winfo_toplevel(), path)
        except Exception as exc:
            messagebox.showerror("Image Viewer", str(exc),
                                 parent=self._parent.winfo_toplevel())

    # ══════════════════════════════════════════════════════════════════════════
    # GENERATE DESCRIPTOR TAB
    # ══════════════════════════════════════════════════════════════════════════

    def _build_generate_tab(self, parent: tk.Frame):
        # ── toolbar ──
        tb = ttk.Frame(parent, padding=(4, 3))
        tb.pack(fill=tk.X)
        ttk.Button(tb, text="New",      command=self._gd_cmd_new).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="Open…",    command=self._gd_cmd_open).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="Save",     command=self._gd_cmd_save).pack(side=tk.LEFT, padx=2)
        ttk.Button(tb, text="Save As…", command=self._gd_cmd_save_as).pack(side=tk.LEFT, padx=2)
        ttk.Separator(tb, orient="vertical").pack(side=tk.LEFT, padx=8, fill="y", pady=3)
        self._gd_status_lbl = ttk.Label(tb, text="New descriptor", foreground="#777")
        self._gd_status_lbl.pack(side=tk.LEFT, padx=4)

        # ── horizontal split: authoring (left) | preview (right) ──
        hpw = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        hpw.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        # ── left authoring pane ──
        auth = ttk.Frame(hpw)
        hpw.add(auth, weight=3)

        sec_frame = ttk.LabelFrame(auth, text="Sections")
        sec_frame.pack(fill=tk.X, padx=4, pady=(4, 0))
        self._gd_sec_lb = tk.Listbox(sec_frame, height=6, selectmode=tk.SINGLE,
                                     activestyle="dotbox", exportselection=False)
        self._gd_sec_lb.pack(fill=tk.X, padx=2, pady=2)
        self._gd_sec_lb.bind("<<ListboxSelect>>", self._gd_on_section_select)
        sec_btns = ttk.Frame(sec_frame)
        sec_btns.pack(fill=tk.X, padx=2, pady=(0, 4))
        ttk.Button(sec_btns, text="+ Add",  command=self._gd_add_section,     width=7).pack(side=tk.LEFT, padx=2)
        ttk.Button(sec_btns, text="Delete", command=self._gd_delete_section,  width=7).pack(side=tk.LEFT, padx=2)
        ttk.Button(sec_btns, text="▲",      command=self._gd_move_section_up,   width=3).pack(side=tk.LEFT, padx=1)
        ttk.Button(sec_btns, text="▼",      command=self._gd_move_section_down, width=3).pack(side=tk.LEFT, padx=1)

        # scrollable field panel
        self._gd_fld_outer = ttk.LabelFrame(auth, text="Fields")
        self._gd_fld_outer.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._gd_fld_canvas = tk.Canvas(self._gd_fld_outer,
                                        borderwidth=0, highlightthickness=0)
        _vsb = ttk.Scrollbar(self._gd_fld_outer, orient="vertical",
                              command=self._gd_fld_canvas.yview)
        self._gd_fld_canvas.configure(yscrollcommand=_vsb.set)
        _vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._gd_fld_canvas.pack(fill=tk.BOTH, expand=True)
        self._gd_fld_frame = ttk.Frame(self._gd_fld_canvas)
        _fw = self._gd_fld_canvas.create_window(
            (0, 0), window=self._gd_fld_frame, anchor="nw")
        self._gd_fld_frame.bind("<Configure>",
            lambda e, c=self._gd_fld_canvas: c.configure(scrollregion=c.bbox("all")))
        self._gd_fld_canvas.bind("<Configure>",
            lambda e, c=self._gd_fld_canvas, w=_fw: c.itemconfig(w, width=e.width))
        self._gd_fld_canvas.bind("<MouseWheel>",
            lambda e, c=self._gd_fld_canvas: c.yview_scroll(
                int(-1*(e.delta/120)), "units"))

        # ── right preview pane ──
        prev = ttk.Frame(hpw)
        hpw.add(prev, weight=2)

        vpw2 = ttk.PanedWindow(prev, orient=tk.VERTICAL)
        vpw2.pack(fill=tk.BOTH, expand=True)

        # top half — JSON Preview
        json_frm = ttk.Frame(vpw2)
        vpw2.add(json_frm, weight=1)
        ttk.Label(json_frm, text="JSON Preview",
                  font=("TkDefaultFont", 9, "bold")).pack(anchor="w", padx=6, pady=(6, 0))
        self._gd_json_txt = tk.Text(json_frm, wrap=tk.NONE, font=self._mono_font,
                                    state="disabled", bg="#1e1e1e", fg="#d4d4d4")
        _jvsb = ttk.Scrollbar(json_frm, orient="vertical",   command=self._gd_json_txt.yview)
        _jhsb = ttk.Scrollbar(json_frm, orient="horizontal", command=self._gd_json_txt.xview)
        self._gd_json_txt.configure(yscrollcommand=_jvsb.set, xscrollcommand=_jhsb.set)
        _jvsb.pack(side=tk.RIGHT,  fill=tk.Y)
        _jhsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._gd_json_txt.pack(fill=tk.BOTH, expand=True, padx=(6, 0))

        # bottom half — command line + parameters table
        cmd_frm = ttk.Frame(vpw2)
        vpw2.add(cmd_frm, weight=1)
        ttk.Label(cmd_frm, text="Command Line Syntax",
                  font=("TkDefaultFont", 9, "bold")).pack(anchor="w", padx=6, pady=(6, 0))
        self._gd_cmd_txt = tk.Text(cmd_frm, wrap=tk.WORD, font=self._mono_font,
                                   state="disabled", bg="#1e1e1e", fg="#9cdcfe", height=3)
        self._gd_cmd_txt.pack(fill=tk.X, padx=(6, 0), pady=(2, 4))

        ttk.Label(cmd_frm, text="Parameters",
                  font=("TkDefaultFont", 9, "bold")).pack(anchor="w", padx=6)
        tv_frm = ttk.Frame(cmd_frm)
        tv_frm.pack(fill=tk.BOTH, expand=True, padx=6, pady=(2, 6))
        _tv_cols = ("flag", "label", "type", "default")
        self._gd_params_tv = ttk.Treeview(
            tv_frm, columns=_tv_cols, show="headings",
            selectmode="none", height=8)
        self._gd_params_tv.heading("flag",    text="Flag")
        self._gd_params_tv.heading("label",   text="Label")
        self._gd_params_tv.heading("type",    text="Type")
        self._gd_params_tv.heading("default", text="Default")
        self._gd_params_tv.column("flag",    width=200, stretch=False, anchor="w")
        self._gd_params_tv.column("label",   width=50,  stretch=True,  anchor="w")
        self._gd_params_tv.column("type",    width=65,  stretch=False, anchor="w")
        self._gd_params_tv.column("default", width=65,  stretch=False, anchor="w")
        _hdr_font = self._ui_font_bold or ("TkDefaultFont", 9, "bold")
        self._gd_params_tv.tag_configure(
            "sec_hdr", background="#dde8f0", foreground="#333333",
            font=_hdr_font)
        _tvsb = ttk.Scrollbar(tv_frm, orient="vertical",
                              command=self._gd_params_tv.yview)
        self._gd_params_tv.configure(yscrollcommand=_tvsb.set)
        _tvsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._gd_params_tv.pack(fill=tk.BOTH, expand=True)

        self._gd_refresh_sections_list()
        self._gd_update_preview()

    # ── sections list (Generate Descriptor) ───────────────────────────────────

    def _gd_refresh_sections_list(self, keep_sel: bool = True, redraw: bool = True):
        sel = self._gd_sec_lb.curselection()
        prev_idx = sel[0] if sel and keep_sel else 0
        self._gd_sec_lb.delete(0, tk.END)
        self._gd_sec_lb.insert(tk.END, "★  Plugin Info")
        for sec in self._gd_descriptor.get("sections", []):
            name = sec.get("name") or sec.get("id") or "(unnamed)"
            self._gd_sec_lb.insert(tk.END, f"{name}  ({len(sec.get('fields',[]))})")
        self._gd_sec_lb.insert(tk.END, "⚙  Output")
        total = self._gd_sec_lb.size()
        self._gd_sec_lb.selection_set(min(prev_idx, total - 1))
        if redraw:
            self._gd_on_section_select()

    def _gd_on_section_select(self, *_):
        sel = self._gd_sec_lb.curselection()
        if not sel:
            return
        idx   = sel[0]
        secs  = self._gd_descriptor.get("sections", [])
        total = self._gd_sec_lb.size()
        if idx == 0:
            self._gd_show_plugin_info()
        elif idx == total - 1:
            self._gd_show_output_form()
        else:
            self._gd_show_section_fields(secs[idx - 1])

    # ── Plugin Info form ──────────────────────────────────────────────────────

    def _gd_show_plugin_info(self):
        self._gd_clear_field_panel()
        d = self._gd_descriptor
        FIELDS = [
            ("plugin_id",       "Plugin ID *",                    "string"),
            ("name",            "Name *",                         "string"),
            ("executable",      "Executable *",                   "file"),
            ("alt_executables", "Alt executables\n(one per line)", "multiline"),
            ("description",     "Description",                    "string"),
            ("homepage",        "Homepage URL",                   "string"),
            ("citation",        "Citation",                       "string"),
            ("license",         "License",                        "string"),
            ("min_version",     "Min version",                    "string"),
        ]
        self._gd_info_vars = {}
        for key, lbl, ftype in FIELDS:
            row = ttk.Frame(self._gd_fld_frame, padding=(0, 2))
            row.pack(fill=tk.X, padx=8)
            ttk.Label(row, text=lbl, width=LABEL_W, anchor="e").pack(
                side=tk.LEFT, padx=(0, 8))
            if ftype == "multiline":
                existing = d.get(key, [])
                txt = tk.Text(row, width=34, height=3, font=("TkDefaultFont", 9))
                txt.insert("1.0", "\n".join(existing)
                           if isinstance(existing, list) else str(existing))
                txt.pack(side=tk.LEFT)
                self._gd_info_vars[key] = txt
            elif ftype == "file":
                var = tk.StringVar(value=str(d.get(key, "") or ""))
                var.trace_add("write",
                    lambda *_, k=key, v=var: self._gd_info_field_changed(k, v))
                ttk.Entry(row, textvariable=var, width=30).pack(side=tk.LEFT)
                ttk.Button(row, text="Browse…", width=8,
                           command=lambda v=var: v.set(
                               filedialog.askopenfilename(
                                   title="Locate executable",
                                   filetypes=[("Executables", "*.exe *.bat *.sh *"),
                                              ("All files", "*.*")]) or v.get())
                           ).pack(side=tk.LEFT, padx=4)
                self._gd_info_vars[key] = var
            else:
                var = tk.StringVar(value=str(d.get(key, "") or ""))
                var.trace_add("write",
                    lambda *_, k=key, v=var: self._gd_info_field_changed(k, v))
                ttk.Entry(row, textvariable=var, width=36).pack(side=tk.LEFT)
                self._gd_info_vars[key] = var

        ttk.Button(self._gd_fld_frame, text="Apply",
                   command=self._gd_apply_plugin_info).pack(anchor="w", padx=8, pady=6)

    def _gd_info_field_changed(self, key: str, var: tk.StringVar):
        self._gd_descriptor[key] = var.get()
        self._gd_mark_dirty()
        self._gd_update_preview()

    def _gd_apply_plugin_info(self):
        for key, widget in self._gd_info_vars.items():
            if isinstance(widget, tk.Text):
                raw = widget.get("1.0", "end-1c").strip()
                self._gd_descriptor[key] = [
                    l.strip() for l in raw.splitlines() if l.strip()]
            else:
                val = widget.get()
                if key == "executable":
                    val = val.strip().strip('"').strip("'")
                self._gd_descriptor[key] = val
        self._gd_mark_dirty()
        self._gd_refresh_sections_list()
        self._gd_update_preview()

    # ── Output form ───────────────────────────────────────────────────────────

    def _gd_show_output_form(self):
        self._gd_clear_field_panel()
        out = self._gd_descriptor.get("output", {})
        self._gd_out_vars = {}

        # display_mode + stdout_file rows
        for key, lbl, values in [
            ("display_mode", "Display mode", DISPLAY_MODES),
            ("stdout_file",  "Stdout file",  None),
        ]:
            row = ttk.Frame(self._gd_fld_frame, padding=(0, 2))
            row.pack(fill=tk.X, padx=8)
            ttk.Label(row, text=lbl, width=LABEL_W, anchor="e").pack(
                side=tk.LEFT, padx=(0, 8))
            var = tk.StringVar(value=str(out.get(key, "") or ""))
            if values:
                cb = ttk.Combobox(row, textvariable=var, values=values,
                                  state="readonly", width=14)
                if not var.get():
                    var.set(values[0])
                cb.pack(side=tk.LEFT)
            else:
                ttk.Entry(row, textvariable=var, width=36).pack(side=tk.LEFT)
            var.trace_add("write",
                lambda *_, k=key, v=var: self._gd_out_field_changed(k, v))
            self._gd_out_vars[key] = var

        ttk.Separator(self._gd_fld_frame, orient="horizontal").pack(
            fill=tk.X, padx=8, pady=6)

        # files table
        files_frm = ttk.LabelFrame(self._gd_fld_frame, text="Output Files")
        files_frm.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        self._gd_out_files_lb = tk.Listbox(files_frm, height=5,
                                           selectmode=tk.SINGLE,
                                           exportselection=False,
                                           font=self._mono_font)
        self._gd_out_files_lb.pack(fill=tk.X, padx=4, pady=(4, 0))
        self._gd_out_files_lb.bind("<<ListboxSelect>>", self._gd_out_on_file_select)

        fl_btns = ttk.Frame(files_frm)
        fl_btns.pack(fill=tk.X, padx=4, pady=2)
        ttk.Button(fl_btns, text="+ Add",  command=self._gd_out_add_file,      width=7).pack(side=tk.LEFT, padx=2)
        ttk.Button(fl_btns, text="Delete", command=self._gd_out_delete_file,   width=7).pack(side=tk.LEFT, padx=2)
        ttk.Button(fl_btns, text="▲",      command=self._gd_out_move_file_up,  width=3).pack(side=tk.LEFT, padx=1)
        ttk.Button(fl_btns, text="▼",      command=self._gd_out_move_file_down,width=3).pack(side=tk.LEFT, padx=1)

        self._gd_out_file_editor = ttk.LabelFrame(files_frm, text="File Entry")
        self._gd_out_file_editor.pack(fill=tk.X, padx=4, pady=(0, 4))
        ttk.Label(self._gd_out_file_editor,
                  text="Select a file entry above to edit.",
                  foreground="#888").pack(padx=8, pady=6)

        self._gd_out_refresh_files_lb()

    def _gd_out_field_changed(self, key: str, var: tk.StringVar):
        self._gd_descriptor.setdefault("output", {})[key] = var.get()
        self._gd_mark_dirty()
        self._gd_update_preview()

    def _gd_out_refresh_files_lb(self):
        self._gd_out_files_lb.delete(0, tk.END)
        icons = {"text": "[TXT]", "table": "[TBL]", "image": "[IMG]",
                 "tree": "[TRE]", "trace": "[TRC]"}
        for fe in self._gd_descriptor.get("output", {}).get("files", []):
            ot   = fe.get("output_type", "")
            icon = icons.get(ot, "[ ? ]")
            self._gd_out_files_lb.insert(
                tk.END, f"{icon}  {fe.get('pattern', '(no pattern)')}")

    def _gd_out_on_file_select(self, *_):
        sel = self._gd_out_files_lb.curselection()
        if not sel:
            return
        files = self._gd_descriptor.get("output", {}).get("files", [])
        if sel[0] < len(files):
            self._gd_out_show_file_editor(files[sel[0]], sel[0])

    def _gd_out_show_file_editor(self, fe: dict, idx: int):
        for w in self._gd_out_file_editor.winfo_children():
            w.destroy()
        self._gd_out_file_idx = idx

        # build available tokens hint from current fields
        tokens = []
        for sec in self._gd_descriptor.get("sections", []):
            for f in sec.get("fields", []):
                flag = f.get("flag", "")
                if flag:
                    tokens.append(flag.lstrip("-"))
        hint_text = "  Tokens: " + "  ".join(f"{{{t}}}" for t in tokens) if tokens else ""

        self._gd_out_fe_vars = {}
        for key, lbl, widget_type in [
            ("pattern",     "Pattern",     "entry"),
            ("output_type", "Output type", "otype_choice"),
            ("description", "Description", "entry"),
        ]:
            row = ttk.Frame(self._gd_out_file_editor, padding=(0, 2))
            row.pack(fill=tk.X, padx=6)
            ttk.Label(row, text=lbl, width=LABEL_W, anchor="e").pack(
                side=tk.LEFT, padx=(0, 6))
            var = tk.StringVar(value=str(fe.get(key, "") or ""))
            if widget_type == "otype_choice":
                otypes = sorted(_pm.VALID_OUTPUT_TYPES)
                cb = ttk.Combobox(row, textvariable=var, values=otypes,
                                  state="readonly", width=14)
                if not var.get() or var.get() not in otypes:
                    var.set("text")
                cb.pack(side=tk.LEFT)
            else:
                ttk.Entry(row, textvariable=var, width=34).pack(side=tk.LEFT)
                if key == "pattern" and hint_text:
                    ttk.Label(row, text=hint_text,
                              foreground="#777", font=("TkDefaultFont", 8)
                              ).pack(side=tk.LEFT, padx=4)
            self._gd_out_fe_vars[key] = var

        apply_btn = ttk.Button(self._gd_out_file_editor, text="Apply",
                               command=self._gd_out_apply_file)
        apply_btn.pack(anchor="w", padx=6, pady=4)
        self._gd_out_fe_apply_btn = apply_btn

    def _gd_out_apply_file(self):
        files = self._gd_descriptor.setdefault("output", {}).setdefault("files", [])
        idx   = getattr(self, "_gd_out_file_idx", None)
        if idx is None or idx >= len(files):
            return
        for key, var in self._gd_out_fe_vars.items():
            files[idx][key] = var.get()
        self._gd_mark_dirty()
        self._gd_out_refresh_files_lb()
        self._gd_update_preview()
        self._gd_out_fe_apply_btn.config(text="Applied ✓", foreground="green")
        self._gd_out_file_editor.after(
            2000, lambda: self._gd_out_fe_apply_btn.config(text="Apply", foreground=""))

    def _gd_out_add_file(self):
        files = self._gd_descriptor.setdefault("output", {}).setdefault("files", [])
        files.append({"pattern": "", "output_type": "text", "description": ""})
        self._gd_mark_dirty()
        self._gd_out_refresh_files_lb()
        idx = len(files) - 1
        self._gd_out_files_lb.selection_clear(0, tk.END)
        self._gd_out_files_lb.selection_set(idx)
        self._gd_out_on_file_select()
        self._gd_update_preview()

    def _gd_out_delete_file(self):
        sel = self._gd_out_files_lb.curselection()
        if not sel:
            return
        files = self._gd_descriptor.get("output", {}).get("files", [])
        if not files or sel[0] >= len(files):
            return
        pattern = files[sel[0]].get("pattern", "(empty)")
        if not messagebox.askyesno("Delete file entry",
                                   f"Delete entry '{pattern}'?"):
            return
        files.pop(sel[0])
        self._gd_mark_dirty()
        self._gd_out_refresh_files_lb()
        for w in self._gd_out_file_editor.winfo_children():
            w.destroy()
        ttk.Label(self._gd_out_file_editor,
                  text="Select a file entry above to edit.",
                  foreground="#888").pack(padx=8, pady=6)
        self._gd_update_preview()

    def _gd_out_move_file_up(self):
        sel = self._gd_out_files_lb.curselection()
        if not sel or sel[0] == 0:
            return
        files = self._gd_descriptor.get("output", {}).get("files", [])
        idx = sel[0]
        files[idx - 1], files[idx] = files[idx], files[idx - 1]
        self._gd_mark_dirty()
        self._gd_out_refresh_files_lb()
        self._gd_out_files_lb.selection_set(idx - 1)
        self._gd_update_preview()

    def _gd_out_move_file_down(self):
        sel = self._gd_out_files_lb.curselection()
        if not sel:
            return
        files = self._gd_descriptor.get("output", {}).get("files", [])
        idx = sel[0]
        if idx >= len(files) - 1:
            return
        files[idx], files[idx + 1] = files[idx + 1], files[idx]
        self._gd_mark_dirty()
        self._gd_out_refresh_files_lb()
        self._gd_out_files_lb.selection_set(idx + 1)
        self._gd_update_preview()

    # ── Section fields editor ─────────────────────────────────────────────────

    def _gd_show_section_fields(self, sec: dict):
        self._gd_clear_field_panel()
        self._gd_current_sec = sec

        # section rename row
        hdr = ttk.Frame(self._gd_fld_frame, padding=(0, 2))
        hdr.pack(fill=tk.X, padx=8)
        ttk.Label(hdr, text="Section name", width=LABEL_W, anchor="e").pack(
            side=tk.LEFT, padx=(0, 8))
        self._gd_sec_name_var = tk.StringVar(
            value=sec.get("name") or sec.get("id") or "")
        ttk.Entry(hdr, textvariable=self._gd_sec_name_var, width=26).pack(side=tk.LEFT)
        ttk.Button(hdr, text="Rename",
                   command=self._gd_rename_section).pack(side=tk.LEFT, padx=4)

        ttk.Separator(self._gd_fld_frame, orient="horizontal").pack(
            fill=tk.X, padx=8, pady=4)

        # fields list + controls
        fl_frame = ttk.LabelFrame(self._gd_fld_frame, text="Fields")
        fl_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=2)
        fl_btns = ttk.Frame(fl_frame)
        fl_btns.pack(fill=tk.X, padx=2, pady=2)
        ttk.Button(fl_btns, text="+ Add",     command=self._gd_add_field,       width=7).pack(side=tk.LEFT, padx=2)
        ttk.Button(fl_btns, text="Delete",    command=self._gd_delete_field,    width=7).pack(side=tk.LEFT, padx=2)
        ttk.Button(fl_btns, text="Duplicate", command=self._gd_duplicate_field, width=9).pack(side=tk.LEFT, padx=2)
        ttk.Button(fl_btns, text="▲", command=self._gd_move_field_up,   width=3).pack(side=tk.LEFT, padx=1)
        ttk.Button(fl_btns, text="▼", command=self._gd_move_field_down, width=3).pack(side=tk.LEFT, padx=1)

        self._gd_fields_lb = tk.Listbox(fl_frame, height=7, selectmode=tk.SINGLE,
                                        exportselection=False)
        self._gd_fields_lb.pack(fill=tk.X, padx=2, pady=2)
        self._gd_fields_lb.bind("<<ListboxSelect>>", self._gd_on_field_select)
        self._gd_refresh_fields_list()

        # field editor placeholder (populated on field select)
        self._gd_field_editor_frame = ttk.LabelFrame(
            self._gd_fld_frame, text="Field Editor")
        self._gd_field_editor_frame.pack(
            fill=tk.BOTH, expand=True, padx=8, pady=4)
        ttk.Label(self._gd_field_editor_frame,
                  text="Select a field above to edit.",
                  foreground="#888").pack(padx=12, pady=12)
        self._apply_manual_text(self._gd_fld_frame)

    def _gd_refresh_fields_list(self):
        sec = self._gd_current_sec
        if sec is None:
            return
        self._gd_fields_lb.delete(0, tk.END)
        for f in sec.get("fields", []):
            flag  = f.get("flag", "")
            label = f.get("label", "")
            entry = (f"{flag or '(pos)'} — {label}"
                     if (flag or label) else "(unnamed)")
            self._gd_fields_lb.insert(tk.END, entry)

    def _gd_on_field_select(self, *_):
        sel = self._gd_fields_lb.curselection()
        if not sel or self._gd_current_sec is None:
            return
        idx    = sel[0]
        fields = self._gd_current_sec.get("fields", [])
        if idx < len(fields):
            self._gd_show_field_editor(fields[idx], idx)

    def _gd_show_field_editor(self, f: dict, idx: int):
        for w in self._gd_field_editor_frame.winfo_children():
            w.destroy()
        self._gd_field_editor_idx = idx

        ATTRS = [
            ("flag",             "Flag",               "string"),
            ("label",            "Label",              "string"),
            ("type",             "Type",               "type_choice"),
            ("required",         "Required",           "boolean"),
            ("common",           "Common",             "boolean"),
            ("default",          "Default",            "string"),
            ("value_hint",       "Value hint",         "string"),
            ("help",             "Help text",          "multiline"),
            ("options",          "Options (one/line)", "multiline"),
            ("mutex_group",      "Mutex group",        "string"),
            ("separator",        "Separator",          "sep_choice"),
            ("positional_order", "Positional order",   "integer"),
            ("multi_separator",  "Multi separator",    "msep_choice"),
        ]
        self._gd_fe_vars = {}
        for key, lbl, ftype in ATTRS:
            row = ttk.Frame(self._gd_field_editor_frame, padding=(0, 1))
            row.pack(fill=tk.X, padx=6)
            ttk.Label(row, text=lbl, width=LABEL_W, anchor="e").pack(
                side=tk.LEFT, padx=(0, 6))
            if ftype == "boolean":
                var = tk.BooleanVar(value=bool(f.get(key, False)))
                ttk.Checkbutton(row, variable=var).pack(side=tk.LEFT)
            elif ftype == "type_choice":
                var = tk.StringVar(value=f.get(key, FIELD_TYPES[0]))
                ttk.Combobox(row, textvariable=var, values=FIELD_TYPES,
                             state="readonly", width=14).pack(side=tk.LEFT)
            elif ftype == "sep_choice":
                var = tk.StringVar(value=f.get(key, " "))
                ttk.Combobox(row, textvariable=var, values=SEPARATORS,
                             state="readonly", width=6).pack(side=tk.LEFT)
            elif ftype == "msep_choice":
                var = tk.StringVar(value=f.get(key, ""))
                ttk.Combobox(row, textvariable=var, values=MULTI_SEPS,
                             state="readonly", width=6).pack(side=tk.LEFT)
            elif ftype == "integer":
                var = tk.StringVar(value=str(f.get(key, 0)))
                ttk.Spinbox(row, textvariable=var, from_=0, to=99,
                            width=6).pack(side=tk.LEFT)
            elif ftype == "multiline":
                existing = f.get(key, "")
                if isinstance(existing, list):
                    existing = "\n".join(existing)
                var = tk.Text(row, width=30, height=3,
                              font=("TkDefaultFont", 9))
                var.insert("1.0", existing)
                var.pack(side=tk.LEFT)
            else:
                var = tk.StringVar(value=str(f.get(key, "") or ""))
                ttk.Entry(row, textvariable=var, width=30).pack(side=tk.LEFT)
            self._gd_fe_vars[key] = var

        self._gd_fe_apply_btn = ttk.Button(
            self._gd_field_editor_frame, text="Apply",
            command=self._gd_apply_field_editor)
        self._gd_fe_apply_btn.pack(anchor="w", padx=6, pady=6)
        self._apply_manual_text(self._gd_field_editor_frame)

    def _gd_apply_field_editor(self):
        if self._gd_current_sec is None:
            return
        idx    = getattr(self, "_gd_field_editor_idx", None)
        fields = self._gd_current_sec.setdefault("fields", [])
        if idx is None or idx >= len(fields):
            return
        f = fields[idx]
        for key, widget in self._gd_fe_vars.items():
            if isinstance(widget, tk.Text):
                raw = widget.get("1.0", "end-1c").strip()
                f[key] = ([l.strip() for l in raw.splitlines() if l.strip()]
                          if key == "options" else raw)
            elif isinstance(widget, (tk.BooleanVar, tk.StringVar)):
                f[key] = widget.get()
            else:
                f[key] = widget.get()
        self._gd_mark_dirty()
        self._gd_refresh_fields_list()
        self._gd_refresh_sections_list(redraw=False)
        self._gd_update_preview()
        self._gd_fe_apply_btn.config(text="Applied ✓", foreground="green")
        self._gd_field_editor_frame.after(
            2000, lambda: self._gd_fe_apply_btn.config(text="Apply", foreground=""))

    # ── section CRUD ──────────────────────────────────────────────────────────

    def _gd_add_section(self):
        name = simpledialog.askstring("Add Section", "Section name:")
        if not name:
            return
        self._gd_descriptor.setdefault("sections", []).append(
            {"id": name.lower().replace(" ", "_"), "name": name, "fields": []})
        self._gd_mark_dirty()
        self._gd_refresh_sections_list(keep_sel=False)
        new_idx = self._gd_sec_lb.size() - 2
        self._gd_sec_lb.selection_clear(0, tk.END)
        self._gd_sec_lb.selection_set(new_idx)
        self._gd_on_section_select()
        self._gd_update_preview()

    def _gd_delete_section(self):
        sel = self._gd_sec_lb.curselection()
        if not sel:
            return
        idx   = sel[0]
        secs  = self._gd_descriptor.get("sections", [])
        total = self._gd_sec_lb.size()
        if idx == 0 or idx == total - 1:
            messagebox.showinfo("Cannot delete",
                "Plugin Info and Output cannot be deleted.")
            return
        sec_idx = idx - 1
        name    = secs[sec_idx].get("name", "")
        if not messagebox.askyesno("Delete section",
                f"Delete '{name}' and all its fields?"):
            return
        secs.pop(sec_idx)
        self._gd_mark_dirty()
        self._gd_refresh_sections_list()
        self._gd_update_preview()

    def _gd_rename_section(self):
        if self._gd_current_sec is None:
            return
        name = self._gd_sec_name_var.get().strip()
        if name:
            self._gd_current_sec["name"] = name
            self._gd_current_sec["id"]   = name.lower().replace(" ", "_")
        self._gd_mark_dirty()
        self._gd_refresh_sections_list()
        self._gd_update_preview()

    def _gd_move_section_up(self):
        sel = self._gd_sec_lb.curselection()
        if not sel:
            return
        idx     = sel[0]
        secs    = self._gd_descriptor.get("sections", [])
        sec_idx = idx - 1
        if sec_idx <= 0:
            return
        secs[sec_idx - 1], secs[sec_idx] = secs[sec_idx], secs[sec_idx - 1]
        self._gd_mark_dirty()
        self._gd_refresh_sections_list(keep_sel=False)
        self._gd_sec_lb.selection_set(idx - 1)
        self._gd_on_section_select()
        self._gd_update_preview()

    def _gd_move_section_down(self):
        sel = self._gd_sec_lb.curselection()
        if not sel:
            return
        idx     = sel[0]
        secs    = self._gd_descriptor.get("sections", [])
        sec_idx = idx - 1
        if sec_idx < 0 or sec_idx >= len(secs) - 1:
            return
        secs[sec_idx], secs[sec_idx + 1] = secs[sec_idx + 1], secs[sec_idx]
        self._gd_mark_dirty()
        self._gd_refresh_sections_list(keep_sel=False)
        self._gd_sec_lb.selection_set(idx + 1)
        self._gd_on_section_select()
        self._gd_update_preview()

    # ── field CRUD ────────────────────────────────────────────────────────────

    def _gd_add_field(self):
        if self._gd_current_sec is None:
            return
        self._gd_current_sec.setdefault("fields", []).append(
            {"flag": "", "label": "New field", "type": "string"})
        self._gd_mark_dirty()
        self._gd_refresh_fields_list()
        idx = len(self._gd_current_sec["fields"]) - 1
        self._gd_fields_lb.selection_clear(0, tk.END)
        self._gd_fields_lb.selection_set(idx)
        self._gd_on_field_select()
        self._gd_refresh_sections_list(redraw=False)
        self._gd_update_preview()

    def _gd_delete_field(self):
        sel = self._gd_fields_lb.curselection()
        if not sel or self._gd_current_sec is None:
            return
        idx    = sel[0]
        fields = self._gd_current_sec.get("fields", [])
        if idx >= len(fields):
            return
        lbl = fields[idx].get("label") or fields[idx].get("flag") or "this field"
        if not messagebox.askyesno("Delete field", f"Delete '{lbl}'?"):
            return
        fields.pop(idx)
        self._gd_mark_dirty()
        self._gd_refresh_fields_list()
        for w in self._gd_field_editor_frame.winfo_children():
            w.destroy()
        ttk.Label(self._gd_field_editor_frame,
                  text="Select a field above to edit.",
                  foreground="#888").pack(padx=12, pady=12)
        self._gd_refresh_sections_list(redraw=False)
        self._gd_update_preview()

    def _gd_duplicate_field(self):
        sel = self._gd_fields_lb.curselection()
        if not sel or self._gd_current_sec is None:
            return
        idx    = sel[0]
        fields = self._gd_current_sec.setdefault("fields", [])
        if idx >= len(fields):
            return
        fields.insert(idx + 1, copy.deepcopy(fields[idx]))
        self._gd_mark_dirty()
        self._gd_refresh_fields_list()
        self._gd_fields_lb.selection_clear(0, tk.END)
        self._gd_fields_lb.selection_set(idx + 1)
        self._gd_on_field_select()
        self._gd_refresh_sections_list(redraw=False)
        self._gd_update_preview()

    def _gd_move_field_up(self):
        sel = self._gd_fields_lb.curselection()
        if not sel or self._gd_current_sec is None:
            return
        idx    = sel[0]
        fields = self._gd_current_sec.get("fields", [])
        if idx == 0:
            return
        fields[idx - 1], fields[idx] = fields[idx], fields[idx - 1]
        self._gd_mark_dirty()
        self._gd_refresh_fields_list()
        self._gd_fields_lb.selection_set(idx - 1)
        self._gd_update_preview()

    def _gd_move_field_down(self):
        sel = self._gd_fields_lb.curselection()
        if not sel or self._gd_current_sec is None:
            return
        idx    = sel[0]
        fields = self._gd_current_sec.get("fields", [])
        if idx >= len(fields) - 1:
            return
        fields[idx], fields[idx + 1] = fields[idx + 1], fields[idx]
        self._gd_mark_dirty()
        self._gd_refresh_fields_list()
        self._gd_fields_lb.selection_set(idx + 1)
        self._gd_update_preview()

    # ── file operations ───────────────────────────────────────────────────────

    def _gd_cmd_new(self):
        if self._gd_dirty and not messagebox.askyesno(
                "Unsaved changes",
                "Discard unsaved changes and start a new descriptor?"):
            return
        self._gd_descriptor = _empty_descriptor()
        self._gd_filepath   = None
        self._gd_dirty      = False
        self._gd_status_lbl.config(text="New descriptor", foreground="#777")
        self._gd_refresh_sections_list(keep_sel=False)
        self._gd_update_preview()

    def _gd_cmd_open(self):
        p = filedialog.askopenfilename(
            title="Open descriptor",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not p:
            return
        try:
            d      = _pm.load(p)
            errors = _pm.validate(d)
            if errors and not messagebox.askyesno(
                    "Validation warnings",
                    "Descriptor has issues:\n• " + "\n• ".join(errors) +
                    "\n\nOpen anyway?"):
                return
            self._gd_descriptor = d
            self._gd_filepath   = p
            self._gd_dirty      = False
            self._gd_status_lbl.config(
                text=os.path.basename(p), foreground="#000")
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))
            return
        self._gd_refresh_sections_list(keep_sel=False)
        self._gd_update_preview()

    def _gd_cmd_save(self):
        if not self._gd_filepath:
            self._gd_cmd_save_as()
        else:
            self._gd_do_save(self._gd_filepath)

    def _gd_cmd_save_as(self):
        pid = self._gd_descriptor.get("plugin_id") or "descriptor"
        p   = filedialog.asksaveasfilename(
            title="Save descriptor",
            initialfile=f"{pid}.json",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not p:
            return
        self._gd_do_save(p)
        self._gd_filepath = p

    def _gd_do_save(self, path: str):
        try:
            _pm.save(self._gd_descriptor, path)
            self._gd_dirty = False
            self._gd_status_lbl.config(
                text=os.path.basename(path), foreground="#000")
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc))

    # ── live preview ──────────────────────────────────────────────────────────

    def _gd_update_preview(self):
        # JSON
        try:
            text = json.dumps(
                _pm._clean_descriptor(self._gd_descriptor),
                indent=2, ensure_ascii=False)
        except Exception:
            text = "(error serialising descriptor)"
        self._gd_json_txt.config(state="normal")
        self._gd_json_txt.delete("1.0", tk.END)
        self._gd_json_txt.insert("1.0", text)
        self._gd_json_txt.config(state="disabled")

        # command syntax (illustrative, using value_hint / default as placeholders)
        exe   = self._gd_descriptor.get("executable") or "<executable>"
        parts = [exe]
        for sec in self._gd_descriptor.get("sections", []):
            for f in sec.get("fields", []):
                flag  = f.get("flag", "")
                ftype = f.get("type", "string")
                hint  = (f.get("value_hint") or f.get("default") or
                         f"<{f.get('label', 'value')}>")
                sep   = f.get("separator", " ")
                if ftype == "boolean":
                    parts.append(f"[{flag}]")
                elif not flag:
                    parts.append(f"<{f.get('label', 'arg')}>")
                elif sep == " ":
                    parts.append(f"{flag} {hint}")
                else:
                    parts.append(f"{flag}{sep}{hint}")
        self._gd_cmd_txt.config(state="normal")
        self._gd_cmd_txt.delete("1.0", tk.END)
        self._gd_cmd_txt.insert("1.0", " ".join(parts))
        self._gd_cmd_txt.config(state="disabled")

        # parameters table
        tv = self._gd_params_tv
        tv.delete(*tv.get_children())
        for sec in self._gd_descriptor.get("sections", []):
            sec_name = sec.get("name") or sec.get("id") or "(unnamed)"
            fields   = sec.get("fields", [])
            if not fields:
                continue
            tv.insert("", tk.END, values=(sec_name, "", "", ""), tags=("sec_hdr",))
            for f in fields:
                flag    = f.get("flag", "")
                label   = f.get("label", "")
                ftype   = f.get("type", "string")
                default = str(f.get("default", "") or "")
                flag_cell = flag if flag else f"<{label or 'arg'}>"
                tv.insert("", tk.END, values=(flag_cell, label, ftype, default))

    # ── dirty state ───────────────────────────────────────────────────────────

    def _gd_mark_dirty(self):
        self._gd_dirty = True
        fname = (os.path.basename(self._gd_filepath)
                 if self._gd_filepath else "New descriptor")
        self._gd_status_lbl.config(
            text=f"{fname} (unsaved)", foreground="darkorange")

    def _gd_clear_field_panel(self):
        for w in self._gd_fld_frame.winfo_children():
            w.destroy()
        self._gd_fld_canvas.configure(scrollregion=(0, 0, 0, 0))



# ── module-level helpers ───────────────────────────────────────────────────────

def _empty_descriptor() -> dict:
    return {
        "schema_version": "1.0",
        "plugin_id": "", "name": "", "executable": "",
        "alt_executables": [],
        "description": "", "homepage": "", "citation": "",
        "license": "", "min_version": "",
        "sections": [],
        "output": {"display_mode": "terminal", "stdout_file": "", "files": []},
    }
