"""
information_operations.py — InformationMixin for CARL.

Mixed into TaxonGPT_UI via multiple inheritance. All methods here
assume self.* attributes defined in TaxonGPT_UI.__init__.
"""

import os
import re
import threading
import time
import tkinter as tk
import tkinter.font as tkFont
from tkinter import ttk, messagebox, filedialog
import webbrowser

from literature_cache import (
    fetch_taxon_entry,
    save_cache_atomic,
    is_new_format,
    entry_has_data,
    INTER_TAXON_DELAY,
    DEFAULT_PROVIDER_ORDER,
    save_resources_cache,
    load_resources_cache,
)
from darwin_core import (RECOMMENDED as DEFAULT_FIELDS, SECTIONS, BY_SECTION,
                         VOCAB_TYPE, CONTROLLED_VOCAB)
from biodiversity_apis import (
    resolve_gbif_backbone_rich, fetch_gbif_children, fetch_gbif_species_profiles,
    fetch_gbif_references, fetch_gbif_pub_dicts,
    get_zoobank_full,
    get_crossref_pub_dicts,
    get_col_full,
    get_ncbi_records,
    fetch_gbif_synonyms,
    fetch_gbif_descriptions,
    fetch_gbif_image_urls,
    fetch_gbif_specimens,
    get_plazi_all, get_plazi_keys_full,
    fetch_bhl_enriched, get_bhl_pub_dicts,
    fetch_itis_summary, fetch_itis_synonyms,
    fetch_worms_summary, fetch_worms_synonyms, fetch_worms_children,
    fetch_wsc_profile,
    fetch_powo_profile,
    fetch_bacdive_profile,
    resolve_publications,
    fetch_wikipedia_report,
    summarize_wikipedia_llm,
    _canonical_key, _name_authorship, _auth_year, _auth_key,
    _tabulate, _RANK_PLURAL,
)


