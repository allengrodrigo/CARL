"""
editor_operations.py — EditorMixin for CARL.

Mixed into TaxonGPT_UI via multiple inheritance. All methods here
assume self.* attributes defined in TaxonGPT_UI.__init__.
"""

import re
import tkinter as tk
from tkinter import ttk, messagebox

from data_model import Taxon, Dataset, Character
from carl_parser import CARLBlock


class EditorMixin:
    """Editor tab methods — mixed into TaxonGPT_UI."""

    # -------------------------
    # EDITOR TAB METHODS
    # -------------------------

    def _populate_editor_tab(self):
        """Fill the Editor treeview from dataset, grouping synonymize/includes taxa."""
        tree = self._editor_taxa_list
        for item in tree.get_children():
            tree.delete(item)

        # Clear right pane
        for w in self._editor_inner.winfo_children():
            w.destroy()
        self._editor_name_labels.clear()
        self._editor_state_labels.clear()
        self._editor_pending_label.config(text="")

        if not self.dataset:
            return

        all_data_ids = {t.name for t in self.dataset.taxa}

        if self.carl_block is not None:
            # Which dataIDs are pointed to by any [&D ...] pointer?
            assigned = set()
            for row in self.carl_block.get_data_tab_rows():
                if row.get("data_id"):
                    assigned.add(row["data_id"])

            # Track which data_ids have been placed under a group
            placed: set = set()

            for e in self.carl_block.entities:

                if e.action == "synonymizes":
                    # Group header (iid = group name string; not a matrix taxon)
                    hdr_iid = f"__grp__{e.name}_syn"
                    tree.insert("", "end", iid=hdr_iid,
                                text=f"{e.name}_syn",
                                tags=("group_header",), open=True)
                    rels = [r for r in self.carl_block.relationships
                            if r.subject_id == e.entity_id and r.rel_type == "synonymizes"]
                    for r in rels:
                        did = r.object_data_id
                        if did and did in all_data_ids:
                            tag = "unassigned" if did not in assigned else ""
                            tree.insert(hdr_iid, "end", iid=did, text=did,
                                        tags=(tag,) if tag else ())
                            placed.add(did)
                        else:
                            # CARL-only member — show greyed, no iid clash
                            tree.insert(hdr_iid, "end",
                                        iid=f"__carl__{r.object_name}",
                                        text=r.object_name,
                                        tags=("carl_only",))

                elif e.action == "includes":
                    hdr_iid = f"__grp__{e.name}"
                    tree.insert("", "end", iid=hdr_iid,
                                text=e.name,
                                tags=("group_header",), open=True)
                    rels = [r for r in self.carl_block.relationships
                            if r.subject_id == e.entity_id and r.rel_type == "includes"]
                    for r in rels:
                        # For includes, member data_id comes from the member's own entity
                        member_ent = next(
                            (me for me in self.carl_block.entities if me.name == r.object_name),
                            None
                        )
                        did = member_ent.data_id if member_ent else r.object_data_id
                        if did and did in all_data_ids:
                            tag = "unassigned" if did not in assigned else ""
                            # May already be placed under another group; skip duplicate
                            if did not in placed:
                                tree.insert(hdr_iid, "end", iid=did, text=did,
                                            tags=(tag,) if tag else ())
                                placed.add(did)
                        else:
                            if f"__carl__{r.object_name}" not in tree.get_children(hdr_iid):
                                tree.insert(hdr_iid, "end",
                                            iid=f"__carl__{r.object_name}",
                                            text=r.object_name,
                                            tags=("carl_only",))

            # Ungrouped matrix taxa — root level
            for taxon in self.dataset.taxa:
                if taxon.name not in placed:
                    tag = "unassigned" if taxon.name not in assigned else ""
                    tree.insert("", "end", iid=taxon.name, text=taxon.name,
                                tags=(tag,) if tag else ())
        else:
            # Build mode — flat list
            for taxon in self.dataset.taxa:
                tree.insert("", "end", iid=taxon.name, text=taxon.name)

        # Auto-select first selectable (non-group-header) item
        self._editor_select_first()

    def _editor_select_first(self):
        """Select and display the first matrix taxon in the treeview."""
        tree = self._editor_taxa_list
        def _find_first(parent=""):
            for iid in tree.get_children(parent):
                if not iid.startswith("__"):
                    return iid
                found = _find_first(iid)
                if found:
                    return found
            return None
        first = _find_first()
        if first:
            tree.selection_set(first)
            tree.see(first)
            self._editor_select_taxon()

    def _editor_select_taxon(self, event=None):
        """Called on treeview selection; fills the right pane for the selected matrix taxon."""
        sel = self._editor_taxa_list.selection()
        if not sel or not self.dataset:
            return
        iid = sel[0]
        # Group headers and CARL-only placeholders are not editable
        if iid.startswith("__"):
            return
        taxon = next((t for t in self.dataset.taxa if t.name == iid), None)
        if taxon:
            self._fill_editor_states_table(taxon)

    def _fill_editor_states_table(self, taxon):
        """Like _fill_states_table but character names and coded state values are clickable."""
        inner  = self._editor_inner
        canvas = self._editor_canvas

        for w in inner.winfo_children():
            w.destroy()
        self._editor_name_labels.clear()
        self._editor_state_labels.clear()

        EVEN_BG  = "#ffffff"
        ODD_BG   = "#f0f0f0"
        GRAY_FG  = "#9e9e9e"
        POLY_FG  = "#1565c0"
        EDIT_FG  = "#003399"
        _f = self.app_ui_font

        for row_idx, char in enumerate(self.dataset.characters):
            bg  = EVEN_BG if row_idx % 2 == 0 else ODD_BG
            raw = taxon.states.get(char.index)

            if raw is None or raw == "M":
                state_str, fg = "?", GRAY_FG
            elif raw == "N":
                state_str, fg = "N/A", GRAY_FG
            elif isinstance(raw, set):
                parts = [char.states.get(s, s) for s in sorted(raw)]
                state_str, fg = " / ".join(parts), POLY_FG
            else:
                state_str, fg = char.states.get(raw, raw), "black"

            # Index cell
            tk.Label(inner, text=str(char.index + 1), bg=bg, fg="#757575",
                     anchor="nw", font=_f
                     ).grid(row=row_idx, column=0, sticky="nsew", padx=(6, 4), pady=2)

            # Character name — left-click = quick name edit; right-click = full definition dialog
            nl = tk.Label(inner, text=char.get_display_name(), bg=bg, fg=EDIT_FG,
                          anchor="nw", font=_f, justify="left", wraplength=200,
                          cursor="hand2")
            nl.grid(row=row_idx, column=1, sticky="nsew", padx=(0, 4), pady=2)
            nl.bind("<Button-1>", lambda e, idx=row_idx: self._editor_edit_char_name(idx))
            nl.bind("<Button-3>", lambda e, idx=row_idx: self._show_char_definition_dialog(idx))
            nl.bind("<Button-2>", lambda e, idx=row_idx: self._show_char_definition_dialog(idx))
            self._editor_name_labels.append(nl)

            # State value — click to edit coded state
            sl = tk.Label(inner, text=state_str, bg=bg, fg=fg,
                          anchor="nw", font=_f, justify="left", wraplength=200,
                          cursor="hand2")
            sl.grid(row=row_idx, column=2, sticky="nsew", padx=(0, 6), pady=2)
            sl.bind("<Button-1>", lambda e, t=taxon, ci=char.index: self._editor_edit_coded_state(t, ci))
            self._editor_state_labels.append(sl)

        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.yview_moveto(0)

        # Re-apply full-width column wraplength to the freshly built rows — no
        # <Configure> fires on a content rebuild, so the placeholder wraplength
        # would otherwise leave the State column collapsed and narrowly wrapped.
        reflow = getattr(canvas, "_carl_reflow", None)
        if reflow is not None:
            canvas.update_idletasks()
            w = canvas.winfo_width()
            if w > 1:
                reflow(w)

    def _show_char_definition_dialog(self, char_idx):
        """Right-click a character name → full Character Definition dialog (2.2)."""
        char = self.dataset.characters[char_idx]

        dlg = tk.Toplevel(self.root)
        dlg.title(f"Character {char_idx + 1} Definition")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.columnconfigure(1, weight=1)

        # Character name
        tk.Label(dlg, text="Name:", anchor="w").grid(
            row=0, column=0, sticky="w", padx=(12, 4), pady=(12, 4))
        name_var = tk.StringVar(value=char.get_display_name())
        tk.Entry(dlg, textvariable=name_var, width=40).grid(
            row=0, column=1, sticky="ew", padx=(0, 12), pady=(12, 4))

        # Character type
        tk.Label(dlg, text="Type:", anchor="w").grid(
            row=1, column=0, sticky="w", padx=(12, 4), pady=4)
        type_var = tk.StringVar(value=getattr(char, "char_type", "multistate"))
        _type_frame = tk.Frame(dlg)
        _type_frame.grid(row=1, column=1, sticky="w", padx=(0, 12), pady=4)
        for _ct in ("multistate", "continuous", "meristic"):
            tk.Radiobutton(_type_frame, text=_ct, variable=type_var,
                           value=_ct).pack(side="left", padx=(0, 8))

        # State labels (multistate)
        tk.Label(dlg, text="States:", anchor="nw").grid(
            row=2, column=0, sticky="nw", padx=(12, 4), pady=4)
        _states_frame = tk.Frame(dlg)
        _states_frame.grid(row=2, column=1, sticky="ew", padx=(0, 12), pady=4)
        _states_frame.columnconfigure(0, weight=1)

        state_listbox = tk.Listbox(_states_frame, height=6, width=36, selectmode="single")
        _slsb = ttk.Scrollbar(_states_frame, command=state_listbox.yview)
        state_listbox.configure(yscrollcommand=_slsb.set)
        state_listbox.grid(row=0, column=0, sticky="ew")
        _slsb.grid(row=0, column=1, sticky="ns")

        # Populate state labels from char.states {id: label}
        _state_items = list(char.states.items())  # [(id, label), ...]
        for sid, slabel in _state_items:
            state_listbox.insert(tk.END, f"{sid}: {slabel}")

        _sbtn = tk.Frame(_states_frame)
        _sbtn.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))

        def _edit_state():
            sel = state_listbox.curselection()
            if not sel:
                return
            idx2 = sel[0]
            sid, slabel = _state_items[idx2]
            self._show_inline_edit(
                title="Edit State Label",
                label=f"State {sid}:",
                initial=slabel,
                on_ok=lambda new, i=idx2, s=sid: _apply_state_label(i, s, new),
            )

        def _apply_state_label(list_idx, sid, new_label):
            _state_items[list_idx] = (sid, new_label)
            state_listbox.delete(list_idx)
            state_listbox.insert(list_idx, f"{sid}: {new_label}")

        tk.Button(_sbtn, text="Edit", command=_edit_state, width=6).pack(side="left", padx=(0, 4))

        # Notes
        tk.Label(dlg, text="Notes:", anchor="nw").grid(
            row=3, column=0, sticky="nw", padx=(12, 4), pady=4)
        notes_text = tk.Text(dlg, height=3, width=40, wrap="word")
        notes_text.grid(row=3, column=1, sticky="ew", padx=(0, 12), pady=4)
        notes_text.insert("1.0", getattr(char, "notes", ""))

        # Ontology term (placeholder)
        tk.Label(dlg, text="Ontology term:", anchor="w").grid(
            row=4, column=0, sticky="w", padx=(12, 4), pady=4)
        onto_var = tk.StringVar(value=getattr(char, "ontology_term", ""))
        tk.Entry(dlg, textvariable=onto_var, width=40,
                 state="disabled").grid(row=4, column=1, sticky="ew", padx=(0, 12), pady=4)
        tk.Label(dlg, text="(available in Phase 4)", fg="gray", font=self.app_ui_font
                 ).grid(row=5, column=1, sticky="w", padx=(0, 12), pady=(0, 4))

        # Buttons
        def _ok():
            new_name = name_var.get().strip()
            if new_name and new_name != char.get_display_name():
                char.name = [new_name]
                self.char_list.delete(char_idx)
                self.char_list.insert(char_idx, char.get_display_name())
                self.char_list.selection_set(char_idx)
            # Apply state label edits
            for sid, slabel in _state_items:
                char.states[sid] = slabel
            char.char_type = type_var.get()
            char.notes = notes_text.get("1.0", "end-1c").strip()
            self._char_edits_pending = True
            self._editor_pending_label.config(text="Unsaved changes — use Nomenclature tab to save")
            self._editor_select_taxon()
            dlg.destroy()

        _btn_row = tk.Frame(dlg)
        _btn_row.grid(row=6, column=0, columnspan=2, pady=(4, 12))
        tk.Button(_btn_row, text="OK",     command=_ok,         width=8).pack(side="left", padx=(0, 6))
        tk.Button(_btn_row, text="Cancel", command=dlg.destroy, width=8).pack(side="left")
        dlg.wait_window()

    def _editor_edit_char_name(self, char_idx):
        """Open inline-edit for a character name (delegates to existing method)."""
        char = self.dataset.characters[char_idx]
        self._show_inline_edit(
            title="Edit Character Name",
            label=f"Character {char_idx + 1}:",
            initial=char.get_display_name(),
            on_ok=lambda new: self._editor_apply_char_name(char_idx, new),
        )

    def _editor_apply_char_name(self, char_idx, new_name):
        """Apply char name edit and refresh Editor + Data tab char list."""
        self._apply_char_name_edit(char_idx, new_name)
        # Refresh the editor right pane with updated name
        self._editor_select_taxon()

    def _editor_edit_coded_state(self, taxon, char_idx):
        """Open inline-edit for a coded state value (raw token, not the label text)."""
        char = self.dataset.characters[char_idx]
        raw  = taxon.states.get(char_idx)
        current_raw = self._editor_raw_str(raw)

        state_hints = "  ".join(f"{k}={v}" for k, v in list(char.states.items())[:6])
        self._show_inline_edit(
            title="Edit Coded State",
            label=f"Char {char_idx + 1}: {char.get_display_name()}\n"
                  f"States: {state_hints}\n"
                  f"Enter: integer key / M / N / {{0 1}}",
            initial=current_raw,
            on_ok=lambda new: self._apply_coded_state_edit(taxon, char_idx, new),
        )

    @staticmethod
    def _editor_raw_str(raw) -> str:
        if raw is None or raw == "M":
            return "M"
        if raw == "N":
            return "N"
        if isinstance(raw, set):
            return "{" + " ".join(sorted(raw)) + "}"
        return str(raw)

    def _apply_coded_state_edit(self, taxon, char_idx, raw_input):
        """Parse, validate and apply a coded state value entered in the Editor."""
        import re as _re
        raw = raw_input.strip()
        char = self.dataset.characters[char_idx]

        if raw in ("?", "M"):
            parsed = "M"
        elif raw == "N":
            parsed = "N"
        elif raw.startswith("{") and raw.endswith("}"):
            tokens = [t.strip() for t in _re.split(r"[,\s]+", raw[1:-1].strip()) if t.strip()]
            invalid = [t for t in tokens if t not in char.states]
            if invalid:
                messagebox.showerror(
                    "Invalid State",
                    f"Unknown state key(s): {', '.join(invalid)}\n"
                    f"Valid keys: {list(char.states.keys())}"
                )
                return
            parsed = set(tokens)
        else:
            if raw not in char.states:
                messagebox.showerror(
                    "Invalid State",
                    f"'{raw}' is not a valid state key for this character.\n"
                    f"Valid keys: {list(char.states.keys())}"
                )
                return
            parsed = raw

        taxon.states[char_idx] = parsed
        self._char_edits_pending = True
        self._editor_pending_label.config(text="Unsaved changes — use Nomenclature tab to save")
        self._fill_editor_states_table(taxon)

    def _editor_save(self):
        """Save to current file (or prompt for path if none set)."""
        self.save_file()
        if not self._char_edits_pending:
            self._editor_pending_label.config(text="")

    # ---- Editor: New / Add DataID / Add Character ----

    def _editor_new(self):
        """Start a blank session: empty Dataset + empty CARLBlock, both panels live."""
        if self.dataset or self.carl_block:
            if not messagebox.askyesno(
                    "New File",
                    "Start a new file? Any unsaved changes will be lost."):
                return
        self.dataset              = Dataset()
        self.carl_block           = CARLBlock()
        self.filepath             = None
        self.groups               = {}
        self.kg                   = {}
        self._char_edits_pending  = False
        self._carl_modified       = False
        self._editor_pending_label.config(text="")
        self._populate_nomenclature_tab("normal")
        self._populate_editor_tab()
        self._update_filepath_display()
        self.status_var.set(
            "New file — add characters and DataIDs in Editor, "
            "then save (Ctrl+S)."
        )

    def _editor_add_dataid(self):
        """Prompt for a DataID name and append it to the dataset."""
        if self.dataset is None:
            messagebox.showinfo("No Dataset",
                                "Click 'New' or load a file before adding DataIDs.")
            return
        self._show_inline_edit(
            title="Add DataID",
            label="DataID (underscores for spaces, e.g. Puma_concolor):",
            initial="",
            on_ok=self._editor_apply_add_dataid,
        )

    def _editor_apply_add_dataid(self, name: str):
        name = name.strip()
        if not name:
            return
        if " " in name:
            messagebox.showerror(
                "Invalid DataID",
                "DataIDs must not contain spaces. Use underscores "
                "(e.g. Puma_concolor).")
            return
        if any(t.name == name for t in self.dataset.taxa):
            messagebox.showerror("Duplicate",
                                 f"DataID '{name}' already exists.")
            return
        self.dataset.taxa.append(Taxon(name))
        self._char_edits_pending = True
        self._editor_pending_label.config(text="Unsaved changes — use Nomenclature tab to save")
        self._populate_editor_tab()
        try:
            self._editor_taxa_list.selection_set(name)
            self._editor_taxa_list.see(name)
            self._editor_select_taxon()
        except tk.TclError:
            pass
        self._populate_nom_dataids()
        self.populate_lists()

    def _editor_add_character(self):
        """Dialog to define a new character (name + state labels) and append it."""
        if self.dataset is None:
            messagebox.showinfo("No Dataset",
                                "Click 'New' or load a file before adding characters.")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("Add Character")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.columnconfigure(1, weight=1)

        tk.Label(dlg, text="Name:", anchor="w").grid(
            row=0, column=0, sticky="w", padx=(12, 4), pady=(12, 4))
        name_var = tk.StringVar()
        tk.Entry(dlg, textvariable=name_var, width=40).grid(
            row=0, column=1, sticky="ew", padx=(0, 12), pady=(12, 4))

        tk.Label(dlg, text="Type:", anchor="w").grid(
            row=1, column=0, sticky="w", padx=(12, 4), pady=4)
        type_var = tk.StringVar(value="multistate")
        _tf = tk.Frame(dlg)
        _tf.grid(row=1, column=1, sticky="w", padx=(0, 12), pady=4)
        for _ct in ("multistate", "continuous", "meristic"):
            tk.Radiobutton(_tf, text=_ct, variable=type_var,
                           value=_ct).pack(side="left", padx=(0, 8))

        tk.Label(dlg, text="States:", anchor="nw").grid(
            row=2, column=0, sticky="nw", padx=(12, 4), pady=4)
        _sf = tk.Frame(dlg)
        _sf.grid(row=2, column=1, sticky="ew", padx=(0, 12), pady=4)
        _sf.columnconfigure(0, weight=1)

        state_lb = tk.Listbox(_sf, height=6, width=36, selectmode="single")
        _slsb = ttk.Scrollbar(_sf, command=state_lb.yview)
        state_lb.configure(yscrollcommand=_slsb.set)
        state_lb.grid(row=0, column=0, sticky="ew")
        _slsb.grid(row=0, column=1, sticky="ns")

        state_labels: list = []

        def _refresh_lb():
            state_lb.delete(0, tk.END)
            for i, lbl in enumerate(state_labels):
                state_lb.insert(tk.END, f"{i}: {lbl}")

        def _add_state():
            self._show_inline_edit(
                title="Add State",
                label="State label:",
                initial="",
                on_ok=lambda lbl: (
                    state_labels.append(lbl.strip()) or _refresh_lb()
                ) if lbl.strip() else None,
            )

        def _remove_state():
            sel = state_lb.curselection()
            if sel:
                del state_labels[sel[0]]
                _refresh_lb()

        _btn = tk.Frame(_sf)
        _btn.grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        tk.Button(_btn, text="+ Add State", command=_add_state).pack(
            side="left", padx=(0, 4))
        tk.Button(_btn, text="Remove",      command=_remove_state).pack(
            side="left")

        def _ok():
            char_name = name_var.get().strip()
            if not char_name:
                messagebox.showerror("Error", "Character name cannot be empty.",
                                     parent=dlg)
                return
            if len(state_labels) < 2:
                messagebox.showerror("Error",
                                     "A character needs at least 2 states.",
                                     parent=dlg)
                return
            new_idx = len(self.dataset.characters)
            states  = {str(i): lbl for i, lbl in enumerate(state_labels)}
            self.dataset.characters.append(
                Character(new_idx, [char_name], states, char_type=type_var.get()))
            self._char_edits_pending = True
            self._editor_pending_label.config(text="Unsaved changes — use Nomenclature tab to save")
            self._editor_select_taxon()   # refresh right pane
            self.populate_lists()         # keep Analyses panel in sync
            dlg.destroy()

        _btn_row = tk.Frame(dlg)
        _btn_row.grid(row=3, column=0, columnspan=2, pady=(4, 12))
        tk.Button(_btn_row, text="OK",     command=_ok,         width=8).pack(
            side="left", padx=(0, 6))
        tk.Button(_btn_row, text="Cancel", command=dlg.destroy, width=8).pack(
            side="left")
        dlg.wait_window()

    # ---- /Editor: New / Add DataID / Add Character ----

    def navigate_to_editor(self, taxon_name: str):
        """Switch to Editor tab and select the row for taxon_name (used by Nomenclature nav)."""
        self._file_nb.select(self.editor_tab)
        tree = self._editor_taxa_list
        try:
            tree.selection_set(taxon_name)
            tree.see(taxon_name)
            self._editor_select_taxon()
        except tk.TclError:
            pass  # iid not present (CARL-only taxon has no matrix row)

    def navigate_to_editor_new_row(self):
        """Switch to Editor tab — selects last matrix taxon as placeholder for 'Create'."""
        self._file_nb.select(self.editor_tab)
        self._editor_select_first()

    # ---- 2.3  Taxon rename + CARL propagation ----

    def _editor_taxa_right_click(self, event):
        tree = self._editor_taxa_list
        iid = tree.identify_row(event.y)
        if not iid or iid.startswith("__"):
            return
        tree.selection_set(iid)
        menu = self._editor_taxa_context_menu
        menu.delete(0, "end")
        menu.add_command(label=f"Rename '{iid}'…",
                         command=lambda: self._editor_start_rename(iid))
        menu.tk_popup(event.x_root, event.y_root)

    def _editor_start_rename(self, old_name):
        self._show_inline_edit(
            title="Rename Taxon",
            label=f"New dataID for '{old_name}':",
            initial=old_name,
            on_ok=lambda new: self._editor_apply_rename(old_name, new),
        )

    def _editor_apply_rename(self, old_name, new_name):
        new_name = new_name.strip()
        if not new_name or new_name == old_name:
            return
        if any(t.name == new_name for t in self.dataset.taxa):
            messagebox.showerror("Name Conflict",
                                 f"A taxon named '{new_name}' already exists in the matrix.")
            return

        # Collect CARL block references affected by this rename
        affected = []
        if self.carl_block is not None:
            for e in self.carl_block.entities:
                if e.data_id == old_name:
                    affected.append(f"  Entity '{e.name}' — data pointer [{e.name}={old_name}]")
            for r in self.carl_block.relationships:
                if r.object_data_id == old_name:
                    subj = next((e for e in self.carl_block.entities
                                 if e.entity_id == r.subject_id), None)
                    subj_name = subj.name if subj else "?"
                    affected.append(f"  Relationship '{subj_name}' → '{r.object_name}={old_name}'")

        if affected:
            msg = (f"Renaming dataID '{old_name}' → '{new_name}' will also update "
                   f"{len(affected)} CARL block reference(s):\n\n"
                   + "\n".join(affected)
                   + "\n\nContinue?")
            if not messagebox.askyesno("CARL Block Update", msg):
                return

        # Apply: update matrix taxon name
        taxon = next((t for t in self.dataset.taxa if t.name == old_name), None)
        if taxon:
            taxon.name = new_name

        # Apply: update in-memory CARL block data_ids
        if self.carl_block is not None:
            for e in self.carl_block.entities:
                if e.data_id == old_name:
                    e.data_id = new_name
            for r in self.carl_block.relationships:
                if r.object_data_id == old_name:
                    r.object_data_id = new_name

        self._char_edits_pending = True
        self._editor_pending_label.config(text="Unsaved changes — use Nomenclature tab to save")

        # Refresh the taxa list and reselect
        self._populate_editor_tab()
        self.navigate_to_editor(new_name)

        # Refresh Analyses panel taxa list after rename
        self._ana_taxa_list.delete(0, tk.END)
        for t in self.dataset.taxa:
            label = self._nom_dataid_to_label.get(t.name, t.name)
            self.taxa_list.insert(tk.END, label)
            self._ana_taxa_list.insert(tk.END, label)
