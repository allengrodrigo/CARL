"""
nomenclature_operations.py — NomenclatureMixin for CARL.

Mixed into TaxonGPT_UI via multiple inheritance. All methods here
assume self.* attributes defined in TaxonGPT_UI.__init__.
"""

import os
import re
import tempfile
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from carl_parser import (TaxonEntity, TaxonRelationship, NONE_ID, _is_real,
                          serialize_carl_block)
from literature_cache import load_cache, load_resources_cache


class NomenclatureMixin:
    """Nomenclature tab methods — mixed into TaxonGPT_UI."""

    def _populate_nom_dataids(self):
        """Fill the DataID Pool pane with all DATA-block taxa; highlight assigned ones."""
        tree = self._dataid_tree
        for item in tree.get_children():
            tree.delete(item)
        self._nom_dataid_to_iid = {}
        self._nom_eid_to_dataids = {}
        self._nom_dataid_to_eids = {}

        if not self.dataset:
            return

        # Build eid→dataids and dataid→eids look-ups from the current CARL block
        if self.carl_block:
            for e in self.carl_block.entities:
                dids: set = set()
                if _is_real(e.data_id):
                    dids.add(e.data_id)
                for r in self.carl_block.relationships:
                    if r.subject_id == e.entity_id and _is_real(r.object_data_id):
                        dids.add(r.object_data_id)
                self._nom_eid_to_dataids[e.entity_id] = dids
                for did in dids:
                    self._nom_dataid_to_eids.setdefault(did, set()).add(e.entity_id)

        # Insert every DATA-block taxon; grey-green background = already assigned
        for t in self.dataset.taxa:
            did = t.name
            assigned = did in self._nom_dataid_to_eids
            tags = ("assigned",) if assigned else ()
            iid = tree.insert("", "end", text=did, tags=tags)
            self._nom_dataid_to_iid[did] = iid

    def _dataid_create_taxa(self):
        """Batch-create definition statements for selected unassigned DataIDs."""
        if not self.carl_block or not self.dataset:
            messagebox.showinfo("No File", "Please load a NEXUS file first.")
            return

        selected_iids = self._dataid_tree.selection()
        if not selected_iids:
            messagebox.showinfo("No Selection",
                                "Select one or more DataIDs from the pool first.")
            return

        all_dids = [self._dataid_tree.item(iid, "text") for iid in selected_iids]
        assigned_set = {
            self._dataid_tree.item(iid, "text")
            for iid in selected_iids
            if "assigned" in self._dataid_tree.item(iid, "tags")
        }
        unassigned = [d for d in all_dids if d not in assigned_set]

        COMMON_RANKS = [
            "species", "subspecies", "variety", "genus", "subgenus",
            "tribe", "subtribe", "family", "subfamily", "superfamily",
            "order", "suborder", "class", "subclass", "phylum",
        ]

        dlg = tk.Toplevel(self.root)
        dlg.title("Create Taxa from DataIDs")
        dlg.resizable(False, False)
        dlg.grab_set()

        body = tk.Frame(dlg, padx=14, pady=10)
        body.pack(fill="both", expand=True)

        n_new = len(unassigned)
        n_skip = len(assigned_set)
        summary = f"Creating {n_new} new statement{'s' if n_new != 1 else ''}"
        if n_skip:
            summary += f"  ({n_skip} already assigned — will be skipped)"
        tk.Label(body, text=summary, anchor="w").pack(fill="x", pady=(0, 4))

        _pf = tk.Frame(body)
        _pf.pack(fill="x", pady=(0, 10))
        _preview_lb = tk.Listbox(_pf, height=min(len(all_dids), 8),
                                 selectmode="none", exportselection=False)
        _preview_vsb = ttk.Scrollbar(_pf, orient="vertical",
                                     command=_preview_lb.yview)
        _preview_lb.configure(yscrollcommand=_preview_vsb.set)
        _preview_lb.pack(side="left", fill="x", expand=True)
        _preview_vsb.pack(side="right", fill="y")
        for did in all_dids:
            _preview_lb.insert(tk.END, did)
            if did in assigned_set:
                _preview_lb.itemconfigure(tk.END, fg="#999999")

        status_var = tk.StringVar(value="is_new")
        _sf = tk.Frame(body)
        _sf.pack(fill="x", pady=(0, 8))
        tk.Label(_sf, text="Status:", width=8, anchor="w").pack(side="left")
        tk.Radiobutton(_sf, text="is_new  (new taxon)",
                       variable=status_var, value="is_new").pack(side="left")
        tk.Radiobutton(_sf, text="is  (existing taxon)",
                       variable=status_var, value="is").pack(side="left", padx=(10, 0))

        rank_var = tk.StringVar()
        _rf = tk.Frame(body)
        _rf.pack(fill="x", pady=(0, 12))
        tk.Label(_rf, text="Rank:", width=8, anchor="w").pack(side="left")
        ttk.Combobox(_rf, textvariable=rank_var,
                     values=COMMON_RANKS, width=22).pack(side="left")

        btn_row = tk.Frame(body)
        btn_row.pack(fill="x")

        def _ok():
            rank = rank_var.get().strip().lower()
            if not rank:
                messagebox.showwarning("Rank Required",
                                       "Please select or enter a rank.", parent=dlg)
                return
            if not unassigned:
                messagebox.showinfo("Nothing to do",
                                    "All selected DataIDs are already assigned.",
                                    parent=dlg)
                return
            status = status_var.get()
            next_eid = max(
                (e.entity_id for e in self.carl_block.entities), default=0) + 1
            for did in unassigned:
                ent = TaxonEntity(
                    entity_id=next_eid,
                    name=did,
                    status=status,
                    rank=rank,
                    data_id=did,
                    action="definition",
                )
                self.carl_block.entities.append(ent)
                self.carl_block._eid[next_eid] = ent
                next_eid += 1
            self._carl_modified = True
            dlg.destroy()
            self._populate_stmt_list()
            self._populate_nom_derived(self._file_state)
            self._populate_nom_dataids()
            self._refresh_derived_panels()
            if self._nom_preview_visible:
                self._nom_preview_update()

        tk.Button(btn_row, text="OK", width=10, command=_ok).pack(side="left")
        tk.Button(btn_row, text="Cancel", width=10,
                  command=dlg.destroy).pack(side="left", padx=(8, 0))

    # -------------------------

    def _populate_nomenclature_tab(self, state):
        """Show all three panes and populate them."""
        self._nom_placeholder.grid_remove()
        self._nom_frame.grid()
        self._nom_toolbar.grid()
        self._nom_left_eid_to_iid = {}
        self._nom_right_iids = {}
        self._nom_right_iid_to_eid = {}
        self._nom_divides_daughter_iids = {}
        self._nom_divides_daughter_info = {}
        self._nom_warn_msgs = {}
        self._nom_dataid_to_iid = {}
        self._nom_eid_to_dataids = {}
        self._nom_dataid_to_eids = {}
        self._nom_iid_meta = {}
        self._populate_stmt_list()
        self._populate_nom_derived(state)
        self._populate_nom_dataids()
        self._lit_cache       = load_cache(self.filepath)            if self.filepath else {}
        self._resources_cache = load_resources_cache(self.filepath) if self.filepath else {}
        self.populate_literature_table()
        self._ana_mirror()
        if self._nom_preview_visible:
            self._nom_preview_update()

    def _populate_stmt_list(self):
        """Fill the statement list (left pane) from carl_block.entities."""
        tree = self._stmt_tree
        for item in tree.get_children():
            tree.delete(item)
        self._nom_left_eid_to_iid = {}
        if not self.carl_block:
            return
        for e in self.carl_block.entities:
            iid = f"stmt_{e.entity_id}"
            self._nom_left_eid_to_iid[e.entity_id] = iid
            tags = ["nov"] if e.status == "is_new" else []
            syntax = self.carl_block.format_statement(e.entity_id)
            tree.insert("", "end", iid=iid, text=syntax,
                        values=(),
                        tags=tuple(tags))

    def _populate_nom_derived(self, state):
        """Fill the derived view (right pane) from carl_block or raw DATA taxa."""
        tree = self.nom_tree
        for item in tree.get_children():
            tree.delete(item)
        self._nom_right_iids = {}
        self._nom_right_iid_to_eid = {}
        self._nom_warn_msgs = {}
        self._nom_iid_meta = {}

        if self.carl_block and self.carl_block.entities:
            eid_map = {e.entity_id: e for e in self.carl_block.entities}
            group_iids: dict = {}

            # Pre-pass: collect all DataIDs per entity to detect conflicts
            entity_data_ids: dict = {}  # entity_name → set of data_ids
            for row in self.carl_block.get_data_tab_rows():
                eid = row.get("entity_id")
                if eid is not None:
                    ent = eid_map.get(eid)
                    if ent and ent.data_id is not None:
                        entity_data_ids.setdefault(ent.name, set()).add(ent.data_id)
                # For relationship member rows, also collect their data_ids
                did = row.get("data_id")
                if did is not None:
                    obj_name = row.get("object_name")
                    if obj_name:
                        entity_data_ids.setdefault(obj_name, set()).add(did)
                    # For divides daughters, also check the entity's own data_id
                    if row.get("note") == "divides_daughter":
                        _obj_name = row.get("object_name") or row["label"].replace(" (Daughter)", "")
                        _daughter_ent = next((e for e in self.carl_block.entities
                                              if e.name == _obj_name), None)
                        if _daughter_ent and _daughter_ent.data_id is not None:
                            entity_data_ids.setdefault(_daughter_ent.name, set()).add(_daughter_ent.data_id)

            # Compute conflict map: {entity_name → True if 2+ distinct DataIDs}
            conflicts = {name: len(dids) > 1 for name, dids in entity_data_ids.items()}

            # W2: names shared by more than one declared taxon
            from collections import Counter
            w2_names = {n for n, c in Counter(e.name for e in self.carl_block.entities).items()
                        if c > 1}

            for row in self.carl_block.get_data_tab_rows():
                label = row["label"]
                is_group_header = row.get("is_group_header", False)
                group_name = row.get("group_name")
                greyed = row["greyed"]
                eid = row.get("entity_id")
                ent = eid_map.get(eid) if eid is not None else None
                # For divides daughters without own entity (entity_id=None),
                # look up the entity by object_name to get rank and status.
                _daughter_ent = None
                if ent is None and row.get("note") == "divides_daughter":
                    _obj_name = row.get("object_name") or label
                    _daughter_ent = next((e for e in self.carl_block.entities
                                          if e.name == _obj_name), None)
                status = ent.status if ent else (_daughter_ent.status if _daughter_ent else "")
                rank   = ent.rank   if ent else (_daughter_ent.rank   if _daughter_ent else "")
                action = ent.action if ent else ""
                action_display = "" if action in ("definition", "") else action
                # Compute per-row warnings
                warn_msgs = []
                if ent and (not ent.rank or ent.rank == "unknown"):
                    warn_msgs.append("Rank not specified")
                # DataID conflict: taxon points to 2+ distinct DataIDs
                check_name = ent.name if ent else (row.get("object_name") or "")
                if check_name and conflicts.get(check_name, False):
                    conflicting_dids = list(entity_data_ids[check_name])
                    dids_str = ", ".join(f"'{did}'" for did in conflicting_dids)
                    warn_msgs.append(
                        f"DataID conflict: '{check_name}' points to multiple DataIDs: {dids_str}"
                    )
                if check_name and check_name in w2_names:
                    warn_msgs.append(
                        f"W2: '{check_name}' is declared as more than one taxon. "
                        "References to this name may be ambiguous — see all declarations "
                        "in the statement list."
                    )
                warn_char = "!" if warn_msgs else ""
                tags = []
                if is_group_header:
                    tags.append("group_header")
                    if row.get("note") == "divides_parent":
                        tags.append("divides_parent")
                elif greyed:
                    tags.append("greyed")
                if "_nov" in label:
                    tags.append("nov")
                if warn_msgs:
                    tags.append("no_rank")
                parent_iid = ""
                if not is_group_header and group_name and group_name in group_iids:
                    parent_iid = group_iids[group_name]
                iid = tree.insert(parent_iid, "end", text=label,
                                  values=(status, rank, action_display, warn_char),
                                  tags=tuple(tags), open=True)
                if warn_msgs:
                    self._nom_warn_msgs[iid] = "; ".join(warn_msgs)
                if is_group_header and group_name:
                    group_iids[group_name] = iid
                if eid is not None:
                    self._nom_right_iids.setdefault(eid, []).append(iid)
                    self._nom_right_iid_to_eid[iid] = eid
                elif row.get("note") == "divides_daughter":
                    self._nom_divides_daughter_iids.setdefault(label, []).append(iid)
                    self._nom_divides_daughter_info[iid] = {
                        "data_id":    row.get("data_id"),
                        "subject_eid": row.get("subject_id"),
                    }
                # Build cache_key and fetchability for Records tab mirroring
                if ent is not None:
                    _ck = row.get("query_name", ent.name) if is_group_header else (row["data_id"] or ent.name)
                else:
                    _ck = row.get("data_id") or label
                self._nom_iid_meta[iid] = {
                    "cache_key":       _ck,
                    "fetchable":       row.get("status") == "is",
                    "is_group_header": is_group_header,
                    "object_name":     row.get("object_name"),
                    "note":            row.get("note"),
                    "subject_eid":     row.get("subject_id"),
                }

    def _nomenclature_right_click(self, event):
        """Show context menu for Nomenclature treeview."""
        tree = self.nom_tree
        item = tree.identify_row(event.y)
        if not item:
            return
        tree.selection_set(item)

        # If the click landed on the ⚠ column and there is a stored message,
        # show it directly instead of the full context menu.
        warn_col = f"#{list(tree['columns']).index('warn') + 1}"
        if tree.identify_column(event.x) == warn_col:
            msg = self._nom_warn_msgs.get(item)
            if msg:
                messagebox.showwarning("⚠ Warning", msg, parent=self.root)
                return

        label = tree.item(item, "text")
        values = tree.item(item, "values")
        status = values[0] if values else ""
        item_tags = tree.item(item, "tags")
        greyed = "greyed" in item_tags
        is_group_header   = "group_header"   in item_tags
        is_divides_parent = "divides_parent" in item_tags

        menu = self._nom_menu
        menu.delete(0, "end")

        if is_group_header and not is_divides_parent:
            menu.add_command(label=f"Group: {label}", state="disabled")
            menu.add_separator()

        if is_divides_parent:
            # Retired parent — real taxon with database records; treat like unit taxon
            if not greyed:
                menu.add_command(
                    label="View character data",
                    command=lambda: self._nom_view_chars(label)
                )
                menu.add_command(
                    label="Edit in Editor",
                    command=lambda lbl=label: self._nom_edit_in_editor(lbl)
                )
            else:
                menu.add_command(
                    label="Create in Editor",
                    command=self.navigate_to_editor_new_row
                )
        elif not greyed and not is_group_header:
            menu.add_command(
                label="View character data",
                command=lambda: self._nom_view_chars(label)
            )
            menu.add_command(
                label="Edit in Editor",
                command=lambda lbl=label: self._nom_edit_in_editor(lbl)
            )
        elif greyed and not is_group_header:
            menu.add_command(
                label="Create in Editor",
                command=self.navigate_to_editor_new_row
            )

        menu.add_command(
            label="Link to data…",
            command=lambda: self._nom_link_to_data(item, label)
        )

        menu.tk_popup(event.x_root, event.y_root)

    def _nom_view_chars(self, display_label):
        """Popup showing character states for the entity named by display_label."""
        if not self.carl_block or not self.dataset:
            return

        # Resolve dataID from CARL block
        rows = self.carl_block.get_data_tab_rows()
        data_id = None
        for row in rows:
            if row["label"] == display_label:
                data_id = row.get("data_id")
                break

        if not data_id:
            messagebox.showinfo("No Data", f"'{display_label}' has no coded data in this matrix.")
            return

        taxon = next((t for t in self.dataset.taxa if t.name == data_id), None)
        if not taxon:
            messagebox.showinfo("Not Found", f"DataID '{data_id}' not found in matrix.")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title(f"Character data — {display_label}")
        dlg.geometry("420x500")

        tk.Label(dlg, text=f"DataID: {data_id}", fg="#555", font=self.app_ui_italic).pack(anchor="w", padx=10, pady=(8, 0))

        lb = tk.Listbox(dlg, width=60)
        sb = ttk.Scrollbar(dlg, command=lb.yview)
        lb.configure(yscrollcommand=sb.set)
        lb.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=8)
        sb.pack(side="right", fill="y", pady=8)

        for i, char in enumerate(self.dataset.characters):
            raw = taxon.states.get(i)
            if raw is None:
                state_str = "—"
            elif raw == "M":
                state_str = "missing"
            elif raw == "N":
                state_str = "N/A"
            elif isinstance(raw, set):
                labels = [char.states.get(s, s) for s in sorted(raw)]
                state_str = " / ".join(labels)
            else:
                state_str = char.states.get(raw, raw)
            lb.insert(tk.END, f"{char.get_display_name()}: {state_str}")

        tk.Button(dlg, text="Close", command=dlg.destroy).pack(pady=6)

    def _nom_edit_in_editor(self, display_label):
        """Navigate to Editor tab for the dataID backing display_label."""
        if not self.carl_block:
            return
        data_id = None
        for row in self.carl_block.get_data_tab_rows():
            if row["label"] == display_label:
                data_id = row.get("data_id")
                break
        if data_id:
            self.navigate_to_editor(data_id)

    def _nom_link_to_data(self, iid, display_label):
        """Picker to assign a matrix dataID to any entity in the Derived View."""
        if not self.dataset or not self.carl_block:
            return

        meta          = self._nom_iid_meta.get(iid, {})
        eid           = self._nom_right_iid_to_eid.get(iid)
        object_name   = meta.get("object_name")
        note          = meta.get("note", "")
        subject_eid   = meta.get("subject_eid")
        daughter_info = self._nom_divides_daughter_info.get(iid)

        if eid is None and not daughter_info and note != "divides_daughter":
            messagebox.showinfo(
                "Not Supported",
                "This row has no direct entity declaration.\n"
                "Declare the taxon as a subject in the Nomenclature tab first.",
                parent=self.root)
            return

        # All matrix taxa are available; mark which are already assigned elsewhere
        already_assigned = set()
        for row in self.carl_block.get_data_tab_rows():
            if row.get("data_id"):
                already_assigned.add(row["data_id"])

        dlg = tk.Toplevel(self.root)
        dlg.title(f"Link '{display_label}' to data row")
        dlg.geometry("320x400")
        dlg.grab_set()

        tk.Label(dlg, text="Select a matrix row to link:").pack(padx=10, pady=(10, 2), anchor="w")
        tk.Label(dlg, text="(grey = already assigned to another entity)",
                 fg="gray", font=self.app_ui_font).pack(padx=10, anchor="w")

        lb = tk.Listbox(dlg, selectmode="single")
        lb.pack(fill="both", expand=True, padx=10, pady=4)

        for taxon in self.dataset.taxa:
            lb.insert(tk.END, taxon.name)
            if taxon.name in already_assigned:
                lb.itemconfig(tk.END, fg="#aaaaaa")

        def _apply():
            sel = lb.curselection()
            if not sel:
                return
            chosen = lb.get(sel[0])
            if chosen in already_assigned:
                if not messagebox.askyesno(
                    "Already Assigned",
                    f"'{chosen}' is already assigned to another entity in the CARL block.\n"
                    "Linking it here will create a shared dataID (warned on load/save).\n\n"
                    "Continue?",
                    parent=dlg
                ):
                    return

            if note == "divides_daughter" and object_name:
                # Divides daughter member: update the divides_to relationship
                s_eid = subject_eid or (daughter_info.get("subject_eid") if daughter_info else None)
                if s_eid is not None:
                    for r in self.carl_block.relationships:
                        if (r.subject_id == s_eid and r.rel_type == "divides_to"
                                and r.object_name == object_name):
                            r.object_data_id = chosen
                            break
            elif object_name:
                # Synonymizes member: update the relationship's object_data_id
                for r in self.carl_block.relationships:
                    if (r.subject_id == eid and r.rel_type == "synonymizes"
                            and r.object_name == object_name):
                        r.object_data_id = chosen
                        break
            else:
                # Entity row (unit taxon, group header incl. divides parent, includes member)
                entity = self.carl_block._eid.get(eid)
                if entity:
                    entity.data_id = chosen

            self._carl_modified = True
            dlg.destroy()
            self._populate_stmt_list()
            self._populate_nom_derived(self._file_state)
            self._populate_nom_dataids()
            self._refresh_derived_panels()

        tk.Button(dlg, text="Link", command=_apply).pack(pady=4)
        tk.Button(dlg, text="Cancel", command=dlg.destroy).pack(pady=2)

    # -------------------------
    # NOMENCLATURE CROSS-SELECT
    # -------------------------

    def _nom_clear_source(self):
        self._nom_source = None

    def _nom_related_for_eid(self, eid):
        """
        Return (set_of_derived_iids, set_of_data_ids) for an entity and all
        nomenclatural dependents that should be co-highlighted.

        synonymizes: member rows already carry the subject's entity_id, so
            _nom_right_iids[eid] already contains the header + all member iids.
            _nom_eid_to_dataids[eid] already contains the subject's data_id +
            every r.object_data_id (built in _populate_nom_dataids).
            → No extra lookup needed; just return everything under eid.

        includes: member taxa appear via their own entity rows, so we must
            walk the relationships and look up each object entity by name.
        """
        derived_iids = set(self._nom_right_iids.get(eid, []))
        data_ids = set(self._nom_eid_to_dataids.get(eid, set()))

        if not self.carl_block:
            return derived_iids, data_ids

        e = self.carl_block._eid.get(eid)
        if e and e.action == "includes":
            name_to_eid = {ent.name: ent.entity_id for ent in self.carl_block.entities}
            for r in self.carl_block.relationships:
                if r.subject_id == eid and r.rel_type == "includes":
                    obj_eid = name_to_eid.get(r.object_name)
                    if obj_eid is not None:
                        derived_iids.update(self._nom_right_iids.get(obj_eid, []))
                        data_ids.update(self._nom_eid_to_dataids.get(obj_eid, set()))

        elif e and e.action == "divides":
            # Highlight all daughter rows under the parent group header:
            # (a) relationship-only rows (entity_id=None) — indexed by daughter name
            # (b) daughters with their own entity rows — indexed by entity_id
            name_to_eid = {ent.name: ent.entity_id for ent in self.carl_block.entities}
            for r in self.carl_block.relationships:
                if r.subject_id == eid and r.rel_type == "divides_to":
                    derived_iids.update(
                        self._nom_divides_daughter_iids.get(r.object_name, []))
                    obj_eid = name_to_eid.get(r.object_name)
                    if obj_eid is not None:
                        derived_iids.update(self._nom_right_iids.get(obj_eid, []))
                        data_ids.update(self._nom_eid_to_dataids.get(obj_eid, set()))
                    if r.object_data_id:
                        data_ids.add(r.object_data_id)

        return derived_iids, data_ids

    def _on_stmt_select(self, event=None):
        """Cross-select derived view and DataID pool when a statement row is clicked."""
        if self._nom_source is not None:
            return
        sel = self._stmt_tree.selection()
        if not sel or not sel[0].startswith("stmt_"):
            return
        try:
            eid = int(sel[0][5:])
        except ValueError:
            return
        self._nom_source = "stmt"
        derived_iids, data_ids = self._nom_related_for_eid(eid)
        # → derived view (all related rows: for synonymizes this is header + all
        #   members; for includes this adds the object entities' own rows)
        if derived_iids:
            iid_list = [i for i in derived_iids if self.nom_tree.exists(i)]
            if iid_list:
                self.nom_tree.selection_set(iid_list)
                self.nom_tree.see(iid_list[0])
            else:
                self.nom_tree.selection_remove(*self.nom_tree.selection())
        else:
            self.nom_tree.selection_remove(*self.nom_tree.selection())
        # → DataID pool (all data_ids covered by this statement)
        self._select_dataids(data_ids)
        self.root.after_idle(self._nom_clear_source)

    def _on_nom_right_select(self, event=None):
        """Cross-select statement and DataID pool when a derived-view row is clicked."""
        if self._nom_source is not None:
            return
        sel = self.nom_tree.selection()
        if not sel:
            return
        # Use the first clicked item to identify the owning entity
        eid = self._nom_right_iid_to_eid.get(sel[0])
        if eid is None:
            # May be a divides daughter row (entity_id=None) — handle separately
            info = self._nom_divides_daughter_info.get(sel[0])
            if info:
                self._nom_source = "deriv"
                subj_eid = info.get("subject_eid")
                if subj_eid is not None:
                    left_iid = f"stmt_{subj_eid}"
                    if self._stmt_tree.exists(left_iid):
                        self._stmt_tree.selection_set(left_iid)
                        self._stmt_tree.see(left_iid)
                did = info.get("data_id")
                self._select_dataids({did} if did else set())
                self.root.after_idle(self._nom_clear_source)
            return
        self._nom_source = "deriv"
        # → stmt tree
        left_iid = f"stmt_{eid}"
        if self._stmt_tree.exists(left_iid):
            self._stmt_tree.selection_set(left_iid)
            self._stmt_tree.see(left_iid)
        # Update DataID pool — do NOT overwrite nom_tree selection so that
        # Ctrl+click multi-selection across entities is preserved for +Add.
        _, data_ids = self._nom_related_for_eid(eid)
        self._select_dataids(data_ids)
        self.root.after_idle(self._nom_clear_source)

    def _on_dataid_select(self, event=None):
        """Cross-select stmt and derived view when a DataID is clicked."""
        if self._nom_source is not None:
            return
        sel = self._dataid_tree.selection()
        if not sel:
            return
        did = self._dataid_tree.item(sel[0], "text")
        eids = self._nom_dataid_to_eids.get(did, set())
        self._nom_source = "dataid"
        # → stmt tree (all entity rows that reference this DataID)
        left_iids = [f"stmt_{eid}" for eid in sorted(eids)
                     if self._stmt_tree.exists(f"stmt_{eid}")]
        if left_iids:
            self._stmt_tree.selection_set(left_iids)
            self._stmt_tree.see(left_iids[0])
        else:
            self._stmt_tree.selection_remove(*self._stmt_tree.selection())
        # → derived view: expand each eid to its full related set
        all_derived: set = set()
        for eid in eids:
            d_iids, _ = self._nom_related_for_eid(eid)
            all_derived.update(d_iids)
        if all_derived:
            iid_list = list(all_derived)
            self.nom_tree.selection_set(iid_list)
            self.nom_tree.see(iid_list[0])
        else:
            self.nom_tree.selection_remove(*self.nom_tree.selection())
        self.root.after_idle(self._nom_clear_source)

    def _select_dataids(self, data_ids):
        """Highlight the given set of DataID names in the DataID pool pane."""
        iids = [iid for did in sorted(data_ids)
                if (iid := self._nom_dataid_to_iid.get(did))]
        if iids:
            self._dataid_tree.selection_set(iids)   # set all at once
            self._dataid_tree.see(iids[0])
        else:
            self._dataid_tree.selection_remove(*self._dataid_tree.selection())

    # -------------------------
    # STATEMENT CRUD
    # -------------------------

    def _stmt_right_click(self, event):
        """Context menu on the statement list."""
        tree = self._stmt_tree
        item = tree.identify_row(event.y)
        if not item:
            return
        if item not in tree.selection():
            tree.selection_set(item)
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Edit…", command=self._stmt_edit_dialog)
        menu.add_command(label="Delete", command=self._stmt_delete)
        menu.add_separator()
        menu.add_command(label="Assign Rank…", command=self._stmt_assign_rank)
        menu.tk_popup(event.x_root, event.y_root)

    def _nom_derived_add(self):
        """Open the +Add dialog pre-filled with taxa selected in the Derived View as objects."""
        if not self.carl_block:
            return

        selected_iids = self.nom_tree.selection()

        # Resolve each selected iid to its backing TaxonEntity name.
        # Rows without an entity_id (synthetic member/daughter rows) are skipped silently.
        object_names = []
        entity_props = []
        seen = set()
        for iid in selected_iids:
            eid = self._nom_right_iid_to_eid.get(iid)
            if eid is None:
                continue
            ent = self.carl_block._eid.get(eid)
            if ent and ent.name not in seen:
                seen.add(ent.name)
                object_names.append(ent.name)
                entity_props.append(ent)

        # No resolvable selection — fall through to the standard empty dialog.
        if not object_names:
            self._stmt_add_dialog()
            return

        # Determine which actions are available.
        # renames is excluded when: more than one object, OR any object is is_new,
        # OR any object's action is synonymizes.
        multi = len(object_names) > 1
        renames_ok = (
            not multi
            and all(e.status != "is_new" for e in entity_props)
            and all(e.action != "synonymizes" for e in entity_props)
        )
        available_actions = ["none", "synonymizes", "includes", "divides"]
        if renames_ok:
            available_actions = ["none", "renames", "synonymizes", "includes", "divides"]

        self._stmt_edit_dialog_impl(
            prefill_objects=object_names,
            available_actions=available_actions,
        )

    def _stmt_add_dialog(self):
        if not self.carl_block:
            return
        self._stmt_edit_dialog_impl(entity_id=None)

    def _stmt_edit_dialog(self):
        sel = self._stmt_tree.selection()
        if not sel:
            messagebox.showinfo("No Selection", "Select a statement to edit.")
            return
        try:
            eid = int(sel[0][5:])
        except (ValueError, IndexError):
            return
        self._stmt_edit_dialog_impl(entity_id=eid)

    def _stmt_edit_dialog_impl(self, entity_id=None,
                               prefill_objects=None, available_actions=None):
        """Unified add / edit dialog for a single CARL statement."""
        is_add = entity_id is None
        existing = None
        existing_rels = []
        if not is_add and self.carl_block:
            existing = self.carl_block._eid.get(entity_id)
            if existing:
                existing_rels = [r for r in self.carl_block.relationships
                                 if r.subject_id == entity_id]

        dlg = tk.Toplevel(self.root)
        dlg.title("Add Statement" if is_add else "Edit Statement")
        dlg.geometry("520x560")
        dlg.resizable(True, True)
        dlg.grab_set()

        COMMON_RANKS = [
            "species", "subspecies", "variety", "genus", "subgenus",
            "tribe", "subtribe", "family", "subfamily", "superfamily",
            "order", "suborder", "class", "subclass", "phylum",
        ]
        data_labels = ["none"] + (
            [t.name for t in self.dataset.taxa] if self.dataset else [])

        def _did_str(d):
            # Python None (blank) → empty string; NONE_ID / real → as-is
            return "" if d is None else d

        def _none_or(s):
            s = (s or "").strip()
            if s in ("", "-"):
                return None        # blank — no DataID specified
            if s == "none":
                return NONE_ID     # explicit no-data sentinel
            return s

        _saved_obj_dids: dict = {}  # populated by do_save() before relationships are cleared

        def _did_for_obj(name):
            # Saved relationship DataIDs take priority — preserves member DataIDs
            # when editing an existing synonymizes/includes statement, and prevents
            # the subject entity's DataID from leaking into same-named members.
            if name in _saved_obj_dids:
                return _saved_obj_dids[name]
            if self.carl_block:
                for e in self.carl_block.entities:
                    if e.name == name:
                        return e.data_id
            return None

        rank_val = (existing.rank or "") if existing else ""
        subject_var = tk.StringVar(value=existing.name if existing else "")
        status_var  = tk.StringVar(value=existing.status if existing else "is")
        rank_var    = tk.StringVar(value="" if rank_val in ("unknown", "") else rank_val)
        init_act    = existing.action if existing else "definition"
        action_var  = tk.StringVar(value="none" if init_act == "definition" else init_act)
        comment_var = tk.StringVar(value=(existing.comment or "") if existing else "")

        body = tk.Frame(dlg, padx=12, pady=8)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        tk.Label(body, text="Subject name:", anchor="w").grid(
            row=0, column=0, sticky="w", pady=3)
        subj_entry = tk.Entry(body, textvariable=subject_var, width=30)
        subj_entry.grid(row=0, column=1, sticky="ew", pady=3)

        tk.Label(body, text="Status:", anchor="w").grid(
            row=1, column=0, sticky="w", pady=3)
        _sf = tk.Frame(body)
        _sf.grid(row=1, column=1, sticky="w")
        tk.Radiobutton(_sf, text="is  (existing)", variable=status_var, value="is").pack(side="left")
        tk.Radiobutton(_sf, text="is_new  (new)", variable=status_var, value="is_new").pack(side="left", padx=8)

        tk.Label(body, text="Rank:", anchor="w").grid(
            row=2, column=0, sticky="w", pady=3)
        ttk.Combobox(body, textvariable=rank_var, values=COMMON_RANKS, width=20).grid(
            row=2, column=1, sticky="w")

        tk.Label(body, text="Action:", anchor="w").grid(
            row=3, column=0, sticky="w", pady=3)
        _action_values = available_actions or [
            "none", "renames", "synonymizes", "includes", "divides"]
        ttk.Combobox(body, textvariable=action_var,
                     values=_action_values,
                     state="readonly", width=20).grid(row=3, column=1, sticky="w")

        dyn_lf = tk.LabelFrame(body, text="DataIDs & Relationships", padx=6, pady=6)
        dyn_lf.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        dyn_lf.columnconfigure(1, weight=1)
        body.rowconfigure(4, weight=1)

        _dyn = {}

        def _rebuild(*_):
            for w in dyn_lf.winfo_children():
                w.destroy()
            _dyn.clear()
            act  = action_var.get()
            # For divides via +Add: the selected entity is the subject (parent), not a daughter
            if act == "divides" and prefill_objects and not subject_var.get().strip():
                subject_var.set(prefill_objects[0])
            subj = subject_var.get().strip() or "subject"
            r = 0
            tk.Label(dyn_lf, text=f"{subj}  →  DataID:", anchor="w").grid(
                row=r, column=0, sticky="w", pady=2)
            # Pre-fill subject DataID from prefill entity when action is divides
            if existing:
                _subj_did_val = existing.data_id
            elif act == "divides" and prefill_objects:
                # Pre-fill subject DataID from the entity being divided so the user
                # can see and resolve the conflict with any same-named daughter.
                # The shared-DataID warning fires on save if both are left pointing
                # to the same row. See [[divides-dataid-logic]]
                _pf_ent = next((e for e in self.carl_block.entities
                                if e.name == prefill_objects[0]), None)
                _subj_did_val = _pf_ent.data_id if _pf_ent else None
            else:
                # synonymizes/includes: subject DataID must default to none.
                # The subject is an aggregate concept; its members retain their own
                # DataIDs. Auto-filling from a member entity would create a
                # shared-DataID conflict. The combobox remains editable so the user
                # can point to a separately pre-coded row (e.g. "SynTaxon1").
                if act in ("synonymizes", "includes"):
                    _subj_did_val = None
                else:
                    # renames / definition: pre-fill from existing entity with same name
                    _named_ent = (next((e for e in self.carl_block.entities
                                        if e.name == subj), None)
                                  if self.carl_block and subj not in ("", "subject")
                                  else None)
                    _subj_did_val = _named_ent.data_id if _named_ent else None
            v_sd = tk.StringVar(value=_did_str(_subj_did_val))
            ttk.Combobox(dyn_lf, textvariable=v_sd, values=data_labels, width=22).grid(
                row=r, column=1, sticky="ew", pady=2)
            _dyn["subj_did"] = v_sd
            r += 1
            if act == "renames":
                tk.Label(dyn_lf, text="Old name:", anchor="w").grid(
                    row=r, column=0, sticky="w", pady=2)
                # Pool: full CARL statements for all entities except subject name.
                # One entry per entity so W2 names are individually selectable.
                _subj_name = subject_var.get().strip()
                _all_ents = self.carl_block.entities if self.carl_block else []
                _stmt_to_entity = {
                    self.carl_block.format_statement(e.entity_id): e
                    for e in _all_ents if e.name not in (_subj_name, "")
                } if self.carl_block else {}
                _dyn["stmt_to_entity"] = _stmt_to_entity
                _carl_pool = sorted(_stmt_to_entity.keys())
                # Find the label that matches the existing/prefill old name.
                # Use object_entity_id when available for W2 disambiguation.
                _renames_default = ""
                if existing_rels:
                    _r0 = existing_rels[0]
                    if _r0.object_entity_id is not None:
                        _renames_default = next(
                            (lbl for lbl, e in _stmt_to_entity.items()
                             if e.entity_id == _r0.object_entity_id),
                            _r0.object_name)
                    else:
                        _renames_default = next(
                            (lbl for lbl, e in _stmt_to_entity.items()
                             if e.name == _r0.object_name
                             and (_r0.object_data_id is None
                                  or e.data_id == _r0.object_data_id)),
                            _r0.object_name)
                elif prefill_objects:
                    _pf_name = prefill_objects[0]
                    _renames_default = next(
                        (lbl for lbl, e in _stmt_to_entity.items() if e.name == _pf_name),
                        _pf_name)
                v_on = tk.StringVar(value=_renames_default)
                _on_combo = ttk.Combobox(dyn_lf, textvariable=v_on,
                                         values=_carl_pool, state="readonly", width=24)
                _on_combo.grid(row=r, column=1, sticky="ew", pady=2)
                _dyn["old_name"] = v_on
                r += 1
                tk.Label(dyn_lf, text="Old name  →  DataID:", anchor="w").grid(
                    row=r, column=0, sticky="w", pady=2)
                _renames_ent = _stmt_to_entity.get(_renames_default)
                _prefill_old_did = (
                    existing_rels[0].object_data_id if existing_rels
                    else (_saved_obj_dids.get(_renames_ent.name, _renames_ent.data_id)
                          if _renames_ent else None))
                v_od = tk.StringVar(value=_did_str(_prefill_old_did))
                _od_combo = ttk.Combobox(dyn_lf, textvariable=v_od,
                                         values=data_labels, width=22)
                _od_combo.grid(row=r, column=1, sticky="ew", pady=2)
                _dyn["old_did"] = v_od

                def _sync_old_did(*_, _v_on=v_on, _v_od=v_od):
                    lbl = _v_on.get()
                    _s2e = _dyn.get("stmt_to_entity", {})
                    _e = _s2e.get(lbl)
                    if _e:
                        auto = _saved_obj_dids.get(_e.name, _e.data_id)
                    else:
                        auto = _did_for_obj(lbl)
                    _v_od.set(_did_str(auto))
                v_on.trace_add("write", _sync_old_did)
            elif act in ("synonymizes", "includes"):
                # Pool = full CARL statements for all eligible entities.
                # One entry per entity so W2 names are individually selectable.
                subj_name = subject_var.get().strip()
                _all_ents = self.carl_block.entities if self.carl_block else []
                _pool_exclude_names = {""} if act == "synonymizes" else {subj_name, ""}
                _stmt_to_entity = {
                    self.carl_block.format_statement(e.entity_id): e
                    for e in _all_ents if e.name not in _pool_exclude_names
                } if self.carl_block else {}
                _dyn["stmt_to_entity"] = _stmt_to_entity
                pool = sorted(_stmt_to_entity.keys())
                # Preselect labels that match previously saved relationships.
                # Use object_entity_id when available (in-session W2 disambiguation);
                # fall back to name+DataID matching (post-reload path).
                preselected_labels = set()
                for rel in existing_rels:
                    if rel.object_entity_id is not None:
                        _match = next(
                            (lbl for lbl, e in _stmt_to_entity.items()
                             if e.entity_id == rel.object_entity_id),
                            None)
                    else:
                        _match = next(
                            (lbl for lbl, e in _stmt_to_entity.items()
                             if e.name == rel.object_name
                             and (rel.object_data_id is None
                                  or e.data_id == rel.object_data_id)),
                            None)
                    if _match:
                        preselected_labels.add(_match)
                if prefill_objects:
                    for _pname in prefill_objects:
                        _match = next(
                            (lbl for lbl, e in _stmt_to_entity.items() if e.name == _pname),
                            None)
                        if _match:
                            preselected_labels.add(_match)

                tk.Label(dyn_lf, text="Taxa:", anchor="nw").grid(
                    row=r, column=0, sticky="nw", pady=2)
                _lb_frame = tk.Frame(dyn_lf)
                _lb_frame.grid(row=r, column=1, sticky="nsew", pady=2)
                _lb_frame.columnconfigure(0, weight=1)
                _lb_frame.rowconfigure(0, weight=1)
                lb = tk.Listbox(_lb_frame, selectmode="multiple",
                                height=8, exportselection=False)
                _lb_vsb = ttk.Scrollbar(_lb_frame, orient="vertical", command=lb.yview)
                lb.configure(yscrollcommand=_lb_vsb.set)
                lb.grid(row=0, column=0, sticky="nsew")
                _lb_vsb.grid(row=0, column=1, sticky="ns")
                for lbl in pool:
                    lb.insert(tk.END, lbl)
                    if lbl in preselected_labels:
                        lb.selection_set(tk.END)
                _dyn["obj_list"] = lb
                dyn_lf.rowconfigure(r, weight=1)
            elif act == "divides":
                # Daughters section: dynamic rows, each a full TaxonEntity specification
                _daughters_outer = tk.Frame(dyn_lf)
                _daughters_outer.grid(row=r, column=0, columnspan=2,
                                      sticky="nsew", pady=(4, 0))
                _daughters_outer.columnconfigure(0, weight=1)
                dyn_lf.rowconfigure(r, weight=1)

                _hdr_f = tk.Frame(_daughters_outer)
                _hdr_f.pack(fill="x")
                for _col_text, _col_w in [("Daughter name", 14), ("Status", 7),
                                           ("Rank", 10), ("DataID", 13)]:
                    tk.Label(_hdr_f, text=_col_text, font=self.app_ui_font,
                             anchor="w", width=_col_w).pack(side="left", padx=2)

                _rows_frame = tk.Frame(_daughters_outer)
                _rows_frame.pack(fill="both", expand=True)

                daughter_rows = []
                _dyn["daughter_rows"] = daughter_rows

                def _make_daughter_row(name="", status="is", rank="", did=None):
                    row_f = tk.Frame(_rows_frame)
                    row_f.pack(fill="x", pady=1)
                    n_var = tk.StringVar(value=name)
                    s_var = tk.StringVar(value=status)
                    r_var = tk.StringVar(value=rank)
                    d_var = tk.StringVar(value=_did_str(did))
                    tk.Entry(row_f, textvariable=n_var, width=14).pack(side="left", padx=2)
                    ttk.Combobox(row_f, textvariable=s_var, values=["is", "is_new"],
                                 state="readonly", width=7).pack(side="left", padx=2)
                    ttk.Combobox(row_f, textvariable=r_var, values=COMMON_RANKS,
                                 width=10).pack(side="left", padx=2)
                    ttk.Combobox(row_f, textvariable=d_var, values=data_labels,
                                 width=13).pack(side="left", padx=2)
                    row_data = {"frame": row_f, "name_var": n_var, "status_var": s_var,
                                "rank_var": r_var, "did_var": d_var}
                    daughter_rows.append(row_data)
                    def _remove(rd=row_data, rf=row_f):
                        rf.destroy()
                        if rd in daughter_rows:
                            daughter_rows.remove(rd)
                    tk.Button(row_f, text="×", width=2, pady=0,
                              command=_remove).pack(side="left", padx=2)

                # Populate daughters:
                #   Editing — load from existing_rels (the stored divides_to records)
                #   +Add    — pre-fill first row from the selected entity
                if existing_rels:
                    for _rel in existing_rels:
                        _d_ent = next((e for e in self.carl_block.entities
                                       if e.name == _rel.object_name), None)
                        _make_daughter_row(
                            name=_rel.object_name,
                            status=_d_ent.status if _d_ent else "is",
                            rank=_d_ent.rank if _d_ent else (rank_var.get() or ""),
                            did=_rel.object_data_id,
                        )
                elif prefill_objects:
                    _pf_name = prefill_objects[0]
                    _pf_e = next((e for e in self.carl_block.entities
                                  if e.name == _pf_name), None)
                    _make_daughter_row(
                        name=_pf_name,
                        status=_pf_e.status if _pf_e else "is",
                        rank=_pf_e.rank if _pf_e else (rank_var.get() or ""),
                        did=_pf_e.data_id if _pf_e else None,
                    )

                tk.Button(_daughters_outer, text="+ Add Daughter", pady=0,
                          command=lambda: _make_daughter_row(
                              rank=rank_var.get())).pack(anchor="w", pady=4)

            # Comment field — always present, defined outside _rebuild so it
            # survives action-change rebuilds
            r += 1
            tk.Label(dyn_lf, text="Comment:", anchor="w").grid(
                row=r, column=0, sticky="w", pady=(8, 2))
            tk.Entry(dyn_lf, textvariable=comment_var, width=28).grid(
                row=r, column=1, sticky="ew", pady=(8, 2))

        subj_entry.bind("<FocusOut>", _rebuild)
        action_var.trace_add("write", _rebuild)
        _rebuild()

        btn_f = tk.Frame(dlg)
        btn_f.pack(fill="x", padx=12, pady=8)

        def _ok():
            subj = subject_var.get().strip()
            if not subj:
                messagebox.showwarning("Missing", "Subject name is required.", parent=dlg)
                return
            rank            = rank_var.get().strip() or "unknown"
            status          = status_var.get()
            act             = action_var.get()
            internal_action = "definition" if act == "none" else act
            subj_did        = _none_or(_dyn.get("subj_did", tk.StringVar(value="none")).get())

            comment_val = comment_var.get().strip() or None

            # Pre-validate renames DataID assignments before modifying carl_block.
            if internal_action == "renames":
                _pre_old_name = _dyn.get("old_name", tk.StringVar()).get().strip()
                _pre_old_did  = _none_or(
                    _dyn.get("old_did", tk.StringVar(value="none")).get())

                # Case B: both subject DataID and object DataID are non-None.
                # Inheritance fires when object_data_id is set, giving the
                # subject two data rows. Valid forms: subject=DataID/object=none
                # OR subject=none/object=DataID — never both non-None.
                if subj_did is not None and _pre_old_did is not None:
                    messagebox.showerror(
                        "DataID Conflict",
                        f"Both '{subj}' (DataID='{subj_did}') and the old name "
                        f"'{_pre_old_name}' (DataID='{_pre_old_did}') have "
                        "explicit DataIDs.\n\n"
                        "For a renames statement, use one of:\n"
                        "  • subject=DataID / old name=none  "
                        "(new name claims data, old released)\n"
                        "  • subject=none / old name=DataID  "
                        "(new name inherits data from old name)",
                        parent=dlg)
                    return

                # Case A: object DataID conflicts with the object entity's
                # own declared data_id.
                if _pre_old_did is not None and _pre_old_name:
                    _obj_ent = next(
                        (e for e in self.carl_block.entities
                         if e.name == _pre_old_name), None)
                    if (_obj_ent is not None
                            and _obj_ent.data_id is not None
                            and _obj_ent.data_id != _pre_old_did):
                        messagebox.showerror(
                            "DataID Conflict",
                            f"'{_pre_old_name}' is declared as an entity with "
                            f"DataID '{_obj_ent.data_id}', but the 'Old name → "
                            f"DataID' field specifies '{_pre_old_did}'.\n\n"
                            "A taxon can only point to one DataID. Set the old "
                            "name DataID to match the entity, or set it to "
                            "'none' to use inheritance.",
                            parent=dlg)
                        return

            if is_add:
                # If an entity with the same identity (name + action) already exists,
                # update it in place to avoid a duplicate entry.
                # Do NOT match on name alone — a definition entity and a divides
                # entity sharing a name are distinct taxa (W2) and must not merge.
                _existing_named = next((e for e in self.carl_block.entities
                                        if e.name == subj
                                        and e.action == internal_action), None)
                if _existing_named:
                    _existing_named.status  = status
                    _existing_named.rank    = rank
                    _existing_named.action  = internal_action
                    _existing_named.comment = comment_val
                    if (subj_did is not None
                            and _existing_named.data_id is not None
                            and _existing_named.data_id != subj_did):
                        if not messagebox.askyesno(
                                "DataID Conflict",
                                f"'{subj}' already has DataID "
                                f"'{_existing_named.data_id}'.\n"
                                f"Changing it to '{subj_did}' will overwrite "
                                "the existing assignment.\n\nProceed?",
                                parent=dlg):
                            return
                    _existing_named.data_id = subj_did
                    use_eid = _existing_named.entity_id
                    _saved_obj_dids.update({
                        r.object_name: r.object_data_id
                        for r in self.carl_block.relationships
                        if r.subject_id == use_eid})
                    self.carl_block.relationships = [
                        r for r in self.carl_block.relationships
                        if r.subject_id != use_eid]
                else:
                    new_eid = max((e.entity_id for e in self.carl_block.entities),
                                  default=0) + 1
                    ent = TaxonEntity(entity_id=new_eid, name=subj, status=status,
                                      rank=rank, data_id=subj_did, action=internal_action,
                                      comment=comment_val)
                    self.carl_block.entities.append(ent)
                    self.carl_block._eid[new_eid] = ent
                    use_eid = new_eid
            else:
                e = self.carl_block._eid.get(entity_id)
                if e:
                    e.name = subj; e.status = status; e.rank = rank
                    e.action = internal_action; e.data_id = subj_did
                    e.comment = comment_val
                use_eid = entity_id
                _saved_obj_dids.update({
                    r.object_name: r.object_data_id
                    for r in self.carl_block.relationships
                    if r.subject_id == entity_id})
                self.carl_block.relationships = [
                    r for r in self.carl_block.relationships
                    if r.subject_id != entity_id]

            _s2e = _dyn.get("stmt_to_entity", {})
            if internal_action == "renames":
                old_label = _dyn.get("old_name", tk.StringVar()).get().strip()
                _old_ent  = _s2e.get(old_label)
                old_name  = _old_ent.name if _old_ent else old_label
                old_did   = _none_or(_dyn.get("old_did", tk.StringVar(value="none")).get())
                if old_name:
                    self.carl_block.relationships.append(TaxonRelationship(
                        subject_id=use_eid, rel_type="renames_from",
                        object_name=old_name, object_data_id=old_did,
                        object_entity_id=_old_ent.entity_id if _old_ent else None))
            elif internal_action in ("synonymizes", "includes"):
                lb = _dyn.get("obj_list")
                if lb:
                    rt = {"synonymizes": "synonymizes",
                          "includes": "includes"}[internal_action]
                    for idx in lb.curselection():
                        lbl = lb.get(idx)
                        _ent = _s2e.get(lbl)
                        if _ent:
                            oname = _ent.name
                            odid  = _saved_obj_dids.get(oname, _ent.data_id)
                        else:
                            oname = lbl
                            odid  = _did_for_obj(oname)
                        if oname:
                            self.carl_block.relationships.append(TaxonRelationship(
                                subject_id=use_eid, rel_type=rt,
                                object_name=oname, object_data_id=odid,
                                object_entity_id=_ent.entity_id if _ent else None))
            elif internal_action == "divides":
                daughter_rows = _dyn.get("daughter_rows", [])

                # Warn if any new daughter (not the same-named one) is left
                # with the default status "is" — it may actually be is_new.
                _unconfirmed = [
                    row_data["name_var"].get().strip()
                    for row_data in daughter_rows
                    if row_data["name_var"].get().strip()
                    and row_data["name_var"].get().strip() != subj
                    and row_data["status_var"].get() == "is"
                    and not any(e.name == row_data["name_var"].get().strip()
                                for e in self.carl_block.entities)
                ]
                if _unconfirmed:
                    _names = "\n".join(f"  • {n}" for n in _unconfirmed)
                    if not messagebox.askyesno(
                        "Check Daughter Status",
                        f"The following daughter(s) have no prior declaration and "
                        f"will be created with status 'is' (existing taxon):\n\n"
                        f"{_names}\n\n"
                        f"If any of these are new to science, click No and change "
                        f"their status to 'is_new' before saving.\n\n"
                        f"Continue with 'is'?",
                        parent=dlg,
                    ):
                        return

                next_eid = max((e.entity_id for e in self.carl_block.entities),
                               default=0) + 1
                for row_data in daughter_rows:
                    dname  = row_data["name_var"].get().strip()
                    if not dname:
                        continue
                    dstatus = row_data["status_var"].get()
                    drank   = row_data["rank_var"].get().strip() or "unknown"
                    ddid    = _none_or(row_data["did_var"].get())
                    existing_d = next((e for e in self.carl_block.entities
                                       if e.name == dname), None)
                    if existing_d is None:
                        new_d = TaxonEntity(
                            entity_id=next_eid, name=dname,
                            status=dstatus, rank=drank,
                            data_id=ddid, action="definition", comment=None)
                        self.carl_block.entities.append(new_d)
                        self.carl_block._eid[next_eid] = new_d
                        next_eid += 1
                    elif existing_d.entity_id != use_eid:
                        # Existing entity: leave its properties untouched.
                        # Its status/rank/data_id come from its own declaration.
                        # The in-statement DataID is stored in object_data_id below.
                        pass
                    self.carl_block.relationships.append(TaxonRelationship(
                        subject_id=use_eid, rel_type="divides_to",
                        object_name=dname, object_data_id=ddid))

            self.carl_block._eid = {e.entity_id: e for e in self.carl_block.entities}
            self._carl_modified = True
            dlg.destroy()
            self._populate_stmt_list()
            self._populate_nom_derived(self._file_state)
            self._populate_nom_dataids()
            self._refresh_derived_panels()
            if self._nom_preview_visible:
                self._nom_preview_update()

        if prefill_objects:
            tk.Label(body, text="Note: statement logic is not validated — GIGO applies.",
                     fg="#996600", font=self.app_ui_italic,
                     anchor="w").grid(row=6, column=0, columnspan=2,
                                      sticky="w", pady=(6, 0))

        tk.Button(btn_f, text="OK",     width=10, command=_ok).pack(side="left")
        tk.Button(btn_f, text="Cancel", width=10, command=dlg.destroy).pack(side="left", padx=6)
        subj_entry.focus_set()

    def _stmt_delete(self):
        sel = self._stmt_tree.selection()
        if not sel:
            messagebox.showinfo("No Selection", "Select one or more statements to delete.")
            return
        names, eids = [], set()
        for iid in sel:
            try:
                eid = int(iid[5:])
                e   = self.carl_block._eid.get(eid) if self.carl_block else None
                if e:
                    names.append(e.name)
                    eids.add(eid)
            except (ValueError, AttributeError):
                pass
        if not names:
            return
        if not messagebox.askyesno("Delete Statements",
                f"Delete {len(names)} statement(s)?\n"
                + "\n".join(f"  • {n}" for n in names)):
            return
        self.carl_block.entities     = [e for e in self.carl_block.entities
                                         if e.entity_id not in eids]
        self.carl_block.relationships = [r for r in self.carl_block.relationships
                                          if r.subject_id not in eids]
        self.carl_block._eid         = {e.entity_id: e for e in self.carl_block.entities}
        self._carl_modified = True
        self._populate_stmt_list()
        self._populate_nom_derived(self._file_state)
        self._populate_nom_dataids()
        self._refresh_derived_panels()
        if self._nom_preview_visible:
            self._nom_preview_update()

    def _stmt_assign_rank(self):
        sel = self._stmt_tree.selection()
        if not sel:
            messagebox.showinfo("No Selection",
                                "Select one or more statements to assign a rank.")
            return
        COMMON_RANKS = [
            "species", "subspecies", "variety", "genus", "subgenus",
            "tribe", "subtribe", "family", "subfamily", "superfamily",
            "order", "suborder", "class", "subclass", "phylum",
        ]
        dlg = tk.Toplevel(self.root)
        dlg.title("Assign Rank")
        dlg.geometry("280x120")
        dlg.grab_set()
        tk.Label(dlg, text=f"Rank for {len(sel)} selected statement(s):").pack(
            pady=(12, 4), padx=12)
        rank_var = tk.StringVar()
        ttk.Combobox(dlg, textvariable=rank_var, values=COMMON_RANKS, width=24).pack(padx=12)

        def _apply():
            rank = rank_var.get().strip()
            if not rank:
                return
            for iid in sel:
                try:
                    eid = int(iid[5:])
                    e   = self.carl_block._eid.get(eid) if self.carl_block else None
                    if e:
                        e.rank = rank
                except (ValueError, AttributeError):
                    pass
            self._carl_modified = True
            dlg.destroy()
            self._populate_stmt_list()
            self._populate_nom_derived(self._file_state)
            self._populate_nom_dataids()
            self._refresh_derived_panels()
            if self._nom_preview_visible:
                self._nom_preview_update()

        tk.Button(dlg, text="Apply", command=_apply).pack(pady=8)

    # -------------------------
    # PREVIEW + SAVE
    # -------------------------

    def _nom_preview_toggle(self):
        if self._nom_preview_visible:
            self._nom_preview_frame.grid_remove()
            self._nom_preview_visible = False
            self._nom_preview_btn.config(text="▼ Preview")
        else:
            self._nom_preview_frame.grid()
            self._nom_preview_visible = True
            self._nom_preview_btn.config(text="▲ Preview")
            self._nom_preview_update()

    def _nom_preview_update(self):
        text = self.carl_block.serialize() if self.carl_block else ""
        self._nom_preview_text.config(state="normal")
        self._nom_preview_text.delete("1.0", "end")
        if text:
            self._nom_preview_text.insert("1.0", text)
        self._nom_preview_text.config(state="disabled")

    def _nom_preview_copy(self):
        if not self.carl_block:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.carl_block.serialize())

    def _nom_save_to_nex(self):
        """Serialize the current CARLBlock and write it into the loaded NEXUS file."""
        if not self.carl_block:
            messagebox.showinfo("No Statements", "No CARL statements to save.")
            return
        if not self.filepath:
            messagebox.showerror("No File", "No NEXUS file loaded.")
            return

        warnings_list = [f"  • {e.name}: rank not set"
                         for e in self.carl_block.entities
                         if not e.rank or e.rank == "unknown"]
        if warnings_list:
            if not messagebox.askyesno(
                    "Incomplete Statements",
                    "Some statements have no rank:\n"
                    + "\n".join(warnings_list)
                    + "\n\nSave anyway?"):
                return

        # Ensure preview is visible so the user can review what will be written
        if not self._nom_preview_visible:
            self._nom_preview_toggle()
        else:
            self._nom_preview_update()

        if not messagebox.askyesno(
                "Confirm Save",
                f"Write CARL block to:\n{self.filepath}\n\n"
                "This will replace any existing CARL block."):
            return

        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except OSError as ex:
            messagebox.showerror("Read Error", str(ex))
            return

        # Serialise the CARL block, preserving verbatim any preclusion lines
        # already in the file's CARL block.
        carl_text = serialize_carl_block(self.carl_block, content)

        # Remove any existing CARL block, append new one
        content_no_carl = re.sub(
            r'\nBEGIN\s+CARL\s*;.*?END\s*;', '',
            content, flags=re.DOTALL | re.IGNORECASE)
        new_content = content_no_carl.rstrip() + "\n\n" + carl_text + "\n"

        dir_     = os.path.dirname(os.path.abspath(self.filepath))
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=dir_,
                    suffix=".tmp", delete=False) as tmp:
                tmp.write(new_content)
                tmp_path = tmp.name
            os.replace(tmp_path, self.filepath)
            self.dataset_text   = new_content
            self._carl_modified = False
            messagebox.showinfo("Saved", "CARL block written successfully.")
        except OSError as ex:
            messagebox.showerror("Write Error", str(ex))
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