class InformationMixin:
    """Information panel methods — mixed into TaxonGPT_UI."""

    # ==========================================================
    # LITERATURE CACHING
    # ==========================================================

    def _apply_provider_settings(self):
        """Read provider UI vars → update _lit_provider_settings."""
        for prov in DEFAULT_PROVIDER_ORDER:
            self._lit_provider_settings[prov] = {
                "enabled":  self._lit_prov_enabled_vars[prov].get(),
                "priority": self._lit_prov_priority_vars[prov].get(),
            }

    def _apply_field_settings(self):
        """Read field UI vars → update _lit_retrieve_fields / _lit_include_fields."""
        self._lit_retrieve_fields = {
            term for term, v in self._lit_field_vars.items() if v["retrieve"].get()
        }
        self._lit_include_fields = {
            term for term, v in self._lit_field_vars.items() if v["include"].get()
        }

    def _reset_lit_fields_to_recommended(self):
        """Reset both field sets to RECOMMENDED and refresh the checkboxes."""
        self._lit_retrieve_fields = set(DEFAULT_FIELDS)
        self._lit_include_fields  = set(DEFAULT_FIELDS)
        self._refresh_lit_field_ui()

    def _save_lit_fields_as_default(self):
        """Persist current field and provider settings to taxongpt_settings.json."""
        self.save_settings()
        self.lit_status_var.set("Field and provider settings saved.")

    def _refresh_lit_settings_ui(self):
        """Sync all Literature settings UI widgets from the model (called by load_settings)."""
        self._refresh_lit_field_ui()
        # Provider vars
        for prov in DEFAULT_PROVIDER_ORDER:
            cfg = self._lit_provider_settings.get(prov, {})
            if prov in self._lit_prov_enabled_vars:
                self._lit_prov_enabled_vars[prov].set(cfg.get("enabled", True))
            if prov in self._lit_prov_priority_vars:
                self._lit_prov_priority_vars[prov].set(cfg.get("priority", 1))

    def _refresh_lit_field_ui(self):
        """Update every field checkbox BooleanVar to match _lit_retrieve/include_fields."""
        for term, v in self._lit_field_vars.items():
            ret = term in self._lit_retrieve_fields
            inc = term in self._lit_include_fields and ret
            v["retrieve"].set(ret)
            v["include"].set(inc)

    def _lit_enabled_providers(self) -> list:
        """Enabled providers sorted by ascending priority (1 = highest).

        Returns the list used as both enabled_providers and provider_order
        when calling fetch_taxon_entry.
        """
        return [
            p for p, cfg in sorted(
                self._lit_provider_settings.items(),
                key=lambda kv: kv[1].get("priority", 99),
            )
            if cfg.get("enabled", True)
        ]

    # ============================================================
    # RETRIEVAL NAME HELPER  (Phase 3.4)
    # ============================================================

    def _get_retrieval_targets(self, data_id: str) -> list:
        """Return [current_name, *historical_names] to use when querying external APIs.

        When a CARL block is loaded, the entity's declared name (with proper
        spacing) is used rather than the raw matrix label. Historical names from
        renames_from relationships are appended as fallbacks.
        """
        if self.carl_block:
            entity = next(
                (e for e in self.carl_block.entities if e.data_id == data_id), None
            )
            if entity:
                return self.carl_block.get_retrieval_targets(entity.entity_id)
        return [data_id]

    # ============================================================
    # SHARED TAXA ITERATION HELPER (used by all three info tabs)
    # ============================================================

    def _lit_cache_key(self, iid: str) -> str:
        """Translate a lit_tree iid to its cache lookup key.

        lit_tree iids are nom_tree iids (auto-generated); _nom_iid_meta maps
        them to the real cache_key.  Manual group-taxon rows use name==iid directly.
        """
        meta = self._nom_iid_meta.get(iid)
        if meta is not None:
            return meta["cache_key"]
        return iid

    def _iter_taxa_rows(self):
        """Yield (parent_iid, iid, label, cache_key, extra_tags) for all taxa.

        When the yielded parent_iid is None the row is a group header; the
        caller should insert it without a parent and store its iid for child rows.
        iids are always unique: when two entities share the same data_id, a
        disambiguation suffix is appended to the second entity's iid.
        """
        if self.carl_block and self.carl_block.entities:
            seen_iids: set = set()
            rows = self.carl_block.get_data_tab_rows()
            group_iids: dict[str, str] = {}
            for row in rows:
                if row["is_group_header"]:
                    grp_iid = f"__grp__{row['group_name']}"
                    seen_iids.add(grp_iid)
                    group_iids[row["group_name"]] = grp_iid
                    yield (None, grp_iid, row["label"].replace("_", " "), None, ())
                else:
                    cache_key = row["data_id"] or row["label"]
                    iid = cache_key
                    attempt = 0
                    while iid in seen_iids:
                        attempt += 1
                        iid = f"{cache_key}__{row['label']}__{attempt}"
                    seen_iids.add(iid)
                    parent = group_iids.get(row["group_name"], "") if row["group_name"] else ""
                    extra  = ("greyed",) if row["greyed"] else ()
                    yield (parent, iid, row["label"].replace("_", " "), cache_key, extra)
        # No CARL block — yield nothing; callers show an appropriate status message.

    # ============================================================

    def populate_literature_table(self):
        """Rebuild the Records treeview by mirroring the Derived View (nom_tree).

        nom_tree iids are reused as lit_tree iids — uniqueness is guaranteed and
        the structure is identical.  Cache lookups use _nom_iid_meta[iid]["cache_key"].
        No cache I/O here; caches are loaded at file-open or explicitly before calling.
        """
        for item in self.lit_tree.get_children():
            self.lit_tree.delete(item)

        self._lit_key_to_iids = {}

        if not self.dataset:
            self.lit_status_var.set("No file loaded.")
            return

        if not (self.carl_block and self.carl_block.entities):
            self.lit_status_var.set("No derived taxa — add CARL statements to populate.")
            return

        def _mirror(nom_parent, lit_parent):
            for nom_iid in self.nom_tree.get_children(nom_parent):
                meta = self._nom_iid_meta.get(nom_iid)
                if meta is None:
                    continue

                cache_key = meta["cache_key"]
                fetchable = meta["fetchable"]
                is_hdr    = meta["is_group_header"]

                nom_tags = set(self.nom_tree.item(nom_iid, "tags"))
                nom_text = self.nom_tree.item(nom_iid, "text")

                lit_tags = []
                if is_hdr:
                    lit_tags.append("group_header")
                elif "greyed" in nom_tags:
                    lit_tags.append("greyed")
                if "nov" in nom_tags:
                    lit_tags.append("nov")

                if fetchable:
                    res       = self._resources_cache.get(cache_key, {})
                    fetch_st  = res.get("status", "")
                    retrieved = res.get("retrieved", "")[:10]
                    comments  = res.get("comments", "")
                    tag = {"fetched": "fetched", "partial": "partial",
                           "error": "error"}.get(fetch_st, "pending")
                    lit_tags.insert(0, tag)

                    # ⚠ when DwC conflicts or profile conflicts exist
                    lit_entry = self._lit_cache.get(cache_key, {})
                    has_conflicts = (
                        bool(lit_entry.get("conflicts"))
                        or bool(res.get("profile_conflicts"))
                    )
                    if has_conflicts and fetch_st == "fetched":
                        fetch_st  = "fetched ⚠"
                        lit_tags.append("conflict")
                else:
                    fetch_st = retrieved = comments = ""

                self.lit_tree.insert(
                    lit_parent, tk.END, iid=nom_iid,
                    text=nom_text,
                    values=(fetch_st, retrieved, comments),
                    tags=tuple(lit_tags),
                    open=True,
                )
                self._lit_key_to_iids.setdefault(cache_key, []).append(nom_iid)
                _mirror(nom_iid, nom_iid)

        _mirror("", "")

        # Manual taxa added via "Add to Literature List" (not in nom_tree)
        dataset_names = {t.name for t in self.dataset.taxa}
        for name, entry in self._lit_cache.items():
            if entry.get("is_group_taxon") and name not in dataset_names:
                res       = self._resources_cache.get(name, {})
                fetch_st  = res.get("status", "")
                retrieved = res.get("retrieved", "")[:10]
                comments  = res.get("comments", "")
                tag = {"fetched": "fetched", "partial": "partial",
                       "error": "error"}.get(fetch_st, "group_taxon")
                self.lit_tree.insert(
                    "", tk.END, iid=name,
                    text=f"[G] {name.replace('_', ' ')}",
                    values=(fetch_st, retrieved, comments),
                    tags=(tag,),
                )
                self._lit_key_to_iids.setdefault(name, []).append(name)

        total   = len(dataset_names)
        fetched = sum(1 for n in dataset_names
                      if self._resources_cache.get(n, {}).get("status") == "fetched")
        self.lit_status_var.set(f"{fetched}/{total} taxa fetched.")

    def _update_lit_row(self, cache_key: str, res_entry: dict):
        """Update treeview row(s) for cache_key from a _resources_cache entry.

        Safe to call from a background thread via root.after().
        """
        status    = res_entry.get("status", "")
        retrieved = res_entry.get("retrieved", "")[:10]
        comments  = res_entry.get("comments", "")
        tag = {"fetched": "fetched", "partial": "partial",
               "error": "error"}.get(status, "pending")

        # ⚠ when DwC conflicts or profile conflicts exist
        lit_entry = self._lit_cache.get(cache_key, {})
        has_conflicts = (
            bool(lit_entry.get("conflicts"))
            or bool(res_entry.get("profile_conflicts"))
        )
        display_status = "fetched ⚠" if (has_conflicts and status == "fetched") else status

        for iid in self._lit_key_to_iids.get(cache_key, []):
            try:
                existing_tags = set(self.lit_tree.item(iid, "tags"))
                new_tags = [tag]
                if "group_header" in existing_tags:
                    new_tags.append("group_header")
                if "greyed" in existing_tags:
                    new_tags.append("greyed")
                if "nov" in existing_tags:
                    new_tags.append("nov")
                if has_conflicts and status == "fetched":
                    new_tags.append("conflict")
                self.lit_tree.item(iid,
                    values=(display_status, retrieved, comments),
                    tags=tuple(new_tags),
                )
            except tk.TclError:
                pass

    # ------------------------------------------------------------------
    # Information panel — consolidated fetch pipeline
    # ------------------------------------------------------------------

    def _info_fetch_all(self):
        """Fetch all unfetched fetchable taxa in the Information panel."""
        if not self.dataset:
            messagebox.showerror("Information", "Please load a NEXUS file first.")
            return
        if self._info_running:
            return
        seen: set = set()
        pending: list = []       # need full sandbox report
        dc_only:  list = []      # sandbox already fetched but DC missing/stale
        for meta in self._nom_iid_meta.values():
            if meta["fetchable"]:
                ck = meta["cache_key"]
                if ck not in seen:
                    seen.add(ck)
                    if self._resources_cache.get(ck, {}).get("status") != "fetched":
                        pending.append(ck)
                    elif not self._lit_cache.get(ck):
                        dc_only.append(ck)
        for name, entry in self._lit_cache.items():
            if entry.get("is_group_taxon") and name not in seen:
                seen.add(name)
                if self._resources_cache.get(name, {}).get("status") != "fetched":
                    pending.append(name)
        self._info_run_worker(pending, dc_only=dc_only)

    def _info_fetch_selected(self):
        """Fetch selected taxa in the Information panel."""
        if not self.dataset:
            messagebox.showerror("Information", "Please load a NEXUS file first.")
            return
        if self._info_running:
            return
        seen: set = set()
        selected: list = []
        for iid in self.lit_tree.selection():
            meta = self._nom_iid_meta.get(iid)
            if meta is not None:
                if not meta["fetchable"]:
                    continue
                ck = meta["cache_key"]
            else:
                ck = iid  # manual group taxon: iid == cache_key
            if ck not in seen:
                seen.add(ck)
                selected.append(ck)
        if not selected:
            messagebox.showinfo("Fetch Selected", "Select one or more fetchable taxa first.")
            return
        already_fetched = [n for n in selected
                           if self._resources_cache.get(n, {}).get("status") == "fetched"]
        has_manual_dc   = [n for n in selected
                           if self._lit_cache.get(n, {}).get("providers_queried") == ["manual"]]
        if already_fetched or has_manual_dc:
            parts = []
            if already_fetched:
                parts.append(f"{len(already_fetched)} taxon/taxa already have fetched reports")
            if has_manual_dc:
                parts.append(f"{len(has_manual_dc)} taxon/taxa have manually-entered DC fields "
                             "(these will not be altered by fetch)")
            msg = "; ".join(parts) + ".\n\nRe-fetch and overwrite existing reports?"
            if not messagebox.askyesno("Confirm Re-fetch", msg):
                return
        self._info_run_worker(selected, dc_only=[])

    def _info_run_worker(self, pending: list, dc_only: list = None):
        """Launch background thread to fetch reports for pending taxa.

        pending  — taxa needing a full sandbox report fetch
        dc_only  — taxa whose sandbox report is cached but DC fields are missing
        """
        if dc_only is None:
            dc_only = []
        if not pending and not dc_only:
            self.lit_status_var.set("All taxa already fetched.")
            return
        self._info_cancel   = False
        self._info_running  = True
        self.lit_cache_btn.config(state="disabled")
        self.lit_fetch_sel_btn.config(state="disabled")
        self.lit_cancel_btn.config(state="normal")

        providers       = self._lit_enabled_providers()
        # Fall back to all recommended fields if none are selected in Settings
        retrieve_fields = set(self._lit_retrieve_fields) or set(DEFAULT_FIELDS)

        def _fetch_dc(name, query_name):
            """Fetch Darwin Core fields for one taxon and save to _lit_cache.

            Uses the exact CARL-declared name — no silent name correction.
            """
            if self._lit_cache.get(name, {}).get("providers_queried") == ["manual"]:
                return
            def _dc_status(msg):
                self.root.after(0, lambda m=msg: self.lit_status_var.set(m))
            dc_entry = fetch_taxon_entry(
                query_name, providers, providers,
                retrieve_fields, status_fn=_dc_status,
            )
            self._lit_cache[name] = dc_entry
            if self.filepath:
                save_cache_atomic(self._lit_cache, self.filepath)

        def worker():
            total = len(pending)
            for i, name in enumerate(pending, 1):
                if self._info_cancel:
                    self.root.after(0, lambda: self.lit_status_var.set("Cancelled."))
                    break

                self.root.after(0, lambda n=name, ii=i, tt=total:
                    self.lit_status_var.set(f"Fetching {n} ({ii}/{tt})..."))

                query_name = self._get_retrieval_targets(name)[0]
                rank = ""
                if self.carl_block:
                    _ent = next(
                        (e for e in self.carl_block.entities if e.name == query_name),
                        None,
                    )
                    if _ent and _ent.rank and _ent.rank not in ("unknown", ""):
                        rank = _ent.rank.upper()
                res_entry = self._info_worker(name, query_name, i, total, rank,
                                              providers=providers)

                self._resources_cache[name] = res_entry
                if self.filepath:
                    save_resources_cache(self._resources_cache, self.filepath)

                _fetch_dc(name, query_name)

                self.root.after(0, lambda n=name, e=res_entry: self._update_lit_row(n, e))

                if i < total and not self._info_cancel:
                    time.sleep(INTER_TAXON_DELAY)

            # DC-only pass: taxa whose sandbox report was already cached
            for name in dc_only:
                if self._info_cancel:
                    break
                query_name = self._get_retrieval_targets(name)[0]
                self.root.after(0, lambda n=name:
                    self.lit_status_var.set(f"Fetching DC fields: {n}..."))
                _fetch_dc(name, query_name)

            if not self._info_cancel:
                fetched = sum(1 for e in self._resources_cache.values()
                              if isinstance(e, dict) and e.get("status") == "fetched")
                tot_all = len(self.dataset.taxa)
                self.root.after(0, lambda f=fetched, t=tot_all:
                    self.lit_status_var.set(f"Done. {f}/{t} taxa fetched."))

            self._info_running = False
            self.root.after(0, lambda: self.lit_cache_btn.config(state="normal"))
            self.root.after(0, lambda: self.lit_fetch_sel_btn.config(state="normal"))
            self.root.after(0, lambda: self.lit_cancel_btn.config(state="disabled"))

        threading.Thread(target=worker, daemon=True).start()

    def _info_worker(self, name: str, query_name: str, i: int, total: int,
                     rank: str, providers=None) -> dict:
        """Fetch external database records for one taxon; return a _resources_cache entry.

        Mirrors query_databases_sandbox.py main() — produces the same 9-section report.
        rank comes from the CARL block statement. providers is a set/list of enabled
        provider names; None means all providers enabled.
        """
        from datetime import datetime, timezone
        import traceback

        _enabled = set(providers) if providers is not None else set(DEFAULT_PROVIDER_ORDER)
        _GBIF_CHILDREN_LIMIT = 300

        def _status(msg):
            self.root.after(0, lambda m=msg: self.lit_status_var.set(m))

        bhl_key   = self._bhl_api_key_var.get()
        groq_key  = self._api_key_vars.get("groq", tk.StringVar()).get()
        groq_model = self.output_model_var.get() if self._llm_model_is_set(self.output_model_var.get()) else None
        existing_comments = self._resources_cache.get(name, {}).get("comments", "")
        lim = {key: var.get() for key, var in self._db_limit_vars.items()}

        try:
            # ── GBIF backbone ────────────────────────────────────────────────────
            _status(f"Resolving GBIF backbone: {query_name} ({i}/{total})...")
            gbif_info = resolve_gbif_backbone_rich(query_name, rank)
            if not gbif_info:
                return {
                    "retrieved": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "status": "error",
                    "report_text": f"Could not resolve '{query_name}' in GBIF backbone.",
                    "comments": existing_comments,
                    "error": "GBIF backbone resolution failed",
                }

            usage_key = gbif_info["usageKey"]
            gbif_rank = gbif_info.get("rank", rank)

            if "GBIF" in _enabled:
                _status(f"GBIF children: {query_name} ({i}/{total})...")
                gbif_children = fetch_gbif_children(usage_key, gbif_rank)
                _status(f"GBIF references + profiles: {query_name} ({i}/{total})...")
                gbif_refs     = fetch_gbif_references(usage_key)
                gbif_profiles = fetch_gbif_species_profiles(usage_key)
                _status(f"GBIF synonyms: {query_name} ({i}/{total})...")
                synonyms = fetch_gbif_synonyms(usage_key)
                _status(f"GBIF descriptions: {query_name} ({i}/{total})...")
                descriptions = fetch_gbif_descriptions(usage_key)
                _status(f"GBIF images: {query_name} ({i}/{total})...")
                images = fetch_gbif_image_urls(usage_key, max_results=lim["images"])
                _status(f"GBIF literature: {query_name} ({i}/{total})...")
                gbif_lit_pub_dicts = fetch_gbif_pub_dicts(usage_key, limit=lim["publications"])
                _status(f"GBIF specimens: {query_name} ({i}/{total})...")
                specimens = fetch_gbif_specimens(usage_key, max_results=lim["specimens"])
            else:
                gbif_children = []
                gbif_refs = []
                gbif_profiles = {}
                synonyms = []
                descriptions = []
                images = []
                gbif_lit_pub_dicts = []
                specimens = []

            if "CoL" in _enabled:
                _status(f"Catalogue of Life: {query_name} ({i}/{total})...")
                _, col_synonyms, col_summary, col_pub_dicts = get_col_full(
                    query_name, syn_limit=10_000)
            else:
                col_synonyms  = []
                col_summary   = ""
                col_pub_dicts = []
            col_children = []  # CoL has no children endpoint; GBIF/WoRMS cover daughter taxa

            if "NCBI" in _enabled:
                _status(f"NCBI: {query_name} ({i}/{total})...")
                resolved_taxid, ncbi_summary = get_ncbi_records(
                    gbif_info.get("taxid"), query_name, acc_limit=lim["ncbi_acc"])
                if resolved_taxid and not gbif_info.get("taxid"):
                    gbif_info["taxid"] = resolved_taxid
            else:
                ncbi_summary = ""

            if "ITIS" in _enabled:
                _status(f"ITIS: {query_name} ({i}/{total})...")
                resolved_tsn, itis_summary = fetch_itis_summary(gbif_info.get("tsn"), query_name)
                if resolved_tsn and not gbif_info.get("tsn"):
                    gbif_info["tsn"] = resolved_tsn
                _status(f"ITIS synonyms: {query_name} ({i}/{total})...")
                itis_synonyms = fetch_itis_synonyms(resolved_tsn or gbif_info.get("tsn"))
            else:
                itis_summary  = ""
                itis_synonyms = []

            if "ZooBank" in _enabled:
                _status(f"ZooBank: {query_name} ({i}/{total})...")
                resolved_lsid, zoobank_summary, zoobank_pub_dicts = get_zoobank_full(
                    query_name, max_acts=lim["zoobank_acts"])
                if resolved_lsid and not gbif_info.get("lsid"):
                    gbif_info["lsid"] = resolved_lsid
            else:
                zoobank_summary   = ""
                zoobank_pub_dicts = []

            if "WoRMS" in _enabled:
                _status(f"WoRMS: {query_name} ({i}/{total})...")
                worms_info = fetch_worms_summary(query_name)
                if worms_info.get("lsid") and not gbif_info.get("lsid"):
                    gbif_info["lsid"] = worms_info["lsid"]
                aphia_id = worms_info.get("aphia_id")
                if aphia_id:
                    _status(f"WoRMS synonyms: {query_name} ({i}/{total})...")
                    worms_synonyms = fetch_worms_synonyms(aphia_id)
                    _status(f"WoRMS children: {query_name} ({i}/{total})...")
                    worms_children = fetch_worms_children(aphia_id)
                else:
                    worms_synonyms = []
                    worms_children = []
            else:
                worms_info     = {}
                worms_synonyms = []
                worms_children = []

            if "WSC" in _enabled:
                _status(f"WSC: {query_name} ({i}/{total})...")
                wsc_data = fetch_wsc_profile(query_name)
            else:
                wsc_data = {}

            if "POWO" in _enabled:
                _status(f"POWO: {query_name} ({i}/{total})...")
                powo_data = fetch_powo_profile(query_name)
            else:
                powo_data = {}

            if "BacDive" in _enabled:
                _status(f"BacDive: {query_name} ({i}/{total})...")
                bacdive_data = fetch_bacdive_profile(query_name)
            else:
                bacdive_data = {}

            if "Wikipedia" in _enabled:
                _status(f"Wikipedia: {query_name} ({i}/{total})...")
                wiki_report = fetch_wikipedia_report(query_name)
                _status(f"Wikipedia LLM summary: {query_name} ({i}/{total})...")
                if groq_model:
                    wiki_description, wiki_summary = summarize_wikipedia_llm(
                        wiki_report, query_name, api_key=groq_key, model=groq_model)
                else:
                    wiki_description, wiki_summary = "", ""
            else:
                wiki_report      = {}
                wiki_description = ""
                wiki_summary     = ""

            if "CrossRef" in _enabled:
                _status(f"CrossRef: {query_name} ({i}/{total})...")
                crossref_pub_dicts = get_crossref_pub_dicts(query_name, max_results=lim["publications"])
            else:
                crossref_pub_dicts = []

            if "BHL" in _enabled:
                _status(f"BHL: {query_name} ({i}/{total})...")
                bhl_pubs, bhl_pages = fetch_bhl_enriched(
                    query_name, api_key=bhl_key,
                    max_titles=lim["bhl_titles"], max_pages=lim["bhl_pages"])
                page_ids = [pg["page_id"] for pg in bhl_pages if pg.get("page_id")]
                if page_ids:
                    _status(f"BHL articles ({len(page_ids)} pages): {query_name} ({i}/{total})...")
                bhl_pub_dicts = get_bhl_pub_dicts(page_ids, api_key=bhl_key)
            else:
                bhl_pubs      = []
                bhl_pages     = []
                bhl_pub_dicts = []

            if "Plazi" in _enabled:
                _status(f"Plazi treatments: {query_name} ({i}/{total})...")
                plazi_descs, plazi_imgs, plazi_specimens = get_plazi_all(
                    query_name, uuid_limit=lim["plazi_uuid"], spec_limit=lim["specimens"])
                _status(f"Plazi keys: {query_name} ({i}/{total})...")
                _, plazi_key_pub_dicts = get_plazi_keys_full(
                    query_name, key_limit=lim["plazi_keys"])
            else:
                plazi_descs      = []
                plazi_imgs       = []
                plazi_specimens  = []
                plazi_key_pub_dicts = []

            # ── Classify Wikipedia sections ──────────────────────────────────────
            _DESC_HEADINGS = frozenset((
                "description", "descriptions", "morphology", "appearance",
                "anatomy", "identification", "diagnostic characters", "characteristics",
            ))
            wiki_desc_secs  = []
            wiki_other_secs = []
            if wiki_report.get("found"):
                for sec in wiki_report.get("sections", []):
                    if sec["heading"].lower() in _DESC_HEADINGS:
                        wiki_desc_secs.append(sec)
                    else:
                        wiki_other_secs.append(sec)

            # ── Unified publications pool ────────────────────────────────────────
            all_pubs = []
            for r in gbif_refs:
                all_pubs.append({
                    "doi": r.get("doi", ""), "title": None, "csl": None,
                    "raw_citation": r["citation"], "sources": ["GBIF"],
                })
            all_pubs.extend(col_pub_dicts)
            all_pubs.extend(zoobank_pub_dicts)
            all_pubs.extend(worms_info.get("pub_dicts", []))
            all_pubs.extend(bacdive_data.get("pub_dicts", []))
            all_pubs.extend(crossref_pub_dicts)
            all_pubs.extend(gbif_lit_pub_dicts)
            all_pubs.extend(bhl_pub_dicts)
            all_pubs.extend(plazi_key_pub_dicts)

            _status(f"Resolving publications: {query_name} ({i}/{total})...")
            formatted_pubs, background_pubs = resolve_publications(all_pubs)

            # WSC citation is already a complete reference — insert directly,
            # bypassing CrossRef resolution entirely.
            if wsc_data.get("reference"):
                yr_m = re.search(r'\((\d{4})\)', wsc_data["reference"])
                formatted_pubs.append({
                    "citation":  wsc_data["reference"],
                    "doi":       wsc_data.get("reference_doi") or "",
                    "sources":   ["WSC"],
                    "plazi_url": "",
                    "year":      int(yr_m.group(1)) if yr_m else None,
                })
                formatted_pubs.sort(
                    key=lambda p: (p.get("year") or 9999, p.get("citation", ""))
                )

        except Exception as exc:
            return {
                "retrieved": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "status": "error",
                "report_text": f"Error fetching '{query_name}': {exc}\n\n{traceback.format_exc()}",
                "comments": existing_comments,
                "error": str(exc),
            }

        # ── Assemble 9-section report (mirrors sandbox main()) ────────────────
        out = []

        def _w(text=""):
            out.append(text)

        _w(f"TAXONOMIC PROFILE: {query_name.upper()} ({rank.upper()})")
        _w("=" * 65)
        _w()

        # === 1. TAXONOMIC PROFILE ===
        _w("=== 1. TAXONOMIC PROFILE ===")
        _w()
        _w(f"  Accepted name:  {gbif_info['scientificName']}")
        if gbif_info.get("hierarchy"):
            _w(f"  Hierarchy:      {gbif_info['hierarchy']}")
        if gbif_info.get("authorship"):
            _w(f"  Authorship:     {gbif_info['authorship']}")
        if gbif_info.get("parent"):
            _w(f"  Parent taxon:   {gbif_info['parent']}")
        if gbif_info.get("numDescendants") is not None:
            _w(f"  Descendants:    {gbif_info['numDescendants']}")
        _w(f"  GBIF usageKey:  {gbif_info['usageKey']}")
        _w(f"  LSID:           {gbif_info.get('lsid') or 'N/A'}")
        _w(f"  ITIS TSN:       {gbif_info.get('tsn')  or 'N/A'}")
        _w(f"  NCBI TaxID:     {gbif_info.get('taxid') or 'N/A'}")
        if wsc_data.get("lsid"):
            _w(f"  WSC LSID:       {wsc_data['lsid']}")
        if powo_data.get("ipni_lsid"):
            _w(f"  IPNI LSID:      {powo_data['ipni_lsid']}")
        if gbif_info.get("publishedIn"):
            _w(f"  Published in:   {gbif_info['publishedIn']}")
        if powo_data.get("reference"):
            _w(f"  Published in (POWO): {powo_data['reference']}")
        _w()

        _profile_conflicts = []
        _gbif_auth = (gbif_info.get("authorship") or "").strip()
        _gbif_rank = (gbif_info.get("rank") or "").strip().lower()

        if worms_info:
            _w("[WoRMS]")
            _w(f"  AphiaID:    {worms_info['aphia_id']}")
            _w(f"  LSID:       {worms_info['lsid'] or 'N/A'}")
            _w(f"  Status:     {worms_info['status'] or 'N/A'}")
            if worms_info.get("authority"):
                _w(f"  Authorship: {worms_info['authority']}")
            if worms_info.get("orig_ref"):
                _w(f"  Orig. ref:  {worms_info['orig_ref']}")
            _w()

            _worms_auth = (worms_info.get("authority") or "").strip()
            if _gbif_auth and _worms_auth and _gbif_auth != _worms_auth:
                _profile_conflicts.append(
                    f"  authorship:  GBIF → {_gbif_auth!r}  |  WoRMS → {_worms_auth!r}")

            _worms_rank = (worms_info.get("rank") or "").strip().lower()
            if _gbif_rank and _worms_rank and _gbif_rank != _worms_rank:
                _profile_conflicts.append(
                    f"  rank:        GBIF → {_gbif_rank!r}  |  WoRMS → {_worms_rank!r}")

        if wsc_data:
            _w("[WSC]")
            if wsc_data.get("status"):
                _w(f"  Status:    {wsc_data['status']}")
            if wsc_data.get("reference"):
                _w(f"  Orig. ref: {wsc_data['reference']}")
            _w()

            _wsc_auth = (wsc_data.get("author") or "").strip()
            if _gbif_auth and _wsc_auth and _gbif_auth != _wsc_auth:
                _profile_conflicts.append(
                    f"  authorship:  GBIF → {_gbif_auth!r}  |  WSC → {_wsc_auth!r}")

        if powo_data:
            _w("[POWO]")
            if powo_data.get("status"):
                _w(f"  Status:   {powo_data['status']}")
            if powo_data.get("taxonRemarks"):
                _w(f"  Remarks:  {powo_data['taxonRemarks']}")
            _w()

            _powo_auth = (powo_data.get("authorship") or "").strip()
            if _gbif_auth and _powo_auth and _gbif_auth != _powo_auth:
                _profile_conflicts.append(
                    f"  authorship:  GBIF → {_gbif_auth!r}  |  POWO → {_powo_auth!r}")
            _gbif_parent = (gbif_info.get("parent") or "").strip()
            _powo_parent = (powo_data.get("parent") or "").strip()
            if _gbif_parent and _powo_parent and _gbif_parent != _powo_parent:
                _profile_conflicts.append(
                    f"  parent:      GBIF → {_gbif_parent!r}  |  POWO → {_powo_parent!r}")

        for _bd_strain in (bacdive_data.get("type_strains") or []):
            _strain_label = _bd_strain.get("strain_designation") or str(_bd_strain.get("bacdive_id", ""))
            _w(f"[BacDive — type strain {_strain_label}]")
            _w(f"  BacDive ID:  {_bd_strain['bacdive_id']}")
            if _bd_strain.get("culture_collection_nos"):
                _w(f"  Collections: {_bd_strain['culture_collection_nos']}")
            if _bd_strain.get("gram_stain"):
                _w(f"  Gram:        {_bd_strain['gram_stain']}")
            if _bd_strain.get("cell_shape"):
                _w(f"  Cell shape:  {_bd_strain['cell_shape']}")
            if _bd_strain.get("motility"):
                _w(f"  Motility:    {_bd_strain['motility']}")
            if _bd_strain.get("oxygen_tolerance"):
                _w(f"  O₂:          {_bd_strain['oxygen_tolerance']}")
            if _bd_strain.get("temp_range"):
                _w(f"  Temp:        {_bd_strain['temp_range']}")
            if _bd_strain.get("biosafety_level"):
                bsl_line = f"  BSL:         {_bd_strain['biosafety_level']}"
                if _bd_strain.get("pathogenicity_human"):
                    bsl_line += f"  (human pathogen: {_bd_strain['pathogenicity_human']})"
                _w(bsl_line)
            if _bd_strain.get("description"):
                _w(f"  Description: {_bd_strain['description']}")
            _w()

        if _profile_conflicts:
            _w("[Profile conflicts]")
            for _c in _profile_conflicts:
                _w(_c)
            _w()

        # Merge daughter taxa across GBIF, CoL, WoRMS — deduplicate by canonical key
        _merged_children: dict = {}
        for _c in gbif_children:
            _ck = _canonical_key(_c["name"]) or _c["name"].lower()[:40]
            if _ck not in _merged_children:
                _merged_children[_ck] = {
                    "name":      _c["name"],
                    "authorship": _c.get("authorship", ""),
                    "rank":      _c.get("rank", ""),
                    "sources":   ["GBIF"],
                    "conflict":  False,
                }
            else:
                if "GBIF" not in _merged_children[_ck]["sources"]:
                    _merged_children[_ck]["sources"].append("GBIF")

        for _src_label, _src_list in [("CoL", col_children), ("WoRMS", worms_children), ("POWO", powo_data.get("children") or [])]:
            for _c in _src_list:
                _ck = _canonical_key(_c["name"]) or _c["name"].lower()[:40]
                if _ck not in _merged_children:
                    _merged_children[_ck] = {
                        "name":      _c["name"],
                        "authorship": _c.get("authorship", ""),
                        "rank":      _c.get("rank", ""),
                        "sources":   [_src_label],
                        "conflict":  False,
                    }
                else:
                    if _src_label not in _merged_children[_ck]["sources"]:
                        _merged_children[_ck]["sources"].append(_src_label)
                    _existing_auth = _auth_key(_name_authorship(_merged_children[_ck]["name"]))
                    _new_auth      = _auth_key(_c.get("authorship", "") or _name_authorship(_c["name"]))
                    if _existing_auth and _new_auth and _existing_auth != _new_auth:
                        _ex_yr  = _auth_year(_name_authorship(_merged_children[_ck]["name"]))
                        _new_yr = _auth_year(_c.get("authorship", "") or _name_authorship(_c["name"]))
                        if _ex_yr and _new_yr and _ex_yr != _new_yr:
                            _merged_children[_ck]["conflict"] = True

        if _merged_children:
            _child_list = sorted(_merged_children.values(), key=lambda e: e["name"])
            _ranks_seen = list(dict.fromkeys(
                e["rank"] for e in _child_list if e["rank"]))
            if len(_ranks_seen) == 1:
                _rank_label = _RANK_PLURAL.get(_ranks_seen[0], _ranks_seen[0].lower() + "s")
            else:
                _rank_label = "taxa"
            _truncated = len(gbif_children) >= _GBIF_CHILDREN_LIMIT
            _count_str = f"{len(_child_list)}+" if _truncated else str(len(_child_list))
            _w(f"[Daughter taxa — {_count_str} {_rank_label}]")
            for _c in _child_list:
                _auth = _c["authorship"] or ""
                _line = f"  {_c['name']}"
                if _auth:
                    _line += f" {_auth}"
                _src = ", ".join(_c["sources"])
                if _c["conflict"]:
                    _src += " — authorship conflict"
                _line += f"  [{_src}]"
                _w(_line)
            _w()

        if gbif_profiles.get("habitats") or gbif_profiles.get("extinct") is not None:
            _w("[GBIF Species Profiles]")
            if gbif_profiles["habitats"]:
                _w(f"  Habitat:  {', '.join(gbif_profiles['habitats'])}")
            if gbif_profiles["extinct"] is not None:
                _w(f"  Extinct:  {'Yes' if gbif_profiles['extinct'] else 'No'}")
            if gbif_profiles.get("sources"):
                _w(f"  Sources:  {'; '.join(gbif_profiles['sources'])}")
            _w()

        _w("[ITIS]")
        for line in itis_summary.splitlines():
            _w(f"  {line}")
        _w()

        _w("[Catalogue of Life]")
        for line in col_summary.splitlines():
            _w(f"  {line}")
        _w()

        # === 2. SYNONYMS ===
        _w("=== 2. SYNONYMS ===")
        _w()
        merged_syns: dict = {}

        for s in synonyms:
            key = _canonical_key(s["scientificName"]) or s["scientificName"].lower()[:40]
            if key not in merged_syns:
                merged_syns[key] = {
                    "name":              s["scientificName"],
                    "taxonomicStatus":   s["taxonomicStatus"],
                    "originalNameUsage": s["originalNameUsage"],
                    "col_status":        "",
                    "sources":           ["GBIF"],
                    "conflict":          False,
                }
            else:
                if "GBIF" not in merged_syns[key]["sources"]:
                    merged_syns[key]["sources"].append("GBIF")

        for s in col_synonyms:
            key = _canonical_key(s["name"]) or s["name"].lower()[:40]
            if key not in merged_syns:
                merged_syns[key] = {
                    "name":              s["name"],
                    "taxonomicStatus":   "",
                    "originalNameUsage": "",
                    "col_status":        s["status"],
                    "sources":           ["CoL"],
                    "conflict":          False,
                }
            else:
                if "CoL" not in merged_syns[key]["sources"]:
                    merged_syns[key]["sources"].append("CoL")
                if not merged_syns[key]["col_status"]:
                    merged_syns[key]["col_status"] = s["status"]
                gbif_auth = _name_authorship(merged_syns[key]["name"])
                col_auth  = _name_authorship(s["name"])
                gbif_ak   = _auth_key(gbif_auth)
                col_ak    = _auth_key(col_auth)
                if not gbif_ak and col_ak:
                    merged_syns[key]["name"] = s["name"]
                elif gbif_ak and col_ak and gbif_ak != col_ak:
                    gbif_yr = _auth_year(gbif_auth)
                    col_yr  = _auth_year(col_auth)
                    years_agree = (not gbif_yr or not col_yr or gbif_yr == col_yr)
                    if not years_agree:
                        merged_syns[key]["name"] = (
                            f"{merged_syns[key]['name']} / {s['name']}")
                        merged_syns[key]["conflict"] = True

        for _src_label, _src_list in [("WoRMS", worms_synonyms), ("ITIS", itis_synonyms), ("POWO", powo_data.get("synonyms") or [])]:
            for s in _src_list:
                _sname = s["name"]
                _sauth = s.get("authorship", "")
                key = _canonical_key(_sname) or _sname.lower()[:40]
                if key not in merged_syns:
                    merged_syns[key] = {
                        "name":              _sname if not _sauth else f"{_sname} {_sauth}".strip(),
                        "taxonomicStatus":   s.get("status", ""),
                        "originalNameUsage": "",
                        "col_status":        "",
                        "sources":           [_src_label],
                        "conflict":          False,
                    }
                else:
                    if _src_label not in merged_syns[key]["sources"]:
                        merged_syns[key]["sources"].append(_src_label)
                    if _sauth:
                        _existing_ak = _auth_key(_name_authorship(merged_syns[key]["name"]))
                        _new_ak      = _auth_key(_sauth)
                        if not _existing_ak:
                            if not merged_syns[key]["name"].endswith(_sauth):
                                merged_syns[key]["name"] = f"{merged_syns[key]['name']} {_sauth}".strip()
                        elif _new_ak and _existing_ak != _new_ak:
                            _ex_yr  = _auth_year(_name_authorship(merged_syns[key]["name"]))
                            _new_yr = _auth_year(_sauth)
                            if _ex_yr and _new_yr and _ex_yr != _new_yr:
                                merged_syns[key]["name"] = (
                                    f"{merged_syns[key]['name']} / {_sname} {_sauth}".strip())
                                merged_syns[key]["conflict"] = True

        merged_list = sorted(merged_syns.values(), key=lambda e: e["name"])
        _w(f"[Synonyms — {len(merged_list)} entries]")
        if merged_list:
            for e in merged_list:
                line = f"  {e['name']}"
                status = e["taxonomicStatus"] or e["col_status"]
                if status:
                    line += f"  [{status}]"
                if e["originalNameUsage"]:
                    line += f"  (basionym: {e['originalNameUsage']})"
                src_label = ", ".join(e["sources"])
                if e.get("conflict"):
                    src_label += " — conflict"
                line += f"  [{src_label}]"
                _w(line)
        else:
            _w("  None on record.")
        _w()

        # === 3. NOMENCLATURAL ACTS ===
        _w("=== 3. NOMENCLATURAL ACTS ===")
        _w()
        _w("[ZooBank]")
        for line in zoobank_summary.splitlines():
            _w(f"  {line}")
        _w()

        # === 4. SPECIMENS ===
        _w("=== 4. SPECIMENS ===")
        _w()

        _w(f"[GBIF Preserved Specimens — {len(specimens)}]")
        if specimens:
            def _gbif_row(sp):
                inst = sp["institutionCode"] or "?"
                coll = sp["collectionCode"] or ""
                loc  = sp["country"] or ""
                if sp["locality"]:
                    loc += (", " if loc else "") + sp["locality"]
                return [
                    sp["typeStatus"] or "—",
                    f"{inst}:{coll}" if coll else inst,
                    sp["catalogNumber"] or "?",
                    loc or "—",
                    sp["eventDate"] or "—",
                    sp["recordedBy"] or "",
                    sp["preparations"] or "",
                ]
            _gbif_spec_headers = [
                "Type", "Institution", "Catalog No.",
                "Location", "Date", "Collector", "Preps",
            ]
            _gbif_spec_maxw = [None, None, None, 40, None, 30, 20]
            _w(_tabulate(_gbif_spec_headers, [_gbif_row(sp) for sp in specimens],
                         max_widths=_gbif_spec_maxw))
        else:
            _w("  None.")
        _w()

        _w(f"[Plazi Specimens (from treatment XML) — {len(plazi_specimens)}]")
        if plazi_specimens:
            def _plazi_row(sp):
                country  = sp.get("country", "") or ""
                locality = sp.get("locality", "") or ""
                loc = (f"{country}, {locality}" if country and locality
                       else country or locality or "—")
                return [
                    sp.get("typeStatus", "") or "—",
                    sp.get("institutionCode", "") or "?",
                    sp.get("catalogNumber", "") or "?",
                    loc,
                    sp.get("taxon", "") or "",
                ]
            _plazi_spec_headers = ["Type", "Institution", "Catalog No.", "Location", "Taxon"]
            _w(_tabulate(_plazi_spec_headers, [_plazi_row(sp) for sp in plazi_specimens]))
        else:
            _w("  None.")
        _w()

        # === 5. ACCESSION NUMBERS ===
        _w("=== 5. ACCESSION NUMBERS ===")
        _w()
        _w("[NCBI]")
        for line in ncbi_summary.splitlines():
            _w(f"  {line}")
        _w()

        _bd_16s   = [acc for s in (bacdive_data.get("type_strains") or []) for acc in s.get("sequences_16s", [])]
        _bd_genome = [acc for s in (bacdive_data.get("type_strains") or []) for acc in s.get("sequences_genome", [])]
        if _bd_16s or _bd_genome:
            _w("[BacDive — Sequences]")
            if _bd_16s:
                _w("  16S rRNA:")
                for acc in _bd_16s:
                    length_str = f"  ({acc['length']} bp)" if acc.get("length") else ""
                    _w(f"    {acc['accession']}{length_str}")
            if _bd_genome:
                _w("  Genome:")
                for acc in _bd_genome:
                    _w(f"    {acc['accession']}")
            _w()

        # === 6. DESCRIPTIONS (suppressed when §8 has formatted publications) ===
        if not formatted_pubs:
            _w("=== 6. DESCRIPTIONS ===")
            _w()
            _w(f"[GBIF — {len(descriptions)} descriptions]")
            if descriptions:
                for d in descriptions:
                    _w(d)
                    _w()
            else:
                _w("  None.")
                _w()
            _w(f"[Plazi Treatments — {len(plazi_descs)} entries]")
            if plazi_descs:
                for entry in plazi_descs:
                    _w(f"  [{entry['taxon'] or entry['uuid']}]")
                    _w("  " + entry["text"])
                    _w()
            else:
                _w("  None.")
                _w()

        # === 7. IMAGES ===
        _w("=== 7. IMAGES ===")
        _w()
        _w(f"[GBIF — {len(images)} URLs]")
        for url in images:
            _w(f"  {url}")
        if not images:
            _w("  None.")
        _w()

        _w(f"[Plazi — {len(plazi_imgs)} URLs]")
        for url in plazi_imgs:
            _w(f"  {url}")
        if not plazi_imgs:
            _w("  None.")
        _w()

        # === 8. PUBLICATIONS ===
        _w("=== 8. PUBLICATIONS ===")
        _w()

        _w(f"[Publications — {len(formatted_pubs)} entries]")
        if formatted_pubs:
            for idx, p in enumerate(formatted_pubs, 1):
                src_tag = f"  [{', '.join(p['sources'])}]" if p["sources"] else ""
                _w(f"  [{idx}] {p['citation']}{src_tag}")
                if p["doi"]:
                    _w(f"       https://doi.org/{p['doi']}")
                if p.get("plazi_url"):
                    _w(f"       {p['plazi_url']}")
        else:
            _w("  None.")
        _w()

        _w(f"[GBIF species references by type — {len(gbif_refs)} records]")
        if gbif_refs:
            current_type = None
            for r in gbif_refs:
                if r["type"] != current_type:
                    current_type = r["type"]
                    _w(f"  [{current_type or 'uncategorised'}]")
                line = f"    {r['citation']}"
                if r["source"]:
                    line += f"  [{r['source']}]"
                _w(line)
        else:
            _w("  None.")
        _w()

        _w(f"[BHL — {len(bhl_pubs)} titles]")
        if bhl_pubs:
            for pub in bhl_pubs:
                title_str = pub["title"] or "(title unavailable)"
                _w(f"  {title_str}")
                yr_s = pub.get("start_year") or pub.get("year") or ""
                yr_e = pub.get("end_year") or ""
                date_range = f"{yr_s}–{yr_e}" if yr_s and yr_e else yr_s or yr_e
                meta_parts = [p for p in [pub.get("place"), date_range] if p]
                if meta_parts:
                    _w(f"    {'. '.join(meta_parts)}")
                if pub.get("author_str"):
                    _w(f"    {pub['author_str']}")
                bib_url = pub.get("bibliography_url") or pub.get("url")
                if bib_url:
                    _w(f"    {bib_url}")
                if pub.get("wikidata_qid"):
                    _w(f"    https://www.wikidata.org/wiki/{pub['wikidata_qid']}")
        else:
            _w("  None.")
        if bhl_pages:
            _w(f"  Pages ({len(bhl_pages)}):")
            for pg in bhl_pages:
                line = f"    {pg['page_url'] or '(no URL)'}"
                if pg["year"]:
                    line += f"  [{pg['year']}]"
                _w(line)
        _w()

        # === 9. WIKIPEDIA SUMMARY (LLM-generated) ===
        _w("=== 9. WIKIPEDIA SUMMARY ===")
        if wiki_report.get("found"):
            _w(f"Source: {wiki_report['title']}  |  {wiki_report.get('url', '')}")
            if wiki_report.get("thumbnail"):
                _w(f"Thumbnail: {wiki_report['thumbnail']}")
            _w(f"(Generated by {groq_model})")
            _w()
            if wiki_description:
                _w("DESCRIPTION:")
                _w(wiki_description)
                _w()
            if wiki_summary:
                _w("SUMMARY:")
                _w(wiki_summary)
                _w()
            if not wiki_description and not wiki_summary:
                _w("[Summary could not be generated]")
                _w()
        else:
            _w("Not found on Wikipedia.")
            _w()

        report_text = "\n".join(out)

        # ── Build structured DwC fields from all fetched sources ─────────────
        def _first(*vals):
            for v in vals:
                s = str(v).strip() if v else ""
                if s:
                    return s
            return ""

        _king = _first(gbif_info.get("kingdom"), worms_info.get("kingdom"))
        _nom_code = {
            "animalia": "ICZN", "plantae": "ICN", "fungi": "ICN",
            "bacteria": "ICNP", "archaea": "ICNP", "viruses": "ICTV",
        }.get(_king.lower(), "")
        if not _nom_code and powo_data:
            _nom_code = "ICN"

        import re as _re
        _yr_m = _re.search(r'\b(1[6-9]\d{2}|20\d{2})\b',
                           gbif_info.get("authorship") or "")
        _pub_year = _first(_yr_m.group(1) if _yr_m else "",
                           powo_data.get("namePublishedInYear"))

        _lsid_val = gbif_info.get("lsid") or ""
        _sci_name_id = _first(
            _lsid_val if "zoobank" in _lsid_val.lower() else None,
            wsc_data.get("lsid"),
            worms_info.get("lsid"),
            _lsid_val,
            powo_data.get("ipni_lsid"),
        )

        _tax_status = _first(
            gbif_info.get("taxonomicStatus"),
            worms_info.get("status"),
            powo_data.get("status"),
        )
        _nom_status = _first(
            gbif_info.get("nomenclaturalStatus"),
            worms_info.get("nomenclaturalStatus"),
        )

        _accepted = (gbif_info.get("acceptedName") or "").strip()
        _accepted_usage = _accepted if _accepted else gbif_info.get("scientificName", "")

        _dwc_raw = {
            "taxonID":                  str(gbif_info.get("usageKey", "")),
            "scientificName":           gbif_info.get("scientificName", ""),
            "scientificNameAuthorship": _first(gbif_info.get("authorship"),
                                               worms_info.get("authority")),
            "taxonRank":                gbif_info.get("rank", "").lower(),
            "kingdom":                  _king,
            "phylum":                   _first(gbif_info.get("phylum"),
                                               worms_info.get("phylum")),
            "class":                    _first(gbif_info.get("class_name"),
                                               worms_info.get("class")),
            "order":                    _first(gbif_info.get("order"),
                                               worms_info.get("order")),
            "family":                   _first(gbif_info.get("family"),
                                               worms_info.get("family")),
            "genus":                    _first(gbif_info.get("genus"),
                                               worms_info.get("genus")),
            "taxonomicStatus":          _tax_status,
            "nomenclaturalCode":        _nom_code,
            "nomenclaturalStatus":      _nom_status,
            "namePublishedIn":          _first(gbif_info.get("publishedIn"),
                                               powo_data.get("reference"),
                                               worms_info.get("orig_ref")),
            "namePublishedInYear":      _pub_year,
            "parentNameUsage":          _first(gbif_info.get("parent"),
                                               powo_data.get("parent")),
            "acceptedNameUsage":        _accepted_usage,
            "scientificNameID":         _sci_name_id,
            "higherClassification":     gbif_info.get("hierarchy", "").replace(":", " | "),
        }
        dwc_fields = {k: v for k, v in _dwc_raw.items() if v}

        return {
            "retrieved":        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status":           "fetched",
            "report_text":      report_text,
            "comments":         existing_comments,
            "error":            "",
            "profile_conflicts": _profile_conflicts,
            "dwc_fields":       dwc_fields,
        }

    def _info_cancel_fetch(self):
        self._info_cancel = True
        self.lit_status_var.set("Cancelling after current taxon...")

    def _info_clear_cache(self):
        """Clear all cached reports and Darwin Core fields for this dataset."""
        if not self.dataset or not self.filepath:
            return
        if not messagebox.askyesno(
                "Clear All",
                "Delete all cached reports and Darwin Core fields "
                "for this dataset?"):
            return
        self._resources_cache = {}
        self._lit_cache = {}
        save_resources_cache(self._resources_cache, self.filepath)
        save_cache_atomic(self._lit_cache, self.filepath)
        self.populate_literature_table()

    def _info_clear_selected(self):
        """Clear cached report + Darwin Core fields for the selected taxa."""
        if not self.dataset or not self.filepath:
            return
        seen, selected = set(), []
        for iid in self.lit_tree.selection():
            meta = self._nom_iid_meta.get(iid)
            if meta is not None:
                if not meta["fetchable"]:
                    continue
                ck = meta["cache_key"]
            else:
                ck = iid  # manual group taxon: iid == cache_key
            if ck not in seen:
                seen.add(ck)
                selected.append(ck)
        if not selected:
            messagebox.showinfo("Clear Selected", "Select one or more taxa first.")
            return
        if not messagebox.askyesno(
                "Clear Selected",
                f"Delete cached reports and Darwin Core fields for "
                f"{len(selected)} selected taxon/taxa?"):
            return
        for ck in selected:
            self._resources_cache.pop(ck, None)
            self._lit_cache.pop(ck, None)
        save_resources_cache(self._resources_cache, self.filepath)
        save_cache_atomic(self._lit_cache, self.filepath)
        self.populate_literature_table()

    def _info_export_txt(self):
        """Export the selected taxon's report to a .txt file."""
        sel = [s for s in self.lit_tree.selection()
               if self._nom_iid_meta.get(s, {}).get("fetchable", s not in self._nom_iid_meta)]
        if not sel:
            messagebox.showinfo("Export", "Select a taxon first.")
            return
        ck     = self._lit_cache_key(sel[0])
        report = self._resources_cache.get(ck, {}).get("report_text", "")
        if not report:
            messagebox.showinfo("Export", "No report available for the selected taxon.")
            return
        save_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialfile=f"{ck}.txt",
            title="Export Report",
            **self._wd_kwargs()
        )
        if not save_path:
            return
        with open(save_path, "w", encoding="utf-8") as f:
            f.write(report)
        self.lit_status_var.set(f"Exported: {save_path}")

    def clear_literature_cache(self):
        if not self.dataset or not self.filepath:
            return
        fixed_names = [n for n, e in self._lit_cache.items() if e.get("fixed")]
        msg = "Delete all cached literature for this dataset?"
        if fixed_names:
            msg += f"\n({len(fixed_names)} Fixed taxon/taxa will be preserved.)"
        if not messagebox.askyesno("Clear Cache", msg):
            return
        self._lit_cache = {n: e for n, e in self._lit_cache.items() if e.get("fixed")}
        save_cache_atomic(self._lit_cache, self.filepath)
        self.populate_literature_table()

    def _on_lit_select(self, event=None):
        """Track the selected taxon and display its report in the right pane."""
        for iid in self.lit_tree.selection():
            meta = self._nom_iid_meta.get(iid)
            if meta is not None and not meta["fetchable"]:
                continue
            self._lit_selected_taxon = iid
            cache_key = self._lit_cache_key(iid)
            report = self._resources_cache.get(cache_key, {}).get("report_text", "")
            self._info_report_text.config(state="normal")
            self._info_report_text.delete("1.0", tk.END)
            if report:
                self._info_report_text.insert(tk.END, report)
                self._linkify_report()
            self._info_report_text.config(state="disabled")
            break

    def _linkify_report(self):
        """Tag all URLs in _info_report_text as clickable hyperlinks."""
        widget = self._info_report_text
        for tag in list(widget.tag_names()):
            if tag.startswith("url_"):
                widget.tag_delete(tag)
        content = widget.get("1.0", "end-1c")
        for n, m in enumerate(re.finditer(r'https?://\S+', content)):
            tag = f"url_{n}"
            widget.tag_add(tag, f"1.0+{m.start()}c", f"1.0+{m.end()}c")
            widget.tag_config(tag, foreground="#0066cc", underline=True)
            widget.tag_bind(tag, "<Button-1>", lambda e, u=m.group(): webbrowser.open(u))
            widget.tag_bind(tag, "<Enter>",    lambda e: widget.config(cursor="hand2"))
            widget.tag_bind(tag, "<Leave>",    lambda e: widget.config(cursor=""))

    def _on_lit_dblclick(self, event):
        """Inline-edit the Comments cell on double-click."""
        region = self.lit_tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col = self.lit_tree.identify_column(event.x)
        row = self.lit_tree.identify_row(event.y)
        meta = self._nom_iid_meta.get(row) if row else None
        if not row or col != "#3" or (meta is not None and not meta["fetchable"]):   # #3 = comments column
            return
        bbox = self.lit_tree.bbox(row, col)
        if not bbox:
            return
        x, y, width, height = bbox
        current = self.lit_tree.set(row, "comments")
        entry = tk.Entry(self.lit_tree, font=tkFont.nametofont("TkDefaultFont"))
        entry.place(x=x, y=y, width=width, height=height)
        entry.insert(0, current)
        entry.select_range(0, tk.END)
        entry.focus_set()

        def _save(event=None):
            new_val = entry.get()
            entry.destroy()
            self.lit_tree.set(row, "comments", new_val)
            ck = self._lit_cache_key(row)
            # Save comments in _resources_cache (primary store)
            self._resources_cache.setdefault(ck, {})["comments"] = new_val
            if self.filepath:
                save_resources_cache(self._resources_cache, self.filepath)

        entry.bind("<Return>",   _save)
        entry.bind("<FocusOut>", _save)
        entry.bind("<Escape>",   lambda e: entry.destroy())

    def _on_lit_right_click(self, event):
        """Open the cache popup for the row under the cursor (preserves multi-selection)."""
        row = self.lit_tree.identify_row(event.y)
        if not row:
            return
        if row not in self.lit_tree.selection():
            self.lit_tree.selection_set(row)
        self._lit_selected_taxon = row
        self._show_lit_popup(row, event.x_root, event.y_root)

    def _show_lit_popup(self, taxon_name, x_root, y_root):
        """Right-click popup: DwC fields with controlled-vocab dropdowns + Comments/Conflicts."""
        cache_key    = self._lit_cache_key(taxon_name)
        dc_entry     = self._lit_cache.get(cache_key, {})
        res_entry    = self._resources_cache.get(cache_key, {})
        is_fetched   = bool(dc_entry.get("retrieved") or dc_entry.get("providers_queried"))
        is_new       = is_new_format(dc_entry)
        fields_d     = dc_entry.get("fields", {}) if is_new else {}
        conflict_map = {c["term"]: c for c in dc_entry.get("conflicts", [])} if is_new else {}
        dwc_auto     = res_entry.get("dwc_fields", {})   # auto-extracted at fetch time
        fetchable    = self._nom_iid_meta.get(taxon_name, {}).get("fetchable", True)
        profile_conflicts = res_entry.get("profile_conflicts", [])

        # Use Include-checked fields (not Retrieve) to drive the popup
        terms = sorted(self._lit_include_fields) if self._lit_include_fields else []

        display_name = self._nom_dataid_to_label.get(cache_key, cache_key).replace("_", " ")

        win = tk.Toplevel(self.root)
        win.title(f"DwC: {display_name}")
        win.geometry("680x560")
        win.resizable(True, True)
        win.transient(self.root)

        tk.Label(win, text=display_name, font=self.app_ui_bold, anchor="w").pack(
            fill="x", padx=8, pady=(6, 2)
        )

        # Button row — packed FIRST so it's never hidden by the expanding content
        btn_frame = tk.Frame(win)
        btn_frame.pack(side="bottom", fill="x", padx=8, pady=(0, 8))

        # Comments / Conflicts section — packed before the expanding dc_section
        if fetchable:
            # For "is" taxa: editable comments box, pre-populated with conflicts if empty
            _bottom_label = "Conflicts / Comments"
        else:
            _bottom_label = "Comments"
        comments_frame = tk.LabelFrame(win, text=_bottom_label, padx=4, pady=4)
        comments_frame.pack(side="bottom", fill="x", padx=8, pady=(0, 4))
        comments_txt = tk.Text(comments_frame, height=4, wrap="word")
        comments_txt.pack(fill="x")
        # Build combined conflict list from both sources.
        # Skip stale cache entries where values differ only in case/whitespace.
        _ID_TERMS = {"taxonID", "taxonConceptID", "parentNameUsageID",
                     "acceptedNameUsageID", "originalNameUsageID", "nameAccordingToID",
                     "namePublishedInID", "scientificNameID"}
        _conflict_lines = []
        if is_new:
            for _c in dc_entry.get("conflicts", []):
                if _c.get("term") in _ID_TERMS:
                    continue
                _norm_vals = {v.strip().lower() for v in _c.get("values", {}).values()}
                if len(_norm_vals) <= 1:
                    continue  # purely a case/whitespace difference
                _vals = " | ".join(f"{src}: {v!r}" for src, v in _c.get("values", {}).items())
                _conflict_lines.append(f"[{_c['term']}] {_vals}")
        _conflict_lines.extend(profile_conflicts)

        existing_comment = res_entry.get("comments", "")
        if existing_comment:
            comments_txt.insert("1.0", existing_comment)
        elif fetchable and _conflict_lines:
            comments_txt.insert("1.0", "\n".join(_conflict_lines))

        # DC fields section — expand to fill remaining space
        dc_section = tk.LabelFrame(win, text="Darwin Core Fields", padx=4, pady=4)
        dc_section.pack(fill="both", expand=True, padx=8, pady=(0, 4))
        dc_section.grid_rowconfigure(0, weight=1)
        dc_section.grid_columnconfigure(0, weight=1)

        if not terms:
            tk.Label(dc_section, text="No fields selected under 'Include' in Settings › Databases.",
                     fg="#888").pack(anchor="w", padx=4, pady=4)
        else:
            canvas = tk.Canvas(dc_section, borderwidth=0, highlightthickness=0)
            v_scroll = ttk.Scrollbar(dc_section, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=v_scroll.set)
            canvas.grid(row=0, column=0, sticky="nsew")
            v_scroll.grid(row=0, column=1, sticky="ns")

            inner = tk.Frame(canvas)
            canvas_win = canvas.create_window((0, 0), window=inner, anchor="nw")

            def _on_inner_configure(e):
                canvas.configure(scrollregion=canvas.bbox("all"))
            def _on_canvas_configure(e):
                canvas.itemconfig(canvas_win, width=e.width)
            inner.bind("<Configure>", _on_inner_configure)
            canvas.bind("<Configure>", _on_canvas_configure)

            def _bind_mw(widget):
                widget.bind("<Enter>", lambda e: canvas.bind_all(
                    "<MouseWheel>", lambda ev: canvas.yview_scroll(int(-1*(ev.delta/120)), "units")))
                widget.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
            _bind_mw(canvas)

            hdr_bg = "#d0d0d0"
            tk.Label(inner, text="DC Field", font=self.app_ui_bold, anchor="w",
                     width=26, bg=hdr_bg).grid(row=0, column=0, sticky="ew", padx=1, pady=1)
            tk.Label(inner, text="Value", font=self.app_ui_bold, anchor="w",
                     bg=hdr_bg).grid(row=0, column=1, sticky="ew", padx=1, pady=1)
            tk.Label(inner, text="Source", font=self.app_ui_bold, anchor="w",
                     width=10, bg=hdr_bg).grid(row=0, column=2, sticky="ew", padx=1, pady=1)
            inner.grid_columnconfigure(1, weight=1)

        vars_by_term = {}

        for row_i, term in enumerate(terms, start=1):
            fv = fields_d.get(term, {})
            # Priority: existing lit_cache value → auto-extracted dwc_fields → empty
            raw_value = fv.get("value", "") if isinstance(fv, dict) else ""
            if not raw_value:
                raw_value = dwc_auto.get(term, "")
            source = fv.get("source", "") if isinstance(fv, dict) else ""
            if not source and raw_value and raw_value == dwc_auto.get(term, ""):
                source = "auto"
            in_conflict = term in conflict_map

            row_bg = "#fff8e1" if in_conflict else ("white" if row_i % 2 == 0 else "#f9f9f9")
            sv = tk.StringVar(value=raw_value)
            vars_by_term[term] = sv

            tk.Label(inner, text=term, anchor="w", bg=row_bg, width=26).grid(
                row=row_i, column=0, sticky="ew", padx=1, pady=1
            )

            vocab = CONTROLLED_VOCAB.get(term)
            if vocab:
                widget = ttk.Combobox(inner, textvariable=sv, values=vocab, state="normal")
            else:
                widget = ttk.Entry(inner, textvariable=sv)
            if in_conflict:
                widget.configure(foreground="#b71c1c")
            widget.grid(row=row_i, column=1, sticky="ew", padx=1, pady=1)

            src_label = source if source else ("fetched" if is_fetched else "manual")
            tk.Label(inner, text=src_label, anchor="w",
                     bg=row_bg, fg="#888", width=10).grid(
                row=row_i, column=2, sticky="ew", padx=1, pady=1
            )

        if is_fetched and terms:
            retrieved_str = dc_entry.get("retrieved", "")[:10]
            _providers    = ", ".join(dc_entry.get("providers_queried", []))
            tk.Label(dc_section, text=f"Fetched {retrieved_str} via {_providers}",
                     fg="#666", font=self.app_ui_font).grid(row=1, column=0, columnspan=2,
                                                    sticky="w", padx=2, pady=(2, 0))

        def _save_comments():
            comment = comments_txt.get("1.0", tk.END).strip()
            self._resources_cache.setdefault(cache_key, {})["comments"] = comment
            if self.filepath:
                save_resources_cache(self._resources_cache, self.filepath)
            res = self._resources_cache.get(cache_key, {})
            self._update_lit_row(cache_key, res)
            self.lit_status_var.set(f"Comments saved: {display_name}.")

        def _commit_dc():
            if not self.filepath:
                messagebox.showwarning("No File", "Save the file first before committing DC fields.",
                                       parent=win)
                return
            if not vars_by_term:
                return
            from datetime import datetime, timezone
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            existing = self._lit_cache.get(cache_key, {})
            if is_new_format(existing):
                updated_fields = dict(existing.get("fields", {}))
                for term, sv in vars_by_term.items():
                    val = sv.get().strip()
                    if term in updated_fields:
                        updated_fields[term] = {**updated_fields[term], "value": val}
                    elif val:
                        updated_fields[term] = {"value": val, "source": "manual"}
                entry_new = {**existing, "fields": updated_fields}
            else:
                entry_new = {
                    "retrieved":         now_str,
                    "providers_queried": ["manual"],
                    "fields":            {t: {"value": sv.get().strip(), "source": "manual"}
                                          for t, sv in vars_by_term.items() if sv.get().strip()},
                    "conflicts":         [],
                    "provider_data":     {},
                    "error":             "",
                }
            self._lit_cache[cache_key] = entry_new
            save_cache_atomic(self._lit_cache, self.filepath)
            self.lit_status_var.set(f"DC fields saved: {display_name}.")
            win.destroy()

        if terms:
            tk.Button(btn_frame, text="Commit DC", command=_commit_dc).pack(side="left", padx=(0, 6))
        tk.Button(btn_frame, text="Save Comments", command=_save_comments).pack(side="left", padx=(0, 6))
        tk.Button(btn_frame, text="Close", command=win.destroy).pack(side="right")

    def _export_lit_csv(self):
        """Export selected taxa's Darwin Core cache data as a flat CSV file."""
        import csv as _csv

        selected = [s for s in self.lit_tree.selection()
                    if self._nom_iid_meta.get(s, {}).get("fetchable", s not in self._nom_iid_meta)]
        if not selected:
            messagebox.showinfo("Export", "Select one or more taxa in the table first.")
            return

        # Columns = all Retrieve-checked Darwin Core terms, sorted for consistency
        columns = sorted(self._lit_retrieve_fields)
        if not columns:
            messagebox.showinfo("Export", "No Retrieve fields are selected in the field selector.")
            return

        save_path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Export Darwin Core CSV",
            **self._wd_kwargs()
        )
        if not save_path:
            return

        with open(save_path, "w", newline="", encoding="utf-8") as f:
            writer = _csv.DictWriter(f, fieldnames=["taxonName"] + columns,
                                     extrasaction="ignore")
            writer.writeheader()
            for taxon_name in selected:
                ck    = self._lit_cache_key(taxon_name)
                entry = self._lit_cache.get(ck, {})
                fields_d = entry.get("fields", {}) if is_new_format(entry) else {}
                # Use the CARL nom-label if available, otherwise the cache key
                display = self._nom_dataid_to_label.get(ck, ck).replace("_", " ")
                row = {"taxonName": display}
                for term in columns:
                    fv = fields_d.get(term, {})
                    val = fv.get("value", "") if isinstance(fv, dict) else ""
                    # Don't write the sentinel into the CSV — leave blank
                    if val == "No Information Available":
                        val = ""
                    row[term] = val
                writer.writerow(row)

        import os as _os
        n = len(selected)
        noun = "taxon" if n == 1 else "taxa"
        self.lit_status_var.set(f"Exported {n} {noun} to {_os.path.basename(save_path)}.")

    def _add_groups_to_literature(self):
        """Add selected groups from the Analyses panel Groups list to the Literature tab as virtual taxa."""
        if not self.dataset or not self.filepath:
            messagebox.showerror("Literature", "Please load a NEXUS file first.")
            return
        sel_iids = [iid for iid in self._ana_tree.selection()
                    if "group_header" in set(self._ana_tree.item(iid, "tags"))]
        if not sel_iids:
            messagebox.showinfo("Literature", "Select one or more groups first.")
            return
        dataset_names = {t.name for t in self.dataset.taxa}
        added = []
        skipped = []
        for iid in sel_iids:
            name = self._ana_tree.item(iid, "text")
            if name in dataset_names:
                skipped.append(name)
                continue
            if name not in self._lit_cache:
                self._lit_cache[name] = {"is_group_taxon": True}
                added.append(name)
            else:
                skipped.append(name)
        if added:
            save_cache_atomic(self._lit_cache, self.filepath)
            self.populate_literature_table()
            noun = "group" if len(added) == 1 else "groups"
            self.lit_status_var.set(
                f"Added {len(added)} {noun} to Literature list: {', '.join(added)}."
            )
        else:
            messagebox.showinfo(
                "Literature",
                "Selected group(s) are already in the Literature list or conflict with taxon names."
            )

    def _remove_group_from_literature(self, name):
        """Remove a group-taxon entry from the Literature list and cache."""
        if not self.filepath:
            return
        self._lit_cache.pop(name, None)
        save_cache_atomic(self._lit_cache, self.filepath)
        try:
            self.lit_tree.delete(name)
        except tk.TclError:
            pass
        self._lit_selected_taxon = None
        self.lit_status_var.set(f"Removed '{name.replace('_', ' ')}' from Literature list.")

    def verify_all_cached(self):
        """Show a summary of conflict counts across all new-format cached entries."""
        if not self.dataset:
            messagebox.showerror("Literature", "Please load a NEXUS file first.")
            return
        conflict_taxa = [
            name for name, entry in self._lit_cache.items()
            if is_new_format(entry) and entry.get("conflicts")
            and not entry.get("fixed", False)
        ]
        total_cached = sum(1 for e in self._lit_cache.values() if entry_has_data(e))
        fixed_count  = sum(1 for e in self._lit_cache.values() if e.get("fixed"))
        suffix = f" ({fixed_count} Fixed skipped)" if fixed_count else ""
        if not conflict_taxa:
            self.lit_status_var.set(
                f"{total_cached} taxa cached, no conflicts detected.{suffix}"
            )
        else:
            n = len(conflict_taxa)
            self.lit_status_var.set(
                f"{total_cached} cached, {n} with conflicts{suffix}. "
                "Right-click a taxon to review."
            )

    def refresh_selected_taxon(self):
        """Re-fetch literature for the currently selected taxon (ignores existing cache)."""
        taxon_name = self._lit_selected_taxon   # treeview iid
        if not taxon_name:
            messagebox.showinfo("Literature", "Select a taxon in the table first.")
            return
        cache_key = self._lit_cache_key(taxon_name)
        if self._lit_cache.get(cache_key, {}).get("fixed", False):
            self.lit_status_var.set(
                f"{taxon_name.replace('_', ' ')} is Fixed — unfix to refresh."
            )
            return
        if not self.filepath:
            return
        if self._literature_running:
            messagebox.showinfo(
                "Literature", "Another operation is in progress. Please wait."
            )
            return

        self._literature_running = True
        self.lit_cache_btn.config(state="disabled")
        self.lit_refresh_btn.config(state="disabled")

        def worker():
            self.root.after(
                0, lambda n=taxon_name:
                self.lit_status_var.set(f"Refreshing {n.replace('_', ' ')}...")
            )

            def status_fn(msg):
                self.root.after(0, lambda m=msg: self.lit_status_var.set(m))

            providers  = self._lit_enabled_providers()
            query_name = self._get_retrieval_targets(cache_key)[0]
            entry = fetch_taxon_entry(
                query_name,
                providers,
                providers,
                self._lit_retrieve_fields,
                status_fn=status_fn,
            )
            self._lit_cache[cache_key] = entry
            save_cache_atomic(self._lit_cache, self.filepath)
            self.root.after(
                0, lambda ck=cache_key, e=entry: self._update_lit_row(ck, e)
            )
            self._literature_running = False
            self.root.after(0, lambda: self.lit_cache_btn.config(state="normal"))
            self.root.after(0, lambda: self.lit_refresh_btn.config(state="normal"))
            self.root.after(
                0, lambda n=taxon_name:
                self.lit_status_var.set(
                    f"Refresh complete for {n.replace('_', ' ')}."
                )
            )

        threading.Thread(target=worker, daemon=True).start()
