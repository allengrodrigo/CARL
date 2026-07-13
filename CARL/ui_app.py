import tkinter as tk
import tkinter.font as tkFont
from tkinter import ttk, filedialog, messagebox, simpledialog
from PIL import Image, ImageTk
import threading
from parser import (
    parse_nexus, update_charstatelabels_in_nexus,
    parse_charsets,
    generate_data_block, build_nexus_content, write_nexus_atomic,
)
from data_model import Taxon, Dataset, Character
from carl_parser import (
    parse_carl_block, detect_file_state,
    CARLBlock, TaxonEntity, TaxonRelationship,
    NONE_ID, _is_real,
)
from core_operations import (
    build_knowledge_graph,
    compare_taxa,
    generate_descriptions,
    format_comparison,
    distinguish_taxa,
    build_temp_kg,
    insert_into_hierarchy
)
from group_operations import (resolve_selection, evaluate_taxa_for_mak,
                              build_group_data_ids, build_member_data_ids)
from description_generator import build_base_description
from key_builder import build_tree_kg, format_key, generate_key
from carl_parser import parse_wtsets, parse_precludes, serialize_carl_block
from llm_formatter import (
    format_fast,
    format_diagnosis,
    format_with_literature,
    verify_output_with_llm,
    verification_passed,
    verification_has_issues,
    verification_display_text,
    correct_prose_with_llm,
    correct_key_with_llm,
    preformat_key_lines,
    naturalize_key_stream,
    rewrite_key_by_couplet,
    clean_key_output,
    build_preamble,
    format_fast_stream,
    format_with_literature_stream,
    format_diagnosis_stream,
    rewrite_key_stream,
)
from diagnose_taxon import build_diagnosis_output, format_diagnosis_output
from literature_cache import (
    fetch_taxon_entry,
    load_cache,
    save_cache_atomic,
    is_new_format,
    entry_has_data,
    INTER_TAXON_DELAY,
    DEFAULT_PROVIDER_ORDER,
    load_resources_cache,
    save_resources_cache,
)
import webbrowser
from darwin_core import (RECOMMENDED as DEFAULT_FIELDS, SECTIONS, BY_SECTION,
                         TAXON_SECTIONS, TAXON_STATUS, VOCAB_TYPE,
                         DEFAULT_INCLUDE_FIELDS)
from biodiversity_apis import (
    set_contact_email, set_wsc_api_key,
    fetch_gbif_publications, fetch_crossref_publications,
    resolve_gbif_backbone, fetch_gbif_synonyms, fetch_gbif_descriptions,
    fetch_gbif_image_urls, fetch_gbif_specimens,
    fetch_col_summary, fetch_ncbi_summary, fetch_itis_summary,
    fetch_zoobank_summary, fetch_bhl_records,
    plazi_genus_species, fetch_plazi_treatments,
    fetch_plazi_specimens, fetch_plazi_keys,
    fetch_wikipedia_report,
    # --- new sandbox pipeline ---
    resolve_gbif_backbone_rich, fetch_gbif_children, fetch_gbif_species_profiles,
    fetch_gbif_references, fetch_gbif_pub_dicts,
    get_zoobank_full,
    get_crossref_pub_dicts,
    get_col_full,
    get_ncbi_records,
    get_plazi_all, get_plazi_keys_full,
    fetch_bhl_enriched, get_bhl_pub_dicts,
    resolve_publications,
    summarize_wikipedia_llm,
    _canonical_key, _name_authorship, _auth_year, _auth_key,
    _tabulate, _RANK_PLURAL,
)
from llm_interface import call_llm, LLMConfig, DEFAULT_MODELS, RateLimitError
from utils import estimate_num_predict_from_kg, estimate_num_predict_from_text
import os
import re
import sys
import shutil
import tempfile
import time
from datetime import datetime, timezone
import subprocess
import json
import queue as _queue_mod
import plugin_manager as _pm
from chatbot.chatbot_controller import (
    ask, ask_stream, _friendly_error,
    get_rar_chunks, format_rar_response,
)
import traceback



from nomenclature_operations import NomenclatureMixin
from editor_operations import EditorMixin
from information_operations import InformationMixin

SETTINGS_FILE = "taxongpt_settings.json"

# Per-provider metadata: default enabled state and a short UI note.
_ALL_PROVIDER_META = {
    "GBIF":        {"default_enabled": True,  "note": ""},
    "CoL":         {"default_enabled": True,  "note": ""},
    "ITIS":        {"default_enabled": True,  "note": ""},
    "WoRMS":       {"default_enabled": True,  "note": "Marine and non-marine; LSID registry"},
    "WSC":         {"default_enabled": False, "note": "Araneae only; requires API key"},
    "BacDive":     {"default_enabled": False, "note": "Prokaryotes, genus/species only; no registration needed"},
    "POWO":        {"default_enabled": False, "note": "Vascular plants only"},
    "NCBI":        {"default_enabled": True,  "note": ""},
    "ZooBank":     {"default_enabled": True,  "note": "Per-IP verification required"},
    "CrossRef":    {"default_enabled": True,  "note": ""},
    "BHL":         {"default_enabled": True,  "note": "Requires API key"},
    "Plazi":       {"default_enabled": True,  "note": "Genus / species only"},
    "Wikipedia":   {"default_enabled": False, "note": ""},
    "Wikidata":    {"default_enabled": False, "note": "Placeholder — not yet implemented"},
}

# Retrieval limits: (settings_key, UI label, default, sandbox module attribute)
_DB_LIMITS = [
    ("publications", "Publications",              10, ""),
    ("images",       "Images",                   10, "GBIF_IMG_LIMIT"),
    ("specimens",    "Specimens",                20, "GBIF_SPEC_LIMIT"),
    ("ncbi_acc",     "NCBI accessions (sample)", 10, "NCBI_ACC_LIMIT"),
    ("plazi_uuid",   "Plazi treatments",         10, "PLAZI_UUID_LIMIT"),
    ("plazi_keys",   "Plazi treatments with keys", 5, "PLAZI_KEY_LIMIT"),
    ("bhl_titles",   "BHL title records",         5, "BHL_MAX_TITLES"),
    ("bhl_pages",    "BHL page records",         10, "BHL_MAX_PAGES"),
    ("zoobank_acts", "ZooBank acts",             10, ""),
]



def _bind_tooltip(widget, text: str, delay: int = 600, wrap: int = 340) -> None:
    """Attach a hover tooltip to *widget* showing *text* in full.

    Cross-platform: uses a borderless Toplevel positioned below the widget.
    Works on Windows, Linux (X11/Wayland), and macOS.
    """
    state = [None, None]  # [after-id, Toplevel]

    def _enter(_e):
        state[0] = widget.after(delay, _show)

    def _show():
        if state[1]:
            return
        tw = tk.Toplevel(widget)
        tw.wm_overrideredirect(True)
        tk.Label(tw, text=text, justify="left", background="#ffffe0",
                 relief="solid", borderwidth=1,
                 wraplength=wrap, padx=5, pady=3).pack()
        tw.update_idletasks()  # force geometry calculation before positioning

        tw_w = tw.winfo_reqwidth()
        tw_h = tw.winfo_reqheight()
        scr_w = widget.winfo_screenwidth()
        scr_h = widget.winfo_screenheight()

        x = widget.winfo_rootx() + 4
        y = widget.winfo_rooty() + widget.winfo_height() + 2

        if x + tw_w > scr_w:
            x = scr_w - tw_w - 4
        if x < 0:
            x = 0
        if y + tw_h > scr_h:
            y = widget.winfo_rooty() - tw_h - 2  # flip above widget
        if y < 0:
            y = 0

        tw.wm_geometry(f"+{x}+{y}")
        state[1] = tw

    def _leave(_e):
        if state[0]:
            widget.after_cancel(state[0])
            state[0] = None
        if state[1]:
            state[1].destroy()
            state[1] = None

    widget.bind("<Enter>",       _enter, add="+")
    widget.bind("<Leave>",       _leave, add="+")
    widget.bind("<ButtonPress>", _leave, add="+")


def _strip_report_tags(line: str) -> str:
    """Remove trailing bracketed tags (e.g. '[synonym]', '[CoL, WoRMS]',
    '[GBIF — authorship conflict]') from a report entry, leaving 'Name Author'."""
    return re.sub(r"\s*\[[^\]]*\]", "", line).strip()


def _extract_synonyms_from_report(report_text: str) -> str:
    """Extract the synonym names from §2 of a resources-cache report, cleaned for
    use in a Descriptions preamble: the '[Synonyms — N entries]' count header and
    the trailing [status]/[sources] tags are dropped. The Information-tab report
    itself is unchanged. Returns indented name lines, or '' if absent/empty.
    """
    if not report_text:
        return ""
    idx = report_text.find("=== 2. SYNONYMS ===")
    if idx < 0:
        return ""
    next_sec = report_text.find("\n=== ", idx + 1)
    body = (report_text[idx + len("=== 2. SYNONYMS ==="):next_sec]
            if next_sec > 0 else report_text[idx + len("=== 2. SYNONYMS ==="):])
    out = []
    for l in body.splitlines():
        s = l.strip()
        if not s or s.startswith("[Synonyms"):   # skip blanks + count header
            continue
        s = _strip_report_tags(s)
        if s:
            out.append("  " + s)
    return "\n".join(out)


def build_preamble_from_report(report_text: str) -> str:
    """Build a Descriptions preamble from the cached information report:
    name + authorship, taxonomic hierarchy, and the cleaned synonym list.
    Daughter taxa and Darwin Core fields are intentionally excluded. Returns ''
    when the report has no usable §1 (caller falls back to the taxon name).
    """
    if not report_text:
        return ""
    i1 = report_text.find("=== 1. TAXONOMIC PROFILE ===")
    if i1 < 0:
        return ""
    i2 = report_text.find("\n=== ", i1 + 1)
    sec1 = report_text[i1:i2] if i2 > 0 else report_text[i1:]

    def _field(label: str) -> str:
        m = re.search(rf"^\s*{re.escape(label)}\s*(.+?)\s*$", sec1, re.MULTILINE)
        return m.group(1).strip() if m else ""

    name = _field("Accepted name:")
    if not name:
        return ""
    authorship = _field("Authorship:")
    hierarchy  = _field("Hierarchy:")

    lines = [f"{name} {authorship}".strip() if authorship else name]
    if hierarchy:
        lines.append(hierarchy)
    synonyms = _extract_synonyms_from_report(report_text)
    if synonyms:
        lines += ["", "Synonyms:", synonyms]
    return "\n".join(lines).rstrip()


def _bundle_path(filename: str) -> str:
    """Return the absolute path to a file bundled with the application."""
    import sys
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS  # _internal/ in PyInstaller 6 one-folder builds
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, filename)

DEFAULT_SETTINGS = {
        "output_model": "llama3.2:1b",
        "output_temp": 0.2,

        "verify_model": "gemma3n:e4b",
        "verify_temp": 0.0,
        "verify_max_tokens": 4096,
        "style_guide": _bundle_path("minimal_style_guide.md"),
        "verify_style_guide": "",

        "chat_model": "llama3.2:1b",

        "ui_font_size":   0,
        "mono_font_size": 0,

        "local_ports": "1234, 1337, 8000, 8080",

        "working_dir": "",
    }

def get_default_model(role, fallback):
    model = DEFAULT_MODELS.get(role)
    return model if model else fallback

class TaxonGPT_UI(EditorMixin, NomenclatureMixin, InformationMixin):


    def __init__(self, root, on_ready_callback=None, on_status_callback=None):
        self.root = root
        _status = on_status_callback or (lambda _: None)

        self.root.title("CARL")
        self.root.geometry("1100x750")   # fallback before maximise
        self.root.update_idletasks()
        try:
            self.root.state("zoomed")    # Windows / Linux
        except tk.TclError:
            self.root.attributes("-zoomed", True)  # fallback for some Linux WMs

        # Increase all default font sizes by 2pt
        for _fname in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                _f = tkFont.nametofont(_fname)
                _f.configure(size=_f.cget("size") + 2)
            except Exception:
                pass

        # Force a consistent ttk theme across macOS/Windows/Linux. The native
        # macOS "aqua" theme renders Notebook tab labels in white under Dark
        # Mode (and ignores an explicit tab foreground); "clam" honours colour
        # configuration, so tab text stays black on every platform.
        _style = ttk.Style()
        try:
            _style.theme_use("clam")
        except tk.TclError:
            pass

        # Bold text on the active notebook tab; force a black label in every
        # state so a dark system appearance can't turn it white.
        _tab_sz = tkFont.nametofont("TkDefaultFont").cget("size")
        _style.configure("TNotebook.Tab", padding=[10, 4], foreground="black")
        _style.map("TNotebook.Tab",
                   foreground=[("selected", "black"), ("!selected", "black")],
                   font=[("selected", ("TkDefaultFont", _tab_sz, "bold")),
                         ("!selected", ("TkDefaultFont", _tab_sz))])

        # Nav bar buttons: ttk (not tk.Button) so "clam" governs their colour —
        # macOS Aqua's native tk.Button ignores explicit bg/fg configuration.
        _style.configure(
            "Nav.TButton",
            background=self._NAV_BG, foreground=self._NAV_BTN_FG,
            font=("TkDefaultFont", _tab_sz, "bold"),
            borderwidth=0, relief="flat", padding=[16, 8],
        )
        _style.map(
            "Nav.TButton",
            background=[("active", self._NAV_ACTIVE_BG), ("!active", self._NAV_BG)],
            foreground=[("active", self._NAV_ACTIVE_FG), ("!active", self._NAV_BTN_FG)],
        )
        _style.configure(
            "NavActive.TButton",
            background=self._NAV_ACTIVE_BG, foreground=self._NAV_ACTIVE_FG,
            font=("TkDefaultFont", _tab_sz, "bold"),
            borderwidth=0, relief="flat", padding=[16, 8],
        )
        _style.map(
            "NavActive.TButton",
            background=[("active", self._NAV_ACTIVE_BG)],
            foreground=[("active", self._NAV_ACTIVE_FG)],
        )

        # ── Application font objects ──────────────────────────────────────
        # Mutable Font objects — configure(size=n) on any one updates all widgets live.
        _base_family = tkFont.nametofont("TkDefaultFont").cget("family")
        _mono_family = tkFont.nametofont("TkFixedFont").cget("family")
        self.app_ui_font      = tkFont.Font(family=_base_family, size=_tab_sz)
        self.app_ui_bold      = tkFont.Font(family=_base_family, size=_tab_sz, weight="bold")
        self.app_ui_italic    = tkFont.Font(family=_base_family, size=_tab_sz, slant="italic")
        self.app_mono_font    = tkFont.Font(family=_mono_family, size=_tab_sz)
        self.app_reading_font = tkFont.Font(family=_base_family, size=_tab_sz + 2)

        # Initialize attributes
        self.dataset = None
        self.dataset_text = ""
        self.kg = None
        self.carl_block = None    # CARLBlock when loaded; None in Build/Invalid state
        self._file_state = "invalid"
        self._nom_left_eid_to_iid: dict = {}
        self._nom_right_iids: dict = {}
        self._nom_right_iid_to_eid: dict = {}
        self._nom_divides_daughter_iids: dict = {}       # daughter_name → [iids]
        self._nom_divides_daughter_info: dict = {}        # iid → {data_id, subject_eid}
        self._nom_source: str | None = None
        self._nom_dataid_to_iid: dict = {}
        self._nom_eid_to_dataids: dict = {}
        self._nom_dataid_to_eids: dict = {}
        self._nom_dataid_to_label: dict = {}   # {data_id: nom_display_label}
        self._nom_label_to_dataid: dict = {}   # {nom_display_label: data_id}
        self._nom_preview_visible: bool = False
        self._carl_modified: bool = False
        self.groups = {}
        self._char_edits_pending = False
        self.filepath = None
        self._session_warned_files: set = set()  # W2 warnings shown once per file per session
        self.style_guide_path_var = tk.StringVar(
                                        value=_bundle_path("minimal_style_guide.md")
                                    )
        self.verify_style_guide_path_var = tk.StringVar(value="")

        # API keys — one StringVar per supported cloud provider
        self._api_key_vars: dict = {
            p: tk.StringVar()
            for p in ("groq", "openai", "huggingface", "anthropic", "google", "openrouter")
        }
        self._openrouter_free_only_var = tk.BooleanVar(value=True)
        self._cloud_models: list = []   # populated by fetch_cloud_models()
        self.test_model_var = tk.StringVar()

        self.available_models = []
        self._analysis_running = False
        self._llm_cancel = threading.Event()
        self._tpd_message = None

        # --------------------------------------------------
        # OUTPUT (generation)
        # --------------------------------------------------
        self.output_model_var = tk.StringVar(
            value=get_default_model("output", "gemma3n:e4b")
        )
        self.output_temp_var = tk.DoubleVar(value=0.2)

        # --------------------------------------------------
        # VERIFICATION
        # --------------------------------------------------
        self.verify_model_var = tk.StringVar(
            value=get_default_model("verification", "gemma3n:e4b")
        )
        self.verify_temp_var = tk.DoubleVar(value=0.0)
        self.verify_max_tokens_var = tk.IntVar(value=2048)

        # --------------------------------------------------
        # CARL (Chatbot)
        # --------------------------------------------------
        self.chat_model_var = tk.StringVar(
            value=get_default_model("chat", "llama3.2:1b")
        )

        # --------------------------------------------------
        # LITERATURE CACHING
        # --------------------------------------------------
        self._literature_running = False
        self._literature_cancel  = False
        self._info_running       = False   # consolidated info-panel worker
        self._info_cancel        = False
        self._lit_cache       = {}   # DWC field cache (GBIF/CoL/ITIS structured fields)
        self._resources_cache = {}   # sandbox-style text reports per taxon
        self._lit_row_keys: dict = {}   # kept for backward compat; superseded by _nom_iid_meta
        self._lit_key_to_iids: dict = {}  # cache_key → [nom_tree iids] in lit_tree
        self._nom_iid_meta: dict = {}     # nom_tree iid → {cache_key, fetchable, is_group_header}
        self._lit_selected_taxon = None
        self._lit_original_text = ""
        self._verify_running = False

        # Literature settings — populated by load_settings(), used by cache functions
        self._lit_retrieve_fields: set = set(DEFAULT_FIELDS)
        self._lit_include_fields:  set = set(DEFAULT_INCLUDE_FIELDS)
        self._lit_provider_settings: dict = {
            p: {"enabled": _ALL_PROVIDER_META[p]["default_enabled"], "priority": i + 1}
            for i, p in enumerate(DEFAULT_PROVIDER_ORDER)
        }

        # Provider and field Tkinter vars — must exist before Databases tab widgets are built
        self._lit_prov_enabled_vars  = {}
        self._lit_prov_priority_vars = {}
        for _ri, _prov in enumerate(DEFAULT_PROVIDER_ORDER, 1):
            _default_en = _ALL_PROVIDER_META[_prov]["default_enabled"]
            self._lit_prov_enabled_vars[_prov]  = tk.BooleanVar(value=_default_en)
            self._lit_prov_priority_vars[_prov] = tk.IntVar(value=_ri)

        # DB retrieval limit vars and BHL API key
        self._db_limit_vars = {
            key: tk.IntVar(value=default)
            for key, _label, default, _attr in _DB_LIMITS
        }
        self._bhl_api_key_var = tk.StringVar(value="")
        self._wsc_api_key_var = tk.StringVar(value="")

        self._lit_field_vars = {}
        for _section in SECTIONS:
            for _f in BY_SECTION.get(_section, []):
                self._lit_field_vars[_f.term] = {
                    "retrieve": tk.BooleanVar(value=_f.term in self._lit_retrieve_fields),
                    "include":  tk.BooleanVar(value=_f.term in self._lit_include_fields),
                }

        # Keyboard shortcuts (nav bar replaces the menu bar)
        self._bind_keyboard_shortcuts()

        # -------------------------
        # NAVIGATION BAR + PANELS
        # -------------------------
        self._panels = {}
        self._nav_buttons = {}

        self._nav_frame = tk.Frame(self.root, bg="#2c3e50")
        self._nav_frame.pack(side="top", fill="x")
        self._build_nav_bar()

        self._content_frame = tk.Frame(self.root)
        self._content_frame.pack(side="top", fill="both", expand=True)
        self._content_frame.grid_rowconfigure(0, weight=1)
        self._content_frame.grid_columnconfigure(0, weight=1)

        for name in ["file", "information", "analyses", "chatbot", "plugins", "settings", "about"]:
            f = tk.Frame(self._content_frame)
            f.grid(row=0, column=0, sticky="nsew")
            self._panels[name] = f

        # File panel — notebook with Nomenclature and Editor tabs
        self._file_nb = ttk.Notebook(self._panels["file"])
        self._file_nb.pack(fill="both", expand=True)
        self.nomenclature_tab = tk.Frame(self._file_nb)
        self._file_nb.add(self.nomenclature_tab, text="Nomenclature")
        self.editor_tab = tk.Frame(self._file_nb)
        self._file_nb.add(self.editor_tab, text="Editor")

        # Toolbar
        _ed_toolbar = tk.Frame(self.editor_tab, relief="groove", bd=1)
        _ed_toolbar.pack(fill="x", padx=4, pady=(4, 2))
        tk.Button(_ed_toolbar, text="New",            command=self._editor_new).pack(side="left", padx=4, pady=2)
        ttk.Separator(_ed_toolbar, orient="vertical").pack(side="left", padx=6, fill="y", pady=3)
        tk.Button(_ed_toolbar, text="+ Add DataID",   command=self._editor_add_dataid).pack(side="left", padx=2, pady=2)
        tk.Button(_ed_toolbar, text="+ Add Character",command=self._editor_add_character).pack(side="left", padx=2, pady=2)
        self._editor_pending_label = tk.Label(_ed_toolbar, text="", fg="darkorange")
        self._editor_pending_label.pack(side="left", padx=8)

        # Paned: left taxon list | right char/state canvas
        _ed_pane = tk.PanedWindow(self.editor_tab, orient="horizontal",
                                   sashrelief="flat", sashwidth=5)
        _ed_pane.pack(fill="both", expand=True, padx=4, pady=2)

        # ---- Left pane: taxon list ----
        _ed_left = tk.Frame(_ed_pane)
        _ed_pane.add(_ed_left, minsize=120)
        _ed_left.rowconfigure(1, weight=1)
        _ed_left.columnconfigure(0, weight=1)
        tk.Label(_ed_left, text="DataIDs", anchor="w",
                 font=self.app_ui_bold).grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))
        _ed_taxa_frame = tk.Frame(_ed_left)
        _ed_taxa_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        _ed_taxa_frame.rowconfigure(0, weight=1)
        _ed_taxa_frame.columnconfigure(0, weight=1)
        self._editor_taxa_list = ttk.Treeview(_ed_taxa_frame, show="tree", selectmode="browse")
        _ed_taxa_vsb = ttk.Scrollbar(_ed_taxa_frame, orient="vertical",
                                      command=self._editor_taxa_list.yview)
        self._editor_taxa_list.configure(yscrollcommand=_ed_taxa_vsb.set)
        self._editor_taxa_list.grid(row=0, column=0, sticky="nsew")
        _ed_taxa_vsb.grid(row=0, column=1, sticky="ns")
        self._editor_taxa_list.tag_configure("group_header", font=self.app_ui_bold)
        self._editor_taxa_list.tag_configure("unassigned", foreground="#aaaaaa")
        self._editor_taxa_list.tag_configure("carl_only",  foreground="#cccccc")
        self._editor_taxa_list.bind("<<TreeviewSelect>>", self._editor_select_taxon)
        self._editor_taxa_list.bind("<Button-3>", self._editor_taxa_right_click)
        self._editor_taxa_list.bind("<Button-2>", self._editor_taxa_right_click)
        self._editor_taxa_context_menu = tk.Menu(self.root, tearoff=0)

        # ---- Right pane: char/state canvas (built once; repopulated on taxon select) ----
        _ed_right = tk.Frame(_ed_pane)
        _ed_pane.add(_ed_right, minsize=300)
        _ed_right.rowconfigure(1, weight=1)
        _ed_right.columnconfigure(0, weight=1)
        self._states_column_header(_ed_right)
        (self._editor_canvas,
         self._editor_inner,
         _,
         self._editor_name_labels,
         self._editor_state_labels) = self._build_states_canvas(_ed_right)

        self.analysis_tab = self._panels["analyses"]  # kept for .after() calls in background threads

        # Chatbot panel — single notebook tab, full-width chat
        _chat_nb = ttk.Notebook(self._panels["chatbot"])
        _chat_nb.pack(fill="both", expand=True)
        _chat_tab_frame = tk.Frame(_chat_nb)
        _chat_nb.add(_chat_tab_frame, text="Chat")
        self._chat_panel_frame = _chat_tab_frame

        # Settings panel — notebook with LM Settings, Databases, Editor Settings
        _settings_nb = ttk.Notebook(self._panels["settings"])
        _settings_nb.pack(fill="both", expand=True)
        self._llm_settings_tab = tk.Frame(_settings_nb)
        _settings_nb.add(self._llm_settings_tab, text="LM Settings")
        _db_tab = tk.Frame(_settings_nb)
        _settings_nb.add(_db_tab, text="Databases")
        _db_tab.grid_columnconfigure(0, weight=0)
        _db_tab.grid_columnconfigure(1, weight=0)
        _db_tab.grid_columnconfigure(2, weight=1)
        _db_tab.grid_rowconfigure(3, weight=1)

        _status("Building settings panel...")
        self.root.update_idletasks()

        # ── Data Providers ────────────────────────────────────────────
        _prov_frame = ttk.LabelFrame(_db_tab, text="Data Providers")
        _prov_frame.grid(row=0, column=0, sticky="new", padx=10, pady=(10, 5))
        tk.Label(_prov_frame, text="Enabled",  font=self.app_ui_bold).grid(row=0, column=0, padx=(8, 4))
        tk.Label(_prov_frame, text="Priority", font=self.app_ui_bold).grid(row=0, column=1, sticky="w", padx=(0, 6))
        tk.Label(_prov_frame, text="Provider", font=self.app_ui_bold).grid(row=0, column=2, sticky="w", padx=(0, 12))
        tk.Label(_prov_frame, text="Notes",    font=self.app_ui_bold).grid(row=0, column=3, sticky="w")
        for _ri, _prov in enumerate(DEFAULT_PROVIDER_ORDER, 1):
            ttk.Checkbutton(_prov_frame, variable=self._lit_prov_enabled_vars[_prov],
                            command=self._apply_provider_settings).grid(row=_ri, column=0, padx=(8, 4), pady=2)
            _prio_spin = ttk.Spinbox(_prov_frame, textvariable=self._lit_prov_priority_vars[_prov],
                        from_=1, to=len(DEFAULT_PROVIDER_ORDER), width=4,
                        command=self._apply_provider_settings)
            _prio_spin._carl_tooltip_key = "db.priority"
            _prio_spin._carl_tooltip_fmt = {"name": _prov}
            _prio_spin.grid(row=_ri, column=1, sticky="w", padx=(0, 6), pady=2)
            tk.Label(_prov_frame, text=_prov, width=14, anchor="w").grid(row=_ri, column=2, sticky="w", padx=(0, 12))
            tk.Label(_prov_frame, text=_ALL_PROVIDER_META[_prov]["note"],
                     fg="#666666", anchor="w").grid(row=_ri, column=3, sticky="w")

        # ── Retrieval Limits ──────────────────────────────────────────
        _lim_frame = ttk.LabelFrame(_db_tab, text="Retrieval Limits")
        _lim_frame.grid(row=1, column=0, sticky="new", padx=10, pady=(0, 5))

        # ── API Keys column — BHL, WSC, ZooBank grouped together at top ─
        _apikeys_frame = tk.Frame(_db_tab)
        _apikeys_frame.grid(row=0, column=1, rowspan=2, sticky="new", padx=(0, 10), pady=(10, 5))

        _bhl_frame = ttk.LabelFrame(_apikeys_frame, text="BHL API Key")
        _bhl_frame.pack(fill="x", pady=(0, 5))
        tk.Label(_bhl_frame, text="Key:").grid(row=0, column=0, sticky="w", padx=(8, 4), pady=6)
        _bhl_entry = ttk.Entry(_bhl_frame, textvariable=self._bhl_api_key_var, show="*", width=28)
        _bhl_entry.grid(row=0, column=1, sticky="w", pady=6)
        def _make_bhl_toggle(e=_bhl_entry):
            return lambda: e.config(show="" if e.cget("show") == "*" else "*")
        ttk.Button(_bhl_frame, text="Show", command=_make_bhl_toggle(), width=5).grid(
            row=0, column=2, padx=(4, 8), pady=6)
        tk.Label(_bhl_frame,
                 text="Register at www.biodiversitylibrary.org/getapikey.aspx",
                 fg="#666666").grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 6))

        _wsc_frame = ttk.LabelFrame(_apikeys_frame, text="WSC API Key")
        _wsc_frame.pack(fill="x", pady=(0, 5))
        tk.Label(_wsc_frame, text="Key:").grid(row=0, column=0, sticky="w", padx=(8, 4), pady=6)
        _wsc_entry = ttk.Entry(_wsc_frame, textvariable=self._wsc_api_key_var, show="*", width=28)
        _wsc_entry.grid(row=0, column=1, sticky="w", pady=6)
        def _make_wsc_toggle(e=_wsc_entry):
            return lambda: e.config(show="" if e.cget("show") == "*" else "*")
        ttk.Button(_wsc_frame, text="Show", command=_make_wsc_toggle(), width=5).grid(
            row=0, column=2, padx=(4, 8), pady=6)
        tk.Label(_wsc_frame,
                 text="Register for a free key at wsc.nmbe.ch",
                 fg="#666666").grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 6))

        _zb_frame = ttk.LabelFrame(_apikeys_frame, text="ZooBank Access")
        _zb_frame.pack(fill="x")
        tk.Label(_zb_frame,
                 text="ZooBank requires human verification from each new IP address\n"
                      "(e.g. switching between office and home). If ZooBank returns no\n"
                      "results, click below to verify, then retry.",
                 justify="left").grid(row=0, column=0, sticky="w", padx=8, pady=(6, 4))
        ttk.Button(_zb_frame, text="Open ZooBank verification page ↗",
                   command=lambda: webbrowser.open("https://zoobank.org/search")
                   ).grid(row=1, column=0, sticky="w", padx=8, pady=(0, 8))
        for _li, (key, label, _default, _attr) in enumerate(_DB_LIMITS):
            _col = (_li % 2) * 3
            _row = _li // 2
            tk.Label(_lim_frame, text=f"{label}:", anchor="e", width=28).grid(
                row=_row, column=_col, sticky="e", padx=(10 if _col == 0 else 20, 4), pady=3)
            ttk.Spinbox(_lim_frame, textvariable=self._db_limit_vars[key],
                        from_=1, to=500, width=6).grid(
                row=_row, column=_col + 1, sticky="w", pady=3)


        # Darwin Core Fields (scrollable) — right column, full height
        _dc_frame = ttk.LabelFrame(_db_tab, text="Darwin Core Fields")
        _dc_frame.grid(row=0, column=2, rowspan=4, sticky="nsew", padx=(0, 10), pady=10)
        _dc_frame.grid_rowconfigure(0, weight=1)
        _dc_frame.grid_columnconfigure(0, weight=1)

        _dc_canvas = tk.Canvas(_dc_frame, highlightthickness=0)
        _dc_canvas.grid(row=0, column=0, sticky="nsew")
        _dc_sb = ttk.Scrollbar(_dc_frame, orient="vertical", command=_dc_canvas.yview)
        _dc_sb.grid(row=0, column=1, sticky="ns")
        _dc_canvas.configure(yscrollcommand=_dc_sb.set)

        _dc_inner = tk.Frame(_dc_canvas)
        _dc_win = _dc_canvas.create_window((0, 0), window=_dc_inner, anchor="nw")
        _dc_inner.bind("<Configure>", lambda e: _dc_canvas.configure(scrollregion=_dc_canvas.bbox("all")))
        _dc_canvas.bind("<Configure>", lambda e: _dc_canvas.itemconfig(_dc_win, width=e.width))
        def _dc_mw(e): _dc_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        _dc_canvas.bind("<Enter>", lambda e: _dc_canvas.bind_all("<MouseWheel>", _dc_mw))
        _dc_canvas.bind("<Leave>", lambda e: _dc_canvas.unbind_all("<MouseWheel>"))

        # Column layout: Retrieve | Include | Status | Field | Description | Vocab
        _dc_inner.grid_columnconfigure(0, minsize=72)
        _dc_inner.grid_columnconfigure(1, minsize=68)
        _dc_inner.grid_columnconfigure(2, minsize=100)
        _dc_inner.grid_columnconfigure(3, minsize=180)
        _dc_inner.grid_columnconfigure(4, weight=1, minsize=140)
        _dc_inner.grid_columnconfigure(5, minsize=90)

        # Header row
        _hdr_bg = "#d8d8d8"
        for _ci, _ht in enumerate(
                ["Retrieve", "Include", "Status", "Field", "Description", "Vocab"]):
            tk.Label(_dc_inner, text=_ht, font=self.app_ui_bold,
                     bg=_hdr_bg, anchor="w").grid(
                row=0, column=_ci, sticky="ew",
                padx=(4 if _ci == 0 else 1, 1), pady=(2, 2))
        tk.Frame(_dc_inner, height=1, bg="#999999").grid(
            row=1, column=0, columnspan=6, sticky="ew")

        _STATUS_FG = {
            "required":    "#c0392b",
            "recommended": "#1a5276",
            "optional":    "#7f8c8d",
        }

        def _on_retrieve(term):
            if not self._lit_field_vars[term]["retrieve"].get():
                self._lit_field_vars[term]["include"].set(False)
            self._apply_field_settings()

        _frow = 2
        for _section in TAXON_SECTIONS:
            _fields = [_f for _f in BY_SECTION.get(_section, [])
                       if _f.term in TAXON_STATUS]
            if not _fields:
                continue
            tk.Label(_dc_inner, text=_section, font=self.app_ui_bold,
                     fg="#2c3e50", bg="#ebebeb").grid(
                row=_frow, column=0, columnspan=6, sticky="ew",
                padx=2, pady=(6, 1))
            _frow += 1
            for _f in _fields:
                _fv = self._lit_field_vars.get(_f.term)
                if not _fv:
                    continue
                _fstatus = TAXON_STATUS.get(_f.term, "optional")
                _vocab   = VOCAB_TYPE.get(_f.term, "")
                _fg      = _STATUS_FG.get(_fstatus, "#7f8c8d")
                _bg      = "white" if _frow % 2 == 0 else "#f5f5f5"
                ttk.Checkbutton(_dc_inner, variable=_fv["retrieve"],
                                command=lambda t=_f.term: _on_retrieve(t)).grid(
                    row=_frow, column=0, sticky="w", padx=(8, 0))
                _inc_cb = ttk.Checkbutton(_dc_inner, variable=_fv["include"],
                                command=self._apply_field_settings)
                _inc_cb._carl_tooltip_key = "dwc.include"
                _inc_cb.grid(row=_frow, column=1, sticky="w", padx=(4, 0))
                tk.Label(_dc_inner, text=_fstatus.capitalize(),
                         anchor="w", fg=_fg, bg=_bg).grid(
                    row=_frow, column=2, sticky="ew", padx=(4, 2), pady=1)
                tk.Label(_dc_inner, text=_f.term,
                         anchor="w", bg=_bg).grid(
                    row=_frow, column=3, sticky="ew", padx=(4, 2), pady=1)
                _desc_lbl = tk.Label(_dc_inner, text=_f.description,
                                     anchor="w", bg=_bg, fg="#333333")
                _desc_lbl.grid(row=_frow, column=4, sticky="ew", padx=(4, 2), pady=1)
                _bind_tooltip(_desc_lbl, _f.description)
                tk.Label(_dc_inner, text=_vocab,
                         anchor="w", bg=_bg, fg="#555555").grid(
                    row=_frow, column=5, sticky="ew", padx=(4, 6), pady=1)
                _frow += 1
        # ---- Preferences tab ----
        _pref_tab = tk.Frame(_settings_nb)
        _settings_nb.add(_pref_tab, text="Preferences")
        _pref_tab.columnconfigure(1, weight=1)

        _pf = ttk.LabelFrame(_pref_tab, text="Font Sizes")
        _pf.grid(row=0, column=0, columnspan=2, sticky="ew", padx=10, pady=(12, 6))
        _pf.columnconfigure(1, weight=0)

        _ui_default = self.app_ui_font.cget("size")
        tk.Label(_pf, text="General text (pt):").grid(
            row=0, column=0, sticky="w", padx=(10, 6), pady=(8, 0))
        tk.Label(_pf, text="Labels, menus, buttons, tree rows", fg="#666").grid(
            row=1, column=0, sticky="w", padx=(10, 6), pady=(0, 6))
        self._pref_ui_font_size = tk.IntVar(value=_ui_default)
        _pref_ui_spin = ttk.Spinbox(_pf, textvariable=self._pref_ui_font_size,
                    from_=7, to=24, width=5)
        _pref_ui_spin._carl_tooltip_key = "pref.font_size_general"
        _pref_ui_spin.grid(row=0, column=1, rowspan=2,
                           sticky="w", padx=4, pady=(8, 6))

        _mono_default = self.app_mono_font.cget("size")
        tk.Label(_pf, text="Code/output text (pt):").grid(
            row=2, column=0, sticky="w", padx=(10, 6), pady=(8, 0))
        tk.Label(_pf, text="Analyses output, CARL block preview, info report", fg="#666").grid(
            row=3, column=0, sticky="w", padx=(10, 6), pady=(0, 6))
        self._pref_mono_font_size = tk.IntVar(value=_mono_default)
        _pref_mono_spin = ttk.Spinbox(_pf, textvariable=self._pref_mono_font_size,
                    from_=7, to=24, width=5)
        _pref_mono_spin._carl_tooltip_key = "pref.font_size_mono"
        _pref_mono_spin.grid(row=2, column=1, rowspan=2,
                             sticky="w", padx=4, pady=(8, 6))

        tk.Button(_pf, text="Apply", command=self._apply_font_prefs).grid(
            row=4, column=0, columnspan=2, pady=(4, 10))

        _wd = ttk.LabelFrame(_pref_tab, text="Working Directory")
        _wd.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 6))
        _wd.columnconfigure(1, weight=1)
        tk.Label(_wd, text="Folder:").grid(
            row=0, column=0, sticky="w", padx=(10, 4), pady=(8, 4))
        tk.Label(_wd, text="Default directory for Open and Save dialogs", fg="#666").grid(
            row=1, column=0, columnspan=3, sticky="w", padx=(10, 6), pady=(0, 6))
        self._pref_working_dir_var = tk.StringVar()
        tk.Entry(_wd, textvariable=self._pref_working_dir_var).grid(
            row=0, column=1, sticky="ew", padx=4, pady=(8, 4))
        _wd_browse_btn = tk.Button(
            _wd, text="Browse…",
            command=lambda: self._pref_working_dir_var.set(
                filedialog.askdirectory(
                    initialdir=self._pref_working_dir_var.get() or "."
                ) or self._pref_working_dir_var.get()
            )
        )
        _wd_browse_btn._carl_tooltip_key = "pref.working_dir_browse"
        _wd_browse_btn.grid(row=0, column=2, padx=(4, 10), pady=(8, 4))

        # Information panel — single split-pane view (no Notebook)
        self.literature_tab = tk.Frame(self._panels["information"])
        self.literature_tab.pack(fill="both", expand=True)

        if False:  # pragma: no cover  — legacy stubs so old method names don't cause NameError
            self.descriptions_tab = tk.Frame(self.literature_tab)
            _desc_btn_bar = tk.Frame(self.descriptions_tab)

        # About panel — Help and Citation tabs
        _about_nb = ttk.Notebook(self._panels["about"])
        _about_nb.pack(fill="both", expand=True)

        # --- Help tab ---
        _help_tab = tk.Frame(_about_nb)
        _about_nb.add(_help_tab, text="Help")
        from help_tab import HelpTab
        self._help_tab = HelpTab(_help_tab, _about_nb)

        # --- Citation tab ---
        _cite_tab = tk.Frame(_about_nb)
        _about_nb.add(_cite_tab, text="Citation")
        _cite_tab.grid_rowconfigure(0, weight=1)
        _cite_tab.grid_columnconfigure(0, weight=1)

        _cite_frame = tk.Frame(_cite_tab)
        _cite_frame.grid(row=0, column=0, sticky="nsew", padx=12, pady=12)
        _cite_frame.grid_rowconfigure(0, weight=1)
        _cite_frame.grid_columnconfigure(0, weight=1)
        _cite_text = tk.Text(_cite_frame, wrap="word", state="disabled",
                              font=self.app_reading_font)
        _cite_text.grid(row=0, column=0, sticky="nsew")
        _cite_sb = ttk.Scrollbar(_cite_frame, orient="vertical", command=_cite_text.yview)
        _cite_sb.grid(row=0, column=1, sticky="ns")
        _cite_text.config(yscrollcommand=_cite_sb.set)

        _citation_content = (
            "CARL — Classification (AI-accessible) Research Laboratory\n"
            "Version: Beta v1\n\n"
            "How to cite CARL:\n"
            "Rodrigo, A. G., Huang, H., Wang, Z., Seldon, D., and Li, T. (2026). Classification\n"
            "(AI-Accessible) Research Laboratory, CARL: An integrated environment\n"
            "for taxonomic research.\n\n"
            "─────────────────────────────────────────────────────\n\n"
            "Acknowledgements\n\n"
            "CARL was developed with assistance from AI coding tools:\n\n"
            "• OpenAI ChatGPT — early-stage architecture, prompt design,\n"
            "  and algorithm development.\n\n"
            "• Anthropic Claude / Claude Code — ongoing development,\n"
            "  UI restructuring, literature caching pipeline, and code review.\n\n"
            "LLM inference is powered by Groq (groq.com) and Ollama (ollama.com).\n\n"
            "Taxonomic data is retrieved from:\n"
            "  • GBIF — gbif.org\n"
            "  • Catalogue of Life — catalogueoflife.org\n"
            "  • ITIS — itis.gov\n\n"
            "─────────────────────────────────────────────────────\n\n"
            "Licence: MIT\n"
        )
        _cite_text.config(state="normal")
        _cite_text.insert("1.0", _citation_content)
        _cite_text.config(state="disabled")

        # ── Plugins panel ──────────────────────────────────────────────────────
        from plugin_operations import PluginsPanel
        self._plugins_panel = PluginsPanel(
            self._panels["plugins"],
            ui_font=self.app_ui_font,
            mono_font=self.app_mono_font,
            ui_font_bold=self.app_ui_bold,
        )

        self._show_panel("file")

        self.root.update_idletasks()

        # ── App-wide hover tooltips (single source: tooltips_data.py) ───────────
        try:
            from tooltips import TooltipController
            # Plugins panel: static buttons get help from the "Plugins tab" dict
            # group; the per-descriptor field inputs are excluded internally.
            try:
                self._plugins_panel.apply_manual_tooltips()
            except Exception:
                pass
            # Help > Contents sidebar: navigational links, not documented controls.
            try:
                self._help_tab.nav_frame._carl_disable_tooltips = True
            except Exception:
                pass
            self._tooltip_controller = TooltipController(self.root)
        except Exception:
            pass

        self._on_ready_callback  = on_ready_callback
        self._on_status_callback = on_status_callback or (lambda _: None)

 


        _status("Building Nomenclature panel...")
        self.root.update_idletasks()

        # ==========================================================
        # NOMENCLATURE TAB  (built in __init__; populated on load)
        # ==========================================================
        self.nomenclature_tab.columnconfigure(0, weight=1)
        self.nomenclature_tab.rowconfigure(3, weight=1)

        # Row 0: Persistent file-operations bar (always visible)
        _nom_file_bar = tk.Frame(self.nomenclature_tab, relief="groove", bd=1)
        _nom_file_bar.grid(row=0, column=0, sticky="ew", padx=6, pady=(4, 0))
        tk.Button(_nom_file_bar, text="Load NEXUS",
                  command=self.load_file).pack(side="left", padx=4, pady=3)
        tk.Button(_nom_file_bar, text="Save",
                  command=self.save_file).pack(side="left", padx=2, pady=3)
        tk.Button(_nom_file_bar, text="Save As…",
                  command=self.save_file_as).pack(side="left", padx=2, pady=3)
        self._nom_filepath_label = tk.Label(
            _nom_file_bar, text="No file loaded",
            fg="#555", font=self.app_ui_italic
        )
        self._nom_filepath_label.pack(side="left", padx=(16, 5), pady=3)

        # Row 1: Mode banner
        self._nom_mode_var = tk.StringVar(value="")
        self._nom_mode_label = tk.Label(
            self.nomenclature_tab,
            textvariable=self._nom_mode_var,
            anchor="w", fg="#555", font=self.app_ui_italic
        )
        self._nom_mode_label.grid(row=1, column=0, sticky="ew", padx=6, pady=(4, 0))

        # Row 2: CARL statement toolbar (hidden until a file is loaded)
        self._nom_toolbar = tk.Frame(self.nomenclature_tab)
        self._nom_toolbar.grid(row=2, column=0, sticky="ew", padx=6, pady=(2, 0))
        self._nom_toolbar.grid_remove()
        tk.Button(self._nom_toolbar, text="+ Add",
                  command=self._stmt_add_dialog).pack(side="left", padx=2)
        tk.Button(self._nom_toolbar, text="Edit",
                  command=self._stmt_edit_dialog).pack(side="left", padx=2)
        tk.Button(self._nom_toolbar, text="Delete",
                  command=self._stmt_delete).pack(side="left", padx=2)
        tk.Button(self._nom_toolbar, text="Assign Rank…",
                  command=self._stmt_assign_rank).pack(side="left", padx=2)
        ttk.Separator(self._nom_toolbar, orient="vertical").pack(
            side="left", padx=8, fill="y", pady=2)
        self._nom_preview_btn = tk.Button(
            self._nom_toolbar, text="▼ Preview", command=self._nom_preview_toggle)
        self._nom_preview_btn._carl_tooltip_key = "nom.preview_toggle"
        self._nom_preview_btn.pack(side="left", padx=2)

        # Row 3: Split-pane frame (hidden until a file is loaded)
        self._nom_frame = tk.Frame(self.nomenclature_tab)
        self._nom_frame.grid(row=3, column=0, sticky="nsew", padx=6, pady=4)
        self._nom_frame.grid_remove()
        self._nom_frame.columnconfigure(0, weight=1)
        self._nom_frame.rowconfigure(0, weight=1)

        _nom_paned = ttk.PanedWindow(self._nom_frame, orient="horizontal")
        _nom_paned.grid(row=0, column=0, sticky="nsew")

        # --- Left pane: Statement list ---
        _stmt_outer = tk.Frame(_nom_paned)
        _nom_paned.add(_stmt_outer, weight=1)
        _stmt_outer.columnconfigure(0, weight=1)
        _stmt_outer.rowconfigure(1, weight=1)
        tk.Label(_stmt_outer, text="Statements",
                 font=self.app_ui_bold, anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="ew", padx=2, pady=(2, 0))
        self._stmt_tree = ttk.Treeview(
            _stmt_outer,
            columns=(),
            show="tree headings",
            selectmode="extended",
        )
        self._stmt_tree.heading("#0", text="Statement")
        self._stmt_tree.column("#0", width=320, stretch=True)
        _stmt_vsb = ttk.Scrollbar(
            _stmt_outer, orient="vertical", command=self._stmt_tree.yview)
        self._stmt_tree.configure(yscrollcommand=_stmt_vsb.set)
        self._stmt_tree.grid(row=1, column=0, sticky="nsew")
        _stmt_vsb.grid(row=1, column=1, sticky="ns")
        self._stmt_tree.tag_configure("nov", foreground="#006699")
        self._stmt_tree.bind("<Double-1>", lambda _e: self._stmt_edit_dialog())
        self._stmt_tree.bind("<<TreeviewSelect>>", self._on_stmt_select)
        self._stmt_tree.bind("<Button-3>", self._stmt_right_click)

        # --- Right pane: Derived view ---
        _deriv_outer = tk.Frame(_nom_paned)
        _nom_paned.add(_deriv_outer, weight=1)
        _deriv_outer.columnconfigure(0, weight=1)
        _deriv_outer.rowconfigure(1, weight=1)
        _deriv_hdr = tk.Frame(_deriv_outer)
        _deriv_hdr.grid(row=0, column=0, columnspan=2, sticky="ew", padx=2, pady=(2, 0))
        _deriv_hdr.columnconfigure(0, weight=1)
        tk.Label(_deriv_hdr, text="Derived View",
                 font=self.app_ui_bold, anchor="w").pack(side="left")
        tk.Button(_deriv_hdr, text="+Add", pady=0,
                  command=self._nom_derived_add).pack(side="right")
        self.nom_tree = ttk.Treeview(
            _deriv_outer,
            columns=("status", "rank", "action", "warn"),
            show="tree headings",
            selectmode="extended",
        )
        self.nom_tree.heading("#0", text="Name")
        self.nom_tree.heading("status", text="Status")
        self.nom_tree.heading("rank", text="Rank")
        self.nom_tree.heading("action", text="Action")
        self.nom_tree.heading("warn", text="⚠")
        self.nom_tree.column("#0", width=180, stretch=True)
        self.nom_tree.column("status", width=50, anchor="center", stretch=False)
        self.nom_tree.column("rank", width=80, anchor="center", stretch=False)
        self.nom_tree.column("action", width=90, anchor="center", stretch=False)
        self.nom_tree.column("warn", width=24, anchor="center", stretch=False)
        _nom_vsb = ttk.Scrollbar(
            _deriv_outer, orient="vertical", command=self.nom_tree.yview)
        self.nom_tree.configure(yscrollcommand=_nom_vsb.set)
        self.nom_tree.grid(row=1, column=0, sticky="nsew")
        _nom_vsb.grid(row=1, column=1, sticky="ns")
        self.nom_tree.tag_configure("greyed", foreground="#999999")
        self.nom_tree.tag_configure("group_header", font=self.app_ui_bold)
        self.nom_tree.tag_configure("nov", foreground="#006699")
        self.nom_tree.tag_configure("no_rank", foreground="#cc6600")
        self._nom_menu = tk.Menu(self.root, tearoff=0)
        self.nom_tree.bind("<Button-3>", self._nomenclature_right_click)
        self.nom_tree.bind("<<TreeviewSelect>>", self._on_nom_right_select)

        # --- Third pane: DataID Pool ---
        _dataid_outer = tk.Frame(_nom_paned)
        _nom_paned.add(_dataid_outer, weight=1)
        _dataid_outer.columnconfigure(0, weight=1)
        _dataid_outer.rowconfigure(1, weight=1)
        _did_hdr = tk.Frame(_dataid_outer)
        _did_hdr.grid(row=0, column=0, columnspan=2, sticky="ew", padx=2, pady=(2, 0))
        _did_hdr.columnconfigure(0, weight=1)
        tk.Label(_did_hdr, text="DataID Pool",
                 font=self.app_ui_bold, anchor="w").pack(side="left")
        tk.Button(_did_hdr, text="Create Taxa…", pady=0,
                  command=self._dataid_create_taxa).pack(side="right")
        self._dataid_tree = ttk.Treeview(
            _dataid_outer,
            columns=(),
            show="tree",
            selectmode="extended",
        )
        _dataid_vsb = ttk.Scrollbar(
            _dataid_outer, orient="vertical", command=self._dataid_tree.yview)
        self._dataid_tree.configure(yscrollcommand=_dataid_vsb.set)
        self._dataid_tree.grid(row=1, column=0, sticky="nsew")
        _dataid_vsb.grid(row=1, column=1, sticky="ns")
        self._dataid_tree.tag_configure("assigned", background="#d8e8d8")
        self._dataid_tree.bind("<<TreeviewSelect>>", self._on_dataid_select)

        # Row 4: Preview panel (collapsible, hidden by default)
        self._nom_preview_frame = tk.Frame(
            self.nomenclature_tab, bd=1, relief="groove")
        self._nom_preview_frame.grid(
            row=4, column=0, sticky="ew", padx=6, pady=(0, 4))
        self._nom_preview_frame.grid_remove()
        _prev_hdr = tk.Frame(self._nom_preview_frame)
        _prev_hdr.pack(fill="x", padx=4, pady=(4, 0))
        tk.Label(_prev_hdr, text="CARL Block Preview",
                 font=self.app_ui_bold).pack(side="left")
        tk.Button(_prev_hdr, text="Copy",
                  command=self._nom_preview_copy).pack(side="right", padx=2)
        _prev_inner = tk.Frame(self._nom_preview_frame)
        _prev_inner.pack(fill="both", expand=True, padx=4, pady=(2, 4))
        _prev_inner.rowconfigure(0, weight=1)
        _prev_inner.columnconfigure(0, weight=1)
        self._nom_preview_text = tk.Text(
            _prev_inner, height=8, wrap="none",
            font=self.app_mono_font, state="disabled")
        _prev_ysb = ttk.Scrollbar(
            _prev_inner, orient="vertical", command=self._nom_preview_text.yview)
        _prev_xsb = ttk.Scrollbar(
            _prev_inner, orient="horizontal", command=self._nom_preview_text.xview)
        self._nom_preview_text.configure(
            yscrollcommand=_prev_ysb.set, xscrollcommand=_prev_xsb.set)
        self._nom_preview_text.grid(row=0, column=0, sticky="nsew")
        _prev_ysb.grid(row=0, column=1, sticky="ns")
        _prev_xsb.grid(row=1, column=0, sticky="ew")

        # Placeholder label when no file loaded (row 3 — same row as content)
        self._nom_placeholder = tk.Label(
            self.nomenclature_tab,
            text="Load a NEXUS file to view nomenclature.",
            fg="#888"
        )
        self._nom_placeholder.grid(row=3, column=0, pady=40)

        _status("Building Analyses panel...")
        self.root.update_idletasks()

        # ==========================================================
        # ANALYSES PANEL  (Descriptions | Comparisons | Keys)
        # ==========================================================

        # Shared vars — synced from tab-local vars before each run_action() call
        self.action_var         = tk.StringVar(value="generate_descriptions")
        self.output_mode        = tk.StringVar(value="raw")
        self.llm_mode           = tk.StringVar(value="fast")
        self._preamble_override = None
        self.nn_threshold_var   = tk.IntVar(value=3)
        self.thinking           = False
        self.thinking_job       = None
        self.thinking_dots      = 0
        self.carl_history       = []

        # Keys tab settings
        self._keys_algo_var    = tk.StringVar(value="ig")
        self._keys_format_var  = tk.StringVar(value="binary")
        self._keys_penalty_var = tk.StringVar(value="0.05")

        # Multi-Access Key tab state
        self._mak_state_selections: dict = {}   # {char_name: set_of_state_labels}
        self._mak_criteria_order:   list = []   # [char_name, ...] in listbox order
        self._mak_char_num_map:     dict = {}   # {char_name: 1-based display number}
        self._mak_taxa_rows:        list = []   # [(display_label, data_id), ...]

        # Progress + status bar sit below the notebook (packed first → anchored to bottom)
        _ana_bottom = tk.Frame(self.analysis_tab)
        _ana_bottom.pack(side="bottom", fill="x", padx=5, pady=3)
        self.progress = ttk.Progressbar(_ana_bottom, mode="indeterminate", length=300)
        self.progress.pack(fill="x", pady=(0, 2))
        self.status_var   = tk.StringVar(value="Ready")
        self.status_label = tk.Label(_ana_bottom, textvariable=self.status_var,
                                     anchor="w", fg="blue")
        self.status_label.pack(fill="x")

        # Main content: left selection pane + right notebook
        _ana_paned = tk.PanedWindow(self.analysis_tab, orient="horizontal",
                                    sashwidth=5, sashrelief="flat")
        _ana_paned.pack(fill="both", expand=True)

        # ---- Left pane: unified taxa + groups tree (mirrors Derived View) ----
        _ana_left = tk.Frame(_ana_paned)
        _ana_paned.add(_ana_left, minsize=130)
        _ana_left.columnconfigure(0, weight=1)
        _ana_left.rowconfigure(0, weight=1)

        _atf = tk.Frame(_ana_left)
        _atf.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        _atf.rowconfigure(0, weight=1)
        _atf.columnconfigure(0, weight=1)
        self._ana_tree = ttk.Treeview(_atf, show="tree", selectmode="extended")
        _at_vsb = ttk.Scrollbar(_atf, orient="vertical",
                                 command=self._ana_tree.yview)
        self._ana_tree.configure(yscrollcommand=_at_vsb.set)
        self._ana_tree.grid(row=0, column=0, sticky="nsew")
        _at_vsb.grid(row=0, column=1, sticky="ns")
        self._ana_tree.tag_configure("group_header", font=self.app_ui_bold)
        self._ana_tree.tag_configure("greyed",       foreground="#999999")
        self._ana_tree.tag_configure("nov",          foreground="#006699")
        self._ana_tree.bind("<Button-3>", self._ana_on_right_click)
        self._ana_tree.bind("<Button-2>", self._ana_on_right_click)

        self._ana_group_context_menu = tk.Menu(self.root, tearoff=0)
        self._ana_group_context_menu.add_command(
            label="View Group Members", command=self.view_group_members)
        self._ana_group_context_menu.add_command(
            label="Show Member Character States",
            command=self.show_group_states_popup)
        self._ana_group_context_menu.add_command(
            label="Show Group Character States",
            command=self.show_group_character_states_popup)
        self._ana_group_context_menu.add_separator()
        self._ana_group_context_menu.add_command(
            label="Add to Literature List",
            command=self._add_groups_to_literature)

        # ---- Right pane: notebook ----
        _ana_right = tk.Frame(_ana_paned)
        _ana_paned.add(_ana_right, minsize=300)

        _analyses_nb = ttk.Notebook(_ana_right)
        _analyses_nb.pack(fill="both", expand=True)

        # ---- shared inner helpers ----
        def _make_ctrl_row(parent, include_nlg=False):
            om = tk.StringVar(value="raw")
            lm = tk.StringVar(value="fast")
            vr = tk.IntVar(value=3)
            bar = tk.Frame(parent, relief="groove", bd=1)
            bar.pack(fill="x", padx=5, pady=(5, 2))
            tk.Label(bar, text="Output Mode:").grid(row=0, column=0, padx=(8, 4), pady=4, sticky="w")
            _om_raw = tk.Radiobutton(bar, text="Raw only",  variable=om, value="raw")
            _om_raw._carl_tooltip_key = "analyses.output_mode_raw"
            _om_raw.grid(row=0, column=1, sticky="w")
            _om_llm = tk.Radiobutton(bar, text="Raw + LLM", variable=om, value="llm")
            _om_llm._carl_tooltip_key = "analyses.output_mode_llm"
            _om_llm.grid(row=0, column=2, sticky="w", padx=(0, 0 if include_nlg else 16))
            col = 3
            if include_nlg:
                _om_nlg = tk.Radiobutton(bar, text="Raw + NLG", variable=om, value="nlg")
                _om_nlg._carl_tooltip_key = "analyses.output_mode_nlg"
                _om_nlg.grid(row=0, column=col, sticky="w", padx=(0, 16))
                col += 1
            tk.Label(bar, text="LLM Mode:").grid(row=0, column=col, padx=(0, 4), sticky="w"); col += 1
            _lm_menu = tk.OptionMenu(bar, lm, "fast", "full")
            _lm_menu._carl_tooltip_key = "analyses.llm_mode_dropdown"
            _lm_menu.grid(row=0, column=col, sticky="w", padx=(0, 8)); col += 1
            tk.Label(bar, text="Verification rounds:").grid(row=0, column=col, padx=(8, 4), sticky="w"); col += 1
            _vr_spin = tk.Spinbox(bar, from_=1, to=5, width=3, textvariable=vr)
            _vr_spin.grid(row=0, column=col, sticky="w", padx=(0, 8))
            def _sync_vr(*_):
                # LLM Mode + verification rounds apply only to Raw + LLM.
                is_llm = om.get() == "llm"
                _lm_menu.config(state="normal" if is_llm else "disabled")
                _vr_spin.config(
                    state="normal" if (is_llm and lm.get() == "full") else "disabled")
            lm.trace_add("write", _sync_vr)
            om.trace_add("write", _sync_vr)
            _sync_vr()
            return bar, om, lm, vr

        def _make_output(parent):
            hdr = tk.Frame(parent)
            hdr.pack(fill="x", padx=5, pady=(4, 0))
            tk.Label(hdr, text="Output", font=self.app_ui_bold).pack(side="left")
            out_frame = tk.Frame(parent)
            out_frame.pack(fill="both", expand=True, padx=5, pady=5)
            out_frame.grid_rowconfigure(0, weight=1)
            out_frame.grid_columnconfigure(0, weight=1)
            out = tk.Text(out_frame, wrap="word", font=self.app_mono_font)
            out.grid(row=0, column=0, sticky="nsew")
            sb = tk.Scrollbar(out_frame, orient="vertical", command=out.yview)
            sb.grid(row=0, column=1, sticky="ns")
            out.config(yscrollcommand=sb.set)
            _save_btn = tk.Button(hdr, text="Save…",
                      command=lambda w=out: (setattr(self, 'output', w), self._save_output()))
            _save_btn._carl_tooltip_key = "analyses.save_output"
            _save_btn.pack(side="right")
            _copy_btn = tk.Button(hdr, text="Copy",
                      command=lambda w=out: (setattr(self, 'output', w), self._copy_output()))
            _copy_btn._carl_tooltip_key = "analyses.copy"
            _copy_btn.pack(side="right", padx=(0, 4))
            return out

        # ============================================================
        # TAB 1: DESCRIPTIONS
        # ============================================================
        _desc_tab = tk.Frame(_analyses_nb)
        _analyses_nb.add(_desc_tab, text="Descriptions")

        _desc_bar, self._desc_output_mode, self._desc_llm_mode, self._desc_verify_rounds = _make_ctrl_row(_desc_tab, include_nlg=True)
        self._desc_include_lit = tk.BooleanVar(value=False)
        tk.Checkbutton(_desc_bar, text="Include Literature",
                       variable=self._desc_include_lit).grid(row=0, column=8, padx=8)
        tk.Button(_desc_bar, text="Preview/Edit Preamble",
                  command=self._show_preamble_popup).grid(row=0, column=9, padx=8)

        self._desc_run_btn = tk.Button(_desc_tab, text="Run", height=2,
                                       command=self._run_descriptions)
        self._desc_run_btn._carl_tooltip_key = "analyses.run"
        self._desc_run_btn.pack(padx=5, pady=4)
        self._desc_output = _make_output(_desc_tab)

        # ============================================================
        # TAB 2: COMPARISONS
        # ============================================================
        _comp_tab = tk.Frame(_analyses_nb)
        _analyses_nb.add(_comp_tab, text="Comparisons")

        _comp_bar, self._comp_output_mode, self._comp_llm_mode, self._comp_verify_rounds = _make_ctrl_row(_comp_tab)
        self._comp_action = tk.StringVar(value="compare_taxa")
        tk.Label(_comp_bar, text="Action:").grid(row=0, column=7, padx=(8, 4), sticky="w")
        for _col, (_lbl, _val) in enumerate(
            [("Compare", "compare_taxa"), ("Distinguish", "distinguish_taxa"), ("Diagnose", "diagnose_taxon")],
            start=8
        ):
            tk.Radiobutton(_comp_bar, text=_lbl, variable=self._comp_action, value=_val,
                           command=self._on_comp_action_change).grid(row=0, column=_col, sticky="w", padx=2)

        self.diagnose_frame = tk.LabelFrame(_comp_tab, text="Diagnose Taxon Options", padx=5, pady=5)
        self.diagnose_frame.columnconfigure(1, weight=1)
        tk.Label(self.diagnose_frame,
                 text="Index Taxon:").grid(row=0, column=0, padx=5, pady=(2, 2), sticky="w")
        self._diagnose_index_var = tk.StringVar()
        self._diagnose_index_cb = ttk.Combobox(
            self.diagnose_frame, textvariable=self._diagnose_index_var,
            state="readonly", width=36)
        self._diagnose_index_cb.grid(row=0, column=1, padx=5, pady=(2, 2), sticky="ew")
        tk.Label(self.diagnose_frame,
                 text="Comparison: select taxa/groups in the tree (empty = all other taxa).",
                 fg="grey").grid(row=1, column=0, columnspan=2, padx=5, pady=(0, 4), sticky="w")
        tk.Label(self.diagnose_frame,
                 text="Max differences for nearest neighbours").grid(row=2, column=0, padx=5, pady=2, sticky="w")
        _max_diff_spin = tk.Spinbox(self.diagnose_frame, from_=1, to=20, width=5,
                   textvariable=self.nn_threshold_var)
        _max_diff_spin._carl_tooltip_key = "comp.max_differences"
        _max_diff_spin.grid(row=2, column=1, padx=5, pady=2, sticky="w")
        # diagnose_frame shown/hidden by _on_comp_action_change

        self._comp_run_btn = tk.Button(_comp_tab, text="Run", height=2,
                                       command=self._run_comparisons)
        self._comp_run_btn._carl_tooltip_key = "analyses.run"
        self._comp_run_btn.pack(padx=5, pady=4)
        self._comp_output = _make_output(_comp_tab)

        # ============================================================
        # TAB 3: KEYS
        # ============================================================
        _keys_tab = tk.Frame(_analyses_nb)
        _analyses_nb.add(_keys_tab, text="Keys")

        # Control bar: algorithm + format + repeat penalty
        _keys_bar = tk.Frame(_keys_tab, relief="groove", bd=1)
        _keys_bar.pack(fill="x", padx=5, pady=(5, 2))

        tk.Label(_keys_bar, text="Algorithm:").grid(
            row=0, column=0, padx=(8, 4), pady=4, sticky="w")
        tk.Radiobutton(_keys_bar, text="IG",
                       variable=self._keys_algo_var, value="ig").grid(
            row=0, column=1, sticky="w")
        tk.Radiobutton(_keys_bar, text="DG",
                       variable=self._keys_algo_var, value="si").grid(
            row=0, column=2, sticky="w", padx=(0, 16))

        tk.Label(_keys_bar, text="Format:").grid(
            row=0, column=3, padx=(0, 4), sticky="w")
        tk.Radiobutton(_keys_bar, text="Binary",
                       variable=self._keys_format_var, value="binary").grid(
            row=0, column=4, sticky="w")
        tk.Radiobutton(_keys_bar, text="Multi-arm",
                       variable=self._keys_format_var, value="multi").grid(
            row=0, column=5, sticky="w", padx=(0, 16))

        tk.Label(_keys_bar, text="Repeat weight:").grid(
            row=0, column=6, padx=(0, 4), sticky="w")
        _keys_rw_entry = ttk.Entry(_keys_bar, textvariable=self._keys_penalty_var, width=6)
        _keys_rw_entry._carl_tooltip_key = "keys.repeat_weight"
        _keys_rw_entry.grid(row=0, column=7, sticky="w", padx=(0, 16))

        self._keys_output_mode = tk.StringVar(value="raw")
        self._keys_llm_mode    = tk.StringVar(value="fast")
        tk.Label(_keys_bar, text="Output Mode:").grid(
            row=0, column=8, padx=(0, 4), sticky="w")
        _keys_om_raw = tk.Radiobutton(_keys_bar, text="Raw only",  variable=self._keys_output_mode, value="raw")
        _keys_om_raw._carl_tooltip_key = "analyses.output_mode_raw"
        _keys_om_raw.grid(row=0, column=9, sticky="w")
        _keys_om_llm = tk.Radiobutton(_keys_bar, text="Raw + LLM", variable=self._keys_output_mode, value="llm")
        _keys_om_llm._carl_tooltip_key = "analyses.output_mode_llm"
        _keys_om_llm.grid(row=0, column=10, sticky="w")
        _keys_om_nlg = tk.Radiobutton(_keys_bar, text="Raw + NLG", variable=self._keys_output_mode, value="nlg")
        _keys_om_nlg._carl_tooltip_key = "analyses.output_mode_nlg"
        _keys_om_nlg.grid(row=0, column=11, sticky="w", padx=(0, 16))
        tk.Label(_keys_bar, text="LLM Mode:").grid(
            row=0, column=12, padx=(0, 4), sticky="w")
        _keys_lm_menu = tk.OptionMenu(_keys_bar, self._keys_llm_mode, "fast", "full")
        _keys_lm_menu._carl_tooltip_key = "analyses.llm_mode_dropdown"
        _keys_lm_menu.grid(row=0, column=13, sticky="w", padx=(0, 8))
        self._keys_verify_rounds = tk.IntVar(value=3)
        tk.Label(_keys_bar, text="Verification rounds:").grid(
            row=0, column=14, padx=(8, 4), sticky="w")
        self._keys_vr_spin = tk.Spinbox(_keys_bar, from_=1, to=5, width=3,
                                        textvariable=self._keys_verify_rounds)
        self._keys_vr_spin.grid(row=0, column=15, sticky="w", padx=(0, 8))
        def _sync_keys_vr(*_):
            # LLM Mode + verification rounds apply only to Raw + LLM.
            is_llm = self._keys_output_mode.get() == "llm"
            _keys_lm_menu.config(state="normal" if is_llm else "disabled")
            self._keys_vr_spin.config(
                state="normal" if (is_llm and self._keys_llm_mode.get() == "full") else "disabled")
        self._keys_llm_mode.trace_add("write", _sync_keys_vr)
        self._keys_output_mode.trace_add("write", _sync_keys_vr)
        _sync_keys_vr()

        self._keys_run_btn = tk.Button(_keys_tab, text="Run", height=2,
                                       command=self._run_keys)
        self._keys_run_btn._carl_tooltip_key = "analyses.run"
        self._keys_run_btn.pack(padx=5, pady=4)
        self._keys_output = _make_output(_keys_tab)

        # ============================================================
        # TAB 4: MULTI-ACCESS KEY
        # ============================================================
        _mak_tab = tk.Frame(_analyses_nb)
        _analyses_nb.add(_mak_tab, text="Multi-Access Key")

        _mak_tab.columnconfigure(0, weight=1)
        _mak_tab.columnconfigure(1, weight=1)
        _mak_tab.columnconfigure(2, weight=1)
        _mak_tab.rowconfigure(1, weight=2)   # listboxes row
        _mak_tab.rowconfigure(5, weight=3)   # taxa listbox row

        # ---- Column headers ----
        tk.Label(_mak_tab, text="Characters",
                 font=self.app_ui_bold).grid(
            row=0, column=0, sticky="w", padx=5, pady=(5, 0))
        tk.Label(_mak_tab, text="States",
                 font=self.app_ui_bold).grid(
            row=0, column=1, sticky="w", padx=5, pady=(5, 0))
        tk.Label(_mak_tab, text="Criteria",
                 font=self.app_ui_bold).grid(
            row=0, column=2, sticky="w", padx=5, pady=(5, 0))

        # ---- Character listbox ----
        _mak_cf = tk.Frame(_mak_tab)
        _mak_cf.grid(row=1, column=0, sticky="nsew", padx=5, pady=2)
        _mak_cf.rowconfigure(0, weight=1)
        _mak_cf.columnconfigure(0, weight=1)
        self._mak_char_list = tk.Listbox(_mak_cf, exportselection=False)
        _mak_c_vsb = ttk.Scrollbar(_mak_cf, orient="vertical",
                                    command=self._mak_char_list.yview)
        self._mak_char_list.configure(yscrollcommand=_mak_c_vsb.set)
        self._mak_char_list.grid(row=0, column=0, sticky="nsew")
        _mak_c_vsb.grid(row=0, column=1, sticky="ns")
        self._mak_char_list.bind("<<ListboxSelect>>", self._mak_on_char_select)

        # ---- State listbox ----
        _mak_sf = tk.Frame(_mak_tab)
        _mak_sf.grid(row=1, column=1, sticky="nsew", padx=5, pady=2)
        _mak_sf.rowconfigure(0, weight=1)
        _mak_sf.columnconfigure(0, weight=1)
        self._mak_state_list = tk.Listbox(_mak_sf, selectmode=tk.MULTIPLE,
                                          exportselection=False)
        _mak_s_vsb = ttk.Scrollbar(_mak_sf, orient="vertical",
                                    command=self._mak_state_list.yview)
        self._mak_state_list.configure(yscrollcommand=_mak_s_vsb.set)
        self._mak_state_list.grid(row=0, column=0, sticky="nsew")
        _mak_s_vsb.grid(row=0, column=1, sticky="ns")

        tk.Button(_mak_tab, text="Add Criterion",
                  command=self._mak_add_criterion).grid(
            row=2, column=1, padx=5, pady=2, sticky="ew")

        # ---- Criteria listbox ----
        _mak_kf = tk.Frame(_mak_tab)
        _mak_kf.grid(row=1, column=2, sticky="nsew", padx=5, pady=2)
        _mak_kf.rowconfigure(0, weight=1)
        _mak_kf.columnconfigure(0, weight=1)
        self._mak_criteria_list = tk.Listbox(_mak_kf, exportselection=False)
        _mak_k_vsb = ttk.Scrollbar(_mak_kf, orient="vertical",
                                    command=self._mak_criteria_list.yview)
        self._mak_criteria_list.configure(yscrollcommand=_mak_k_vsb.set)
        self._mak_criteria_list.grid(row=0, column=0, sticky="nsew")
        _mak_k_vsb.grid(row=0, column=1, sticky="ns")

        _mak_btn_row = tk.Frame(_mak_tab)
        _mak_btn_row.grid(row=2, column=2, padx=5, pady=2, sticky="ew")
        tk.Button(_mak_btn_row, text="Remove Selected",
                  command=self._mak_remove_criterion).pack(side="left", padx=(0, 4))
        tk.Button(_mak_btn_row, text="Clear All",
                  command=self._mak_clear_criteria).pack(side="left")

        # ---- Separator ----
        ttk.Separator(_mak_tab, orient="horizontal").grid(
            row=3, column=0, columnspan=3, sticky="ew", padx=5, pady=4)

        # ---- Candidates label + count ----
        self._mak_candidates_var = tk.StringVar(value="Candidates")
        tk.Label(_mak_tab, textvariable=self._mak_candidates_var,
                 font=self.app_ui_bold, anchor="w").grid(
            row=4, column=0, columnspan=3, sticky="w", padx=5, pady=(0, 2))

        # ---- Taxa listbox (full width) ----
        _mak_tf = tk.Frame(_mak_tab)
        _mak_tf.grid(row=5, column=0, columnspan=3, sticky="nsew", padx=5, pady=(0, 5))
        _mak_tf.rowconfigure(0, weight=1)
        _mak_tf.columnconfigure(0, weight=1)
        self._mak_taxa_list = tk.Listbox(_mak_tf, exportselection=False)
        _mak_t_vsb = ttk.Scrollbar(_mak_tf, orient="vertical",
                                    command=self._mak_taxa_list.yview)
        self._mak_taxa_list.configure(yscrollcommand=_mak_t_vsb.set)
        self._mak_taxa_list.grid(row=0, column=0, sticky="nsew")
        _mak_t_vsb.grid(row=0, column=1, sticky="ns")

        # Initial references for run_action() compatibility
        self.run_btn = self._desc_run_btn
        self.output  = self._desc_output

        _status("Building Information panel...")
        self.root.update_idletasks()

        # ==========================================================
        # INFORMATION PANEL — single split-pane (treeview | report text)
        # ==========================================================

        self.literature_tab.grid_columnconfigure(0, weight=1)
        self.literature_tab.grid_rowconfigure(2, weight=1)

        # --- Button row ---
        lit_btn_frame = tk.Frame(self.literature_tab)
        lit_btn_frame.grid(row=0, column=0, padx=5, pady=5, sticky="ew")

        self.lit_cache_btn = tk.Button(
            lit_btn_frame, text="Fetch All", command=self._info_fetch_all
        )
        self.lit_cache_btn.pack(side="left", padx=(0, 4))

        self.lit_fetch_sel_btn = tk.Button(
            lit_btn_frame, text="Fetch Selected", command=self._info_fetch_selected
        )
        self.lit_fetch_sel_btn.pack(side="left", padx=(0, 10))

        self.lit_cancel_btn = tk.Button(
            lit_btn_frame, text="Cancel", state="disabled",
            command=self._info_cancel_fetch
        )
        self.lit_cancel_btn._carl_tooltip_key = "info.cancel_fetch"
        self.lit_cancel_btn.pack(side="left", padx=(0, 10))

        tk.Button(
            lit_btn_frame, text="Clear All", command=self._info_clear_cache
        ).pack(side="left", padx=(0, 4))

        tk.Button(
            lit_btn_frame, text="Clear Selected", command=self._info_clear_selected
        ).pack(side="left", padx=(0, 10))

        tk.Button(
            lit_btn_frame, text="Export as .txt", command=self._info_export_txt
        ).pack(side="left", padx=(0, 10))

        tk.Button(
            lit_btn_frame, text="Export DC…", command=self._export_lit_csv
        ).pack(side="left")

        # --- Status label ---
        self.lit_status_var = tk.StringVar(value="No file loaded.")
        tk.Label(
            self.literature_tab, textvariable=self.lit_status_var,
            anchor="w", fg="blue"
        ).grid(row=1, column=0, padx=5, pady=(0, 2), sticky="ew")

        # --- Main horizontal PanedWindow (row 2) ---
        lit_paned = tk.PanedWindow(
            self.literature_tab, orient="horizontal",
            sashwidth=5, sashrelief="flat"
        )
        lit_paned.grid(row=2, column=0, padx=5, pady=(0, 5), sticky="nsew")

        # ── Left: treeview ──────────────────────────────────────────
        lit_left = tk.Frame(lit_paned)
        lit_left.grid_rowconfigure(0, weight=1)
        lit_left.grid_columnconfigure(0, weight=1)
        lit_paned.add(lit_left, minsize=250)

        lit_tree_frame = tk.Frame(lit_left)
        lit_tree_frame.grid(row=0, column=0, sticky="nsew")
        lit_tree_frame.grid_rowconfigure(0, weight=1)
        lit_tree_frame.grid_columnconfigure(0, weight=1)

        _pad = self.app_ui_font.measure("W") * 2
        self.lit_tree = ttk.Treeview(
            lit_tree_frame,
            columns=("status", "retrieved", "comments"),
            show="tree headings",
            selectmode="extended"
        )
        self.lit_tree.heading("#0",        text="Taxon")
        self.lit_tree.heading("status",    text="Status")
        self.lit_tree.heading("retrieved", text="Retrieved")
        self.lit_tree.heading("comments",  text="Comments")
        self.lit_tree.column("#0",        width=self.app_ui_font.measure("W" * 24),          stretch=False)
        self.lit_tree.column("status",    width=self.app_ui_font.measure("fetched") + _pad,   stretch=False)
        self.lit_tree.column("retrieved", width=self.app_ui_font.measure("2026-05-16") + _pad, stretch=False)
        self.lit_tree.column("comments",  stretch=True)

        self.lit_tree.tag_configure("fetched",      foreground="#2e7d32")
        self.lit_tree.tag_configure("partial",      foreground="#e65100")
        self.lit_tree.tag_configure("error",        foreground="#c62828")
        self.lit_tree.tag_configure("pending",      foreground="#757575")
        self.lit_tree.tag_configure("group_taxon",  background="#f3e5f5")
        self.lit_tree.tag_configure("group_header", font=self.app_ui_bold)
        self.lit_tree.tag_configure("greyed",       foreground="#999999")
        self.lit_tree.tag_configure("ref_member",   foreground="#666666", font=self.app_ui_font)
        self.lit_tree.tag_configure("conflict",     background="#fff8e1")

        self.lit_tree.bind("<<TreeviewSelect>>", self._on_lit_select)
        self.lit_tree.bind("<Button-3>",          self._on_lit_right_click)
        self.lit_tree.bind("<Double-1>",          self._on_lit_dblclick)

        lit_scroll = ttk.Scrollbar(lit_tree_frame, orient="vertical",
                                    command=self.lit_tree.yview)
        self.lit_tree.configure(yscrollcommand=lit_scroll.set)
        self.lit_tree.grid(row=0, column=0, sticky="nsew")
        lit_scroll.grid(row=0, column=1, sticky="ns")

        # ── Right: sandbox-style report text ────────────────────────
        lit_right = tk.Frame(lit_paned)
        lit_right.grid_rowconfigure(0, weight=1)
        lit_right.grid_columnconfigure(0, weight=1)
        lit_paned.add(lit_right, minsize=350)

        self._info_report_text = tk.Text(
            lit_right, wrap="word", state="disabled",
            font=self.app_mono_font, padx=6, pady=6
        )
        _info_rts = ttk.Scrollbar(lit_right, orient="vertical",
                                   command=self._info_report_text.yview)
        self._info_report_text.configure(yscrollcommand=_info_rts.set)
        self._info_report_text.grid(row=0, column=0, sticky="nsew")
        _info_rts.grid(row=0, column=1, sticky="ns")

        _status("Building Chatbot panel...")
        self.root.update_idletasks()

        # ==========================================================
        # CHATBOT PANEL — full-width chat interface
        # ==========================================================

        _cp = self._chat_panel_frame
        _cp.grid_columnconfigure(0, weight=1)
        _cp.grid_columnconfigure(1, weight=1)
        _cp.grid_rowconfigure(1, weight=1)

        # Column headers
        tk.Label(_cp, text="Your Query", font=self.app_ui_bold).grid(
            row=0, column=0, sticky="w", padx=(10, 5), pady=(8, 2))
        tk.Label(_cp, text="CARL", font=self.app_ui_bold).grid(
            row=0, column=1, sticky="w", padx=(5, 10), pady=(8, 2))

        # Left pane — user input + buttons
        _left_pane = tk.Frame(_cp)
        _left_pane.grid(row=1, column=0, sticky="nsew", padx=(10, 5), pady=(0, 10))
        _left_pane.grid_rowconfigure(0, weight=1)
        _left_pane.grid_columnconfigure(0, weight=1)

        _input_text_frame = tk.Frame(_left_pane)
        _input_text_frame.grid(row=0, column=0, columnspan=2, sticky="nsew")
        _input_text_frame.grid_rowconfigure(0, weight=1)
        _input_text_frame.grid_columnconfigure(0, weight=1)

        self.chat_input = tk.Text(_input_text_frame, wrap="word", font=self.app_reading_font)
        self.chat_input.grid(row=0, column=0, sticky="nsew")
        _chat_in_scroll = tk.Scrollbar(_input_text_frame, command=self.chat_input.yview)
        _chat_in_scroll.grid(row=0, column=1, sticky="ns")
        self.chat_input.config(yscrollcommand=_chat_in_scroll.set)

        _btn_row = tk.Frame(_left_pane)
        _btn_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        tk.Button(_btn_row, text="Send",       width=10, command=self.send_chat_message).pack(side="left", padx=(0, 4))
        tk.Button(_btn_row, text="Clear Chat", width=10, command=self.clear_chat).pack(side="left", padx=4)
        tk.Button(_btn_row, text="Copy Chat",  width=10, command=self.copy_chat).pack(side="left", padx=4)

        _status("Loading nomenclatural code indices...")
        self.root.update_idletasks()

        # RAG code selector — only show codes whose index files exist on disk.
        # Defined here directly to avoid importing rag_retrieval (faiss + sentence_transformers)
        # at startup; those heavy deps load lazily the first time the chatbot uses RAG.
        _RAG_INDEX_FILES = {
            "iczn":  "iczn_index.faiss",
            "icn":   "icn_index.faiss",
            "icnp":  "icnp_index.faiss",
            "icvcn": "icvcn_index.faiss",
        }
        _available = [code for code, f in _RAG_INDEX_FILES.items() if os.path.exists(f)]
        self.rag_code_var = tk.StringVar(value="None")
        self.rag_k_var    = tk.IntVar(value=12)
        if _available:
            tk.Label(_btn_row, text="Code:").pack(side="left", padx=(12, 2))
            _rag_cb = ttk.Combobox(
                _btn_row, textvariable=self.rag_code_var,
                values=["None"] + _available,
                state="readonly", width=8,
            )
            _rag_cb.pack(side="left")
            tk.Label(_btn_row, text="k:").pack(side="left", padx=(8, 2))
            tk.Spinbox(
                _btn_row, textvariable=self.rag_k_var,
                from_=1, to=30, width=3, state="readonly",
            ).pack(side="left")

        self.chat_memory_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            _btn_row, text="Memory", variable=self.chat_memory_var,
        ).pack(side="left", padx=(12, 0))

        self.chat_status_var = tk.StringVar(value="")
        tk.Label(
            _btn_row, textvariable=self.chat_status_var,
            fg="gray", font=self.app_ui_italic,
        ).pack(side="left", padx=(8, 0))

        self.chat_input.bind("<Return>", lambda event: "break")

        # Right pane — chat history
        _right_pane = tk.Frame(_cp)
        _right_pane.grid(row=1, column=1, sticky="nsew", padx=(5, 10), pady=(0, 10))
        _right_pane.grid_rowconfigure(0, weight=1)
        _right_pane.grid_columnconfigure(0, weight=1)

        self.chat_history = tk.Text(_right_pane, wrap="word", state="disabled", bg="white", font=self.app_reading_font)
        self.chat_history.grid(row=0, column=0, sticky="nsew")
        _chat_hist_scroll = tk.Scrollbar(_right_pane, command=self.chat_history.yview)
        _chat_hist_scroll.grid(row=0, column=1, sticky="ns")
        self.chat_history.config(yscrollcommand=_chat_hist_scroll.set)
        self.chat_history.tag_configure("rag_sep", wrap="none")

        _status("Building LLM settings...")
        self.root.update_idletasks()

        # ==========================================================
        # SETTINGS PANEL — LM Settings tab
        # ==========================================================

        _lf_outer = self._llm_settings_tab
        _lf_outer.grid_rowconfigure(0, weight=1)
        _lf_outer.grid_columnconfigure(0, weight=1)
        _lf_canvas = tk.Canvas(_lf_outer, highlightthickness=0)
        _lf_canvas.grid(row=0, column=0, sticky="nsew")
        _lf_vsb = ttk.Scrollbar(_lf_outer, orient="vertical", command=_lf_canvas.yview)
        _lf_vsb.grid(row=0, column=1, sticky="ns")
        _lf_canvas.configure(yscrollcommand=_lf_vsb.set)
        _lf = tk.Frame(_lf_canvas)
        _lf_id = _lf_canvas.create_window((0, 0), window=_lf, anchor="nw")
        _lf.bind("<Configure>", lambda e: _lf_canvas.configure(scrollregion=_lf_canvas.bbox("all")))
        _lf_canvas.bind("<Configure>", lambda e: _lf_canvas.itemconfigure(_lf_id, width=e.width))
        _lf.bind("<Enter>", lambda e: _lf_canvas.bind_all(
            "<MouseWheel>", lambda ev: _lf_canvas.yview_scroll(int(-1*(ev.delta/120)), "units")))
        _lf.bind("<Leave>", lambda e: _lf_canvas.unbind_all("<MouseWheel>"))
        _lf.grid_columnconfigure(0, minsize=130)
        _lf.grid_columnconfigure(1, weight=1)

        # ── API Keys ──────────────────────────────────────────────
        _ak_frame = ttk.LabelFrame(_lf, text="API Keys", padding=(10, 6))
        _ak_frame.grid(row=0, column=0, columnspan=3, sticky="w", padx=10, pady=(10, 6))

        _provider_labels = [
            ("groq",        "Groq"),
            ("openai",      "OpenAI"),
            ("anthropic",   "Anthropic"),
            ("google",      "Google"),
            ("huggingface", "HuggingFace"),
            ("openrouter",  "OpenRouter"),
        ]
        for _ri, (_pkey, _plabel) in enumerate(_provider_labels):
            tk.Label(_ak_frame, text=f"{_plabel}:", anchor="w", width=12).grid(
                row=_ri, column=0, sticky="w", padx=(0, 4), pady=2)
            _entry = ttk.Entry(_ak_frame, textvariable=self._api_key_vars[_pkey],
                               show="*", width=45)
            _entry.grid(row=_ri, column=1, sticky="w", pady=2)
            def _make_toggle(e=_entry):
                return lambda: e.config(show="" if e.cget("show") == "*" else "*")
            ttk.Button(_ak_frame, text="Show", command=_make_toggle(), width=5).grid(
                row=_ri, column=2, padx=(4, 0), pady=2)

        _or_free_row = len(_provider_labels)
        ttk.Checkbutton(
            _ak_frame, text="Free models only (OpenRouter)",
            variable=self._openrouter_free_only_var,
            command=self._apply_openrouter_free_only,
        ).grid(row=_or_free_row, column=1, sticky="w", pady=(2, 0))

        ttk.Button(
            _ak_frame, text="Save API Keys",
            command=self._save_api_keys,
        ).grid(row=_or_free_row + 1, column=0, columnspan=2, pady=(8, 2), sticky="w")

        # ── OUTPUT (Generation) ───────────────────────────────────
        tk.Label(_lf, text="OUTPUT (Generation)", font=self.app_ui_bold).grid(
            row=2, column=0, columnspan=2, sticky="w", padx=10, pady=(12, 4))

        tk.Label(_lf, text="Model:").grid(row=3, column=0, sticky="w", padx=10)
        self.output_model_dropdown = ttk.Combobox(_lf, textvariable=self.output_model_var, width=45, state="normal")
        self.output_model_dropdown.grid(row=3, column=1, sticky="w", pady=2)

        tk.Label(_lf, text="Temperature:").grid(row=4, column=0, sticky="w", padx=10)
        ttk.Entry(_lf, textvariable=self.output_temp_var, width=22).grid(row=4, column=1, sticky="w", pady=2)

        tk.Label(_lf, text="Style Guide:").grid(row=5, column=0, sticky="w", padx=10)
        _sg_entry = ttk.Entry(_lf, textvariable=self.style_guide_path_var, width=45)
        _sg_entry._carl_tooltip_key = "lm.style_guide_entry"
        _sg_entry.grid(row=5, column=1, sticky="w", pady=2)
        _sg_browse = ttk.Button(_lf, text="Browse…", command=self.browse_style_guide)
        _sg_browse._carl_tooltip_key = "lm.style_guide_browse"
        _sg_browse.grid(row=6, column=1, sticky="w")

        # ── VERIFICATION (Full Mode) ──────────────────────────────
        tk.Label(_lf, text="VERIFICATION (Full Mode)", font=self.app_ui_bold).grid(
            row=8, column=0, columnspan=2, sticky="w", padx=10, pady=(12, 4))

        tk.Label(_lf, text="Model:").grid(row=9, column=0, sticky="w", padx=10)
        self.verify_model_dropdown = ttk.Combobox(_lf, textvariable=self.verify_model_var, width=45, state="normal")
        self.verify_model_dropdown.grid(row=9, column=1, sticky="w", pady=2)

        tk.Label(_lf, text="Temperature:").grid(row=10, column=0, sticky="w", padx=10)
        ttk.Entry(_lf, textvariable=self.verify_temp_var, width=22).grid(row=10, column=1, sticky="w", pady=2)

        tk.Label(_lf, text="Max Tokens:").grid(row=11, column=0, sticky="w", padx=10)
        ttk.Entry(_lf, textvariable=self.verify_max_tokens_var, width=22).grid(row=11, column=1, sticky="w", pady=2)

        # ── CARL (Chatbot) ────────────────────────────────────────
        tk.Label(_lf, text="CARL (Chatbot)", font=self.app_ui_bold).grid(
            row=13, column=0, columnspan=2, sticky="w", padx=10, pady=(12, 4))

        tk.Label(_lf, text="Model:").grid(row=14, column=0, sticky="w", padx=10)
        self.chat_model_dropdown = ttk.Combobox(_lf, textvariable=self.chat_model_var, width=45, state="normal")
        self.chat_model_dropdown.grid(row=14, column=1, sticky="w", pady=2)

        # ── Local server ports ────────────────────────────────────
        tk.Label(_lf, text="Local server ports:").grid(
            row=18, column=0, sticky="w", padx=10, pady=(10, 0))
        self._local_ports_var = tk.StringVar(value="1234, 1337, 8000, 8080")
        _ports_entry = tk.Entry(_lf, textvariable=self._local_ports_var, width=30)
        _ports_entry.grid(row=18, column=1, sticky="w", pady=(10, 0))
        tk.Label(_lf, text="Comma-separated ports for LM Studio, Jan, LocalAI, llama.cpp.\n"
                           "Leave empty to skip local server probing.",
                 fg="#666", justify="left").grid(
            row=18, column=1, sticky="w", padx=(240, 0), pady=(10, 0))

        # ── Buttons ───────────────────────────────────────────────
        _btn_row = tk.Frame(_lf)
        _btn_row.grid(row=19, column=0, columnspan=2, sticky="w", padx=10, pady=(8, 2))
        ttk.Button(_btn_row, text="Fetch Models",
                   command=self.fetch_models).pack(side="left")

        # ── Model Test ────────────────────────────────────────────
        tk.Label(_lf, text="MODEL TEST", font=self.app_ui_bold).grid(
            row=21, column=0, columnspan=2, sticky="w", padx=10, pady=(12, 4))

        _test_row = tk.Frame(_lf)
        _test_row.grid(row=22, column=0, columnspan=2, sticky="w", padx=10, pady=2)

        self.test_model_dropdown = ttk.Combobox(
            _test_row, textvariable=self.test_model_var, width=45, state="normal")
        self.test_model_dropdown._carl_tooltip_key = "lm.model_test_dropdown"
        self.test_model_dropdown.grid(row=0, column=0, sticky="w", padx=(0, 6))

        self._test_btn = ttk.Button(_test_row, text="Test Model", command=self._test_model)
        self._test_btn.grid(row=0, column=1, sticky="e")

        self._test_response_text = tk.Text(
            _lf, height=3, wrap="word", state="disabled",
            font=self.app_mono_font, padx=4, pady=4, width=45)
        self._test_response_text.grid(
            row=23, column=0, columnspan=2, sticky="w", padx=10, pady=(2, 4))

        ttk.Button(_lf, text="Reset to Defaults", command=self.reset_to_defaults).grid(
            row=999, column=0, columnspan=2, padx=10, pady=(6, 10), sticky="w")

        self.analysis_raw_output = ""

        self.root.update()


        # ----------------------------------------------------------
        # WARM UP THE LLM AFTER UI INITIALIZATION
        # ----------------------------------------------------------


        _status("Loading saved settings...")
        self.root.update_idletasks()

        self.fetch_models()
        self.root.after(500, self.warm_up_llm)
        self.load_settings()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self.introduce_carl)  #--- delete this if we remove all Chat functionality

    def animate_thinking(self):
        if not self.thinking or not self.thinking_index:
            return

        self.thinking_dots = (self.thinking_dots + 1) % 4
        dots = "." * self.thinking_dots

        self.chat_history.config(state="normal")

        start = self.thinking_index
        end = f"{start} lineend"

        # Replace entire line cleanly
        self.chat_history.delete(start, end)
        self.chat_history.insert(start, f"Carl: Thinking{dots}")

        self.chat_history.config(state="disabled")
        self.chat_history.see(tk.END)

        self.thinking_job = self.chat_history.after(400, self.animate_thinking)


    def on_close(self):
        self.save_settings()
        try:
            tc = getattr(self, "_tooltip_controller", None)
            if tc is not None:
                tc.teardown()
        except Exception:
            pass
        try:
            self.root.destroy()
        except tk.TclError:
            # A stray Tcl command can break the destroy cascade; ensure we still exit.
            try:
                self.root.quit()
            except Exception:
                pass

    # -------------------------
    # FOLDER SETTINGS HELPERS
    # -------------------------

    def _wd_kwargs(self):
        """Return {"initialdir": path} when a working directory is set, else {}."""
        _wd = self._pref_working_dir_var.get().strip()
        return {"initialdir": _wd} if _wd else {}

    def _apply_openrouter_free_only(self):
        from llm_interface import set_openrouter_free_only
        set_openrouter_free_only(self._openrouter_free_only_var.get())

    def _save_api_keys(self):
        """Save API keys to settings and push to llm_interface."""
        from llm_interface import set_api_keys
        set_api_keys({p: v.get() for p, v in self._api_key_vars.items()})
        self._apply_openrouter_free_only()
        self.save_settings()
        messagebox.showinfo("Saved", "API keys saved.")

    def save_settings(self):
        settings = {
            "output_model": self.output_model_var.get(),
            "output_temp": self.output_temp_var.get(),

            "verify_model": self.verify_model_var.get(),
            "verify_temp": self.verify_temp_var.get(),
            "verify_max_tokens": self.verify_max_tokens_var.get(),
            "style_guide": self.style_guide_path_var.get(),
            "verify_style_guide": self.verify_style_guide_path_var.get(),

            "chat_model": self.chat_model_var.get(),

            "api_keys": {p: v.get() for p, v in self._api_key_vars.items()},
            "openrouter_free_only": self._openrouter_free_only_var.get(),
            "bhl_api_key": self._bhl_api_key_var.get(),
            "wsc_api_key": self._wsc_api_key_var.get(),

            "lit_retrieve_fields": sorted(self._lit_retrieve_fields),
            "lit_include_fields":  sorted(self._lit_include_fields),
            "lit_providers":       self._lit_provider_settings,
            "db_limits": {key: self._db_limit_vars[key].get()
                          for key, *_ in _DB_LIMITS},

            "working_dir": self._pref_working_dir_var.get(),

            "keys_algo":    self._keys_algo_var.get(),
            "keys_format":  self._keys_format_var.get(),
            "keys_penalty": self._keys_penalty_var.get(),

            "ui_font_size":   self._pref_ui_font_size.get(),
            "mono_font_size": self._pref_mono_font_size.get(),

            "local_ports": self._local_ports_var.get(),
        }

        with open(SETTINGS_FILE, "w") as f:
            json.dump(settings, f, indent=2)

        set_wsc_api_key(self._wsc_api_key_var.get())

    def load_settings(self):
        settings = None

        # ----------------------------------
        # 1. Try to load saved settings
        # ----------------------------------
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r") as f:
                    settings = json.load(f)
            except Exception as e:
                print(f"[WARNING] Failed to load settings: {e}")

        # ----------------------------------
        # 2. If no saved settings → use defaults
        # ----------------------------------
        if settings is None:
            settings = DEFAULT_SETTINGS.copy()

            # Apply config overrides (models only)
            try:
                if DEFAULT_MODELS.get("output"):
                    settings["output_model"] = DEFAULT_MODELS["output"]
            except Exception:
                pass

            try:
                if DEFAULT_MODELS.get("verification"):
                    settings["verify_model"] = DEFAULT_MODELS["verification"]
            except Exception:
                pass

            try:
                if DEFAULT_MODELS.get("chat"):
                    settings["chat_model"] = DEFAULT_MODELS["chat"]
            except Exception:
                pass

        # ----------------------------------
        # 3. Apply settings to UI
        # ----------------------------------
        self.output_model_var.set(settings.get("output_model", ""))
        self.output_temp_var.set(settings.get("output_temp", 0.2))

        self.verify_model_var.set(settings.get("verify_model", ""))
        self.verify_temp_var.set(settings.get("verify_temp", 0.0))
        self.verify_max_tokens_var.set(settings.get("verify_max_tokens", 4096))

        self.style_guide_path_var.set(settings.get("style_guide", ""))
        self.verify_style_guide_path_var.set(settings.get("verify_style_guide", ""))

        self.chat_model_var.set(settings.get("chat_model", get_default_model("chat", "llama3.2:1b")))

        # Literature field and provider settings
        rf = settings.get("lit_retrieve_fields")
        self._lit_retrieve_fields = set(rf) if rf is not None else set(DEFAULT_FIELDS)

        inf = settings.get("lit_include_fields")
        self._lit_include_fields = set(inf) if inf is not None else set(DEFAULT_INCLUDE_FIELDS)

        saved_providers = settings.get("lit_providers", {})
        self._lit_provider_settings = {
            p: saved_providers.get(p, {
                "enabled":  _ALL_PROVIDER_META[p]["default_enabled"],
                "priority": i + 1,
            })
            for i, p in enumerate(DEFAULT_PROVIDER_ORDER)
        }

        # DB retrieval limits
        saved_limits = settings.get("db_limits", {})
        for key, _label, default, _attr in _DB_LIMITS:
            self._db_limit_vars[key].set(saved_limits.get(key, default))

        # BHL / WSC API keys
        self._bhl_api_key_var.set(
            settings.get("bhl_api_key", ""))
        self._wsc_api_key_var.set(settings.get("wsc_api_key", ""))
        set_wsc_api_key(self._wsc_api_key_var.get())

        # Sync Literature settings UI widgets (field checkboxes + provider spinboxes)
        self._refresh_lit_settings_ui()

        # Working directory
        self._pref_working_dir_var.set(settings.get("working_dir", ""))

        # API keys — load into StringVars and push to llm_interface
        saved_keys = settings.get("api_keys", {})
        for p, var in self._api_key_vars.items():
            var.set(saved_keys.get(p, ""))
        from llm_interface import set_api_keys, set_openrouter_free_only
        set_api_keys({p: v.get() for p, v in self._api_key_vars.items()})
        self._openrouter_free_only_var.set(settings.get("openrouter_free_only", True))
        set_openrouter_free_only(self._openrouter_free_only_var.get())

        # Keys tab settings
        self._keys_algo_var.set(settings.get("keys_algo", "ig"))
        self._keys_format_var.set(settings.get("keys_format", "binary"))
        self._keys_penalty_var.set(settings.get("keys_penalty", "0.05"))

        # Font preferences — resolve 0 (sentinel / first run) to actual current size.
        _actual_ui   = self.app_ui_font.cget("size")
        _actual_mono = self.app_mono_font.cget("size")
        _saved_ui   = settings.get("ui_font_size",   0)
        _saved_mono = settings.get("mono_font_size", 0)
        self._pref_ui_font_size.set(_saved_ui   if _saved_ui   >= 7 else _actual_ui)
        self._pref_mono_font_size.set(_saved_mono if _saved_mono >= 7 else _actual_mono)
        self._apply_font_prefs(_save=False)

        self._local_ports_var.set(settings.get("local_ports", "1234, 1337, 8000, 8080"))


    def _apply_font_prefs(self, _save=True):
        """Apply Preferences > Font Sizes spinbox values to all font objects and system fonts."""
        ui_sz   = max(7, self._pref_ui_font_size.get())
        mono_sz = max(7, self._pref_mono_font_size.get())

        # Update system named fonts so widgets without explicit font= also update.
        for _fname in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkFont.nametofont(_fname).configure(size=ui_sz)
            except Exception:
                pass

        # Update our named font objects.
        self.app_ui_font.configure(size=ui_sz)
        self.app_ui_bold.configure(size=ui_sz)
        self.app_ui_italic.configure(size=ui_sz)
        self.app_mono_font.configure(size=mono_sz)
        self.app_reading_font.configure(size=ui_sz + 2)

        # Re-apply Notebook tab / nav bar styles with the new size (ttk styles are not live).
        _style = ttk.Style()
        _style.map("TNotebook.Tab",
                   font=[("selected", ("TkDefaultFont", ui_sz, "bold")),
                         ("!selected", ("TkDefaultFont", ui_sz))])
        _style.configure("Nav.TButton", font=("TkDefaultFont", ui_sz, "bold"))
        _style.configure("NavActive.TButton", font=("TkDefaultFont", ui_sz, "bold"))

        # Force-refresh Text widgets — on Windows, tk.Text can lag after a Font.configure().
        for _w, _f in (
            (self._desc_output,           self.app_mono_font),
            (self._comp_output,           self.app_mono_font),
            (self._keys_output,           self.app_mono_font),
            (self._nom_preview_text,      self.app_mono_font),
            (self._info_report_text,      self.app_mono_font),
            (self._test_response_text,    self.app_mono_font),
            (self.chat_input,             self.app_reading_font),
            (self.chat_history,           self.app_reading_font),
        ):
            try:
                _w.configure(font=_f)
            except Exception:
                pass

        # Plugins panel owns its own mono-font widgets (incl. dynamic ones).
        try:
            self._plugins_panel.refresh_fonts()
        except Exception:
            pass

        # Refresh Editor canvas scroll region so row heights reflow after font resize.
        try:
            self._editor_canvas.configure(
                scrollregion=self._editor_canvas.bbox("all"))
        except Exception:
            pass

        if _save:
            self.save_settings()

    def reset_to_defaults(self):
        confirm = messagebox.askyesno(
            "Reset Settings",
            "Are you sure you want to reset all LLM settings to defaults?"
        )

        if not confirm:
            return

        d = DEFAULT_SETTINGS

        self.output_model_var.set(
            get_default_model("output", d["output_model"]))
        self.output_temp_var.set(d["output_temp"])

        self.verify_model_var.set(
            get_default_model("verification", d["verify_model"]))
        self.verify_temp_var.set(d["verify_temp"])
        self.verify_max_tokens_var.set(d["verify_max_tokens"])
        self.style_guide_path_var.set(d["style_guide"])
        self.verify_style_guide_path_var.set(d["verify_style_guide"])

        self.chat_model_var.set(
            get_default_model("chat", d["chat_model"]))

        self.save_settings()
        self.status_var.set("Settings reset to defaults")

    def _update_all_dropdowns(self):
        """Merge cloud + Ollama models and populate all model Comboboxes."""
        merged = ["None"] + list(dict.fromkeys(
            getattr(self, "_cloud_models", []) + self.available_models
        ))
        self.output_model_dropdown["values"] = merged
        self.verify_model_dropdown["values"] = merged
        self.chat_model_dropdown["values"]   = merged
        self.test_model_dropdown["values"]   = merged

    @staticmethod
    def _llm_model_is_set(model: str) -> bool:
        """Return True if model is a real selection (not empty or the sentinel 'None')."""
        return bool(model) and model != "None"

    def fetch_models(self):
        """Fetch all available models: Ollama, other local servers, and cloud providers."""
        import requests as _requests
        from llm_interface import fetch_all_provider_models

        def _worker():
            self.root.after(0, lambda: self.status_var.set("Fetching models…"))
            self.root.after(0, lambda: self._on_status_callback("Fetching models..."))
            local_models = []

            # 1. Ollama — lists all pulled models regardless of whether any are loaded
            try:
                result = subprocess.run(
                    ["ollama", "list"],
                    capture_output=True, text=True, check=True,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
                for line in result.stdout.strip().split("\n")[1:]:
                    parts = line.split()
                    if parts:
                        local_models.append(parts[0])
            except Exception:
                pass

            # 2. Other local OpenAI-compatible servers (LM Studio, Jan, LocalAI, llama.cpp)
            # Ports come from Settings > LM Settings; empty string = skip entirely.
            _raw_ports = self._local_ports_var.get().strip()
            _ports = []
            if _raw_ports:
                for _p in _raw_ports.split(","):
                    try:
                        _ports.append(int(_p.strip()))
                    except ValueError:
                        pass

            def _probe_port(port):
                try:
                    resp = _requests.get(
                        f"http://localhost:{port}/v1/models", timeout=0.5)
                    if resp.status_code == 200:
                        data  = resp.json()
                        items = data.get("data", []) if isinstance(data, dict) else data
                        return [m.get("id") if isinstance(m, dict) else str(m)
                                for m in items]
                except Exception:
                    pass
                return []

            if _ports:
                import concurrent.futures as _cf
                with _cf.ThreadPoolExecutor(max_workers=len(_ports)) as _pool:
                    for _ids in _pool.map(_probe_port, _ports):
                        for mid in _ids:
                            if mid and mid not in local_models:
                                local_models.append(mid)

            # 3. Cloud providers (parallel fetch, one per stored API key)
            keys  = {p: v.get() for p, v in self._api_key_vars.items()}
            cloud = fetch_all_provider_models(keys)

            config_models = [m for m in DEFAULT_MODELS.values() if m]

            def _done():
                self.available_models = list(dict.fromkeys(local_models + config_models))
                self._cloud_models    = cloud
                self._update_all_dropdowns()
                parts = []
                if local_models:
                    parts.append(f"{len(local_models)} local")
                if cloud:
                    parts.append(f"{len(cloud)} cloud")
                self.status_var.set(
                    f"Models fetched: {', '.join(parts)}." if parts
                    else "No models found — check Ollama installation and API keys."
                )

            self.root.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _test_model(self):
        """Send a minimal prompt to the selected model and show the response."""
        model = self.test_model_var.get().strip()
        if not model:
            self._test_response_text.config(state="normal")
            self._test_response_text.delete("1.0", tk.END)
            self._test_response_text.insert(tk.END, "Select a model first.")
            self._test_response_text.config(state="disabled")
            return

        self._test_btn.config(state="disabled")
        self._test_response_text.config(state="normal")
        self._test_response_text.delete("1.0", tk.END)
        self._test_response_text.insert(tk.END, f"Testing {model}…")
        self._test_response_text.config(state="disabled")

        def _worker():
            from llm_interface import call_llm
            _last_error: list[str] = []
            cfg = LLMConfig(model=model, temperature=0.5, num_predict=15)
            result = call_llm("Hello", cfg, status_fn=lambda msg: _last_error.append(msg))
            def _done():
                self._test_response_text.config(state="normal")
                self._test_response_text.delete("1.0", tk.END)
                display = result or (_last_error[-1] if _last_error else "(no response)")
                self._test_response_text.insert(tk.END, display)
                self._test_response_text.config(state="disabled")
                self._test_btn.config(state="normal")
            self.root.after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def browse_style_guide(self):
        path = filedialog.askopenfilename(
            title="Select Style Guide",
            filetypes=[("Markdown files", "*.md"), ("All files", "*.*")]
        )
        if path:
            self.style_guide_path_var.set(path)


    def load_style_guide_from_path(self, path: str) -> str:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
        except Exception as e:
            print(f"[Style guide load error] {e}")
        return ""

    def warm_up_llm(self):
        """
        Preload the LLMs to avoid cold-start delays.
        Runs in a background thread and updates the UI.
        """
        def worker():
            try:
                # Update UI to indicate warm-up
                self.analysis_tab.after(0, lambda: self.status_var.set("Warming up LLM..."))
                self.root.after(0, lambda: self._on_status_callback("Warming up LLM..."))
                self.analysis_tab.after(0, self.progress.start)

                # ----------------------------------
                # MAP MODELS TO ROLES (NEW)
                # ----------------------------------
                role_map = {
                    "output": self.output_model_var.get(),
                    "verifier": self.verify_model_var.get(),
                    "chatbot": self.chat_model_var.get(),
                }

                # Remove empty/unset roles ("None" sentinel and empty string)
                role_map = {role: model for role, model in role_map.items()
                            if self._llm_model_is_set(model)}

                # Reverse mapping: model → roles
                model_to_roles = {}
                for role, model in role_map.items():
                    model_to_roles.setdefault(model, []).append(role)

                # Unique models (preserve order)
                models = list(dict.fromkeys(model_to_roles.keys()))

                # ----------------------------------
                # WARM EACH MODEL ONCE
                # ----------------------------------
                for i, model in enumerate(models, 1):
                    roles = ", ".join(model_to_roles[model])

                    self.analysis_tab.after(
                        0,
                        lambda m=model, r=roles, i=i: self.status_var.set(
                            f"Warming {m} for {r} ({i}/{len(models)})..."
                        )
                    )
                    self.root.after(
                        0,
                        lambda m=model, i=i, n=len(models):
                            self._on_status_callback(f"Warming up model {i}/{n}...")
                    )

                    config = LLMConfig(
                        model=model,
                        temperature=0.0,
                        num_predict=10
                    )

                    call_llm("Respond with the single word: Ready.", config)

                # ----------------------------------
                # FINAL STATUS MESSAGE (NEW)
                # ----------------------------------
                role_descriptions = []
                for role, model in role_map.items():
                    role_descriptions.append(f"{role.capitalize()} ({model})")

                final_msg = ", ".join(role_descriptions) + " ready"

                self.analysis_tab.after(0, lambda: self.status_var.set(final_msg))

            except Exception as e:
                msg = f"LLM warm-up failed: {e}"
                self.analysis_tab.after(
                    0,
                    lambda: self.status_var.set(msg)
                )

            finally:
                # Stop the progress bar
                self.analysis_tab.after(0, self.progress.stop)
                # Guarantee splash shows for at least 3 seconds
                # WITH:
                self.root.after(0, lambda: self._on_status_callback("Ready."))
                if self._on_ready_callback:
                    self.root.after(0, self._on_ready_callback)

        # Run warm-up in a background thread
        threading.Thread(target=worker, daemon=True).start()



    # ------------------------------------------------------------------
    # Navigation bar
    # ------------------------------------------------------------------

    _NAV_ITEMS = [
        ("file",        "File"),
        ("information", "Information"),
        ("analyses",    "Analyses"),
        ("chatbot",     "Chatbot"),
        ("plugins",     "Plugins"),
        ("settings",    "Settings"),
        ("about",       "About"),
    ]
    _NAV_BG        = "#2c3e50"
    _NAV_BTN_FG    = "#ecf0f1"
    _NAV_ACTIVE_BG = "#3498db"
    _NAV_ACTIVE_FG = "#ffffff"

    def _build_nav_bar(self):
        for key, label in self._NAV_ITEMS:
            btn = ttk.Button(
                self._nav_frame,
                text=label,
                style="Nav.TButton",
                cursor="hand2",
                command=lambda k=key: self._show_panel(k),
            )
            btn.pack(side="left")
            self._nav_buttons[key] = btn

    def _show_panel(self, name):
        for key, frame in self._panels.items():
            frame.grid_remove()
        self._panels[name].grid()
        for key, btn in self._nav_buttons.items():
            btn.configure(style="NavActive.TButton" if key == name else "Nav.TButton")

    def _bind_keyboard_shortcuts(self):
        modifier = "Command" if self.root.tk.call('tk', 'windowingsystem') == 'aqua' else "Control"
        self.root.bind_all(f"<{modifier}-o>", lambda e: self.load_file())
        self.root.bind_all(f"<{modifier}-O>", lambda e: self.load_file())
        self.root.bind_all(f"<{modifier}-q>", lambda e: self.root.quit())
        self.root.bind_all(f"<{modifier}-Q>", lambda e: self.root.quit())

    # ------------------------------------------------------------------
    # Shared helpers for character-state popups
    # ------------------------------------------------------------------

    def _build_states_canvas(self, outer, num_w=36):
        """Create the scrollable canvas + inner frame used by state popups.

        Returns (canvas, inner, canvas_win, name_labels, state_labels).
        The name_labels / state_labels lists are updated in-place by
        _fill_states_table so resize callbacks stay current automatically.
        """
        canvas = tk.Canvas(outer, highlightthickness=0)
        canvas.grid(row=1, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        vsb.grid(row=1, column=1, sticky="ns")
        canvas.configure(yscrollcommand=vsb.set)

        inner = tk.Frame(canvas)
        canvas_win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.grid_columnconfigure(0, minsize=num_w)
        inner.grid_columnconfigure(1, weight=1)
        inner.grid_columnconfigure(2, weight=1)

        def _mw(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _mw))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        name_labels:  list = []
        state_labels: list = []

        def _apply_wraplength(w):
            canvas.itemconfig(canvas_win, width=w)
            col_w = max(80, (w - num_w - 30) // 2)
            for lbl in name_labels:
                lbl.config(wraplength=col_w)
            for lbl in state_labels:
                lbl.config(wraplength=col_w)

        def _on_resize(event):
            _apply_wraplength(event.width)

        canvas.bind("<Configure>", _on_resize)
        # Let fill functions re-apply column widths after repopulating (no
        # <Configure> fires on a mere content rebuild), so rows added on a later
        # selection get the full-width wraplength, not the placeholder 200.
        canvas._carl_reflow = _apply_wraplength
        return canvas, inner, canvas_win, name_labels, state_labels

    def _fill_states_table(self, inner, canvas, name_labels, state_labels, taxon):
        """Populate (or repopulate) inner frame with one row per character."""
        for widget in inner.winfo_children():
            widget.destroy()
        name_labels.clear()
        state_labels.clear()

        EVEN_BG = "#ffffff"
        ODD_BG  = "#f0f0f0"
        GRAY_FG = "#9e9e9e"
        POLY_FG = "#1565c0"
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

            tk.Label(inner, text=str(char.index + 1), bg=bg, fg="#757575",
                     anchor="nw", font=_f
                     ).grid(row=row_idx, column=0, sticky="nsew",
                            padx=(6, 4), pady=2)

            nl = tk.Label(inner, text=char.get_display_name(), bg=bg, fg="black",
                          anchor="nw", font=_f, justify="left", wraplength=200)
            nl.grid(row=row_idx, column=1, sticky="nsew", padx=(0, 4), pady=2)
            name_labels.append(nl)

            sl = tk.Label(inner, text=state_str, bg=bg, fg=fg,
                          anchor="nw", font=_f, justify="left", wraplength=200)
            sl.grid(row=row_idx, column=2, sticky="nsew", padx=(0, 6), pady=2)
            state_labels.append(sl)

        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.yview_moveto(0)

    def _states_column_header(self, outer):
        """Add the #/Character/State header strip to outer (row 0, cols 0–1)."""
        HDR_BG = "#d0d0d0"
        hdr = tk.Frame(outer, bg=HDR_BG)
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)
        hdr.grid_columnconfigure(2, weight=1)
        _hf = self.app_ui_bold
        tk.Label(hdr, text="#",         bg=HDR_BG, font=_hf, anchor="w",
                 width=4).grid(row=0, column=0, padx=(6, 4), pady=4, sticky="w")
        tk.Label(hdr, text="Character", bg=HDR_BG, font=_hf, anchor="w"
                 ).grid(row=0, column=1, padx=(0, 4), pady=4, sticky="ew")
        tk.Label(hdr, text="State",     bg=HDR_BG, font=_hf, anchor="w"
                 ).grid(row=0, column=2, padx=(0, 6), pady=4, sticky="ew")

    def _show_inline_edit(self, title, label, initial, on_ok):
        """Small modal prompt: a label + entry; calls on_ok(value) when confirmed.

        Shared by the Editor's inline-edit actions (Add DataID, Rename Taxon,
        Edit Character Name / State / Coded State, Add State)."""
        win = tk.Toplevel(self.root)
        win.title(title)
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()
        tk.Label(win, text=label, anchor="w").pack(padx=12, pady=(10, 2), fill="x")
        var = tk.StringVar(value=initial)
        entry = tk.Entry(win, textvariable=var, width=52)
        entry.pack(padx=12, pady=(0, 8), fill="x")
        entry.select_range(0, tk.END)
        entry.focus_set()

        def _ok():
            new_val = var.get().strip()
            if new_val and new_val != initial:
                on_ok(new_val)
            win.destroy()

        entry.bind("<Return>", lambda e: _ok())
        entry.bind("<Escape>", lambda e: win.destroy())
        btn = tk.Frame(win)
        btn.pack(pady=(0, 10))
        tk.Button(btn, text="OK",     command=_ok,         width=8).pack(side="left", padx=(0, 6))
        tk.Button(btn, text="Cancel", command=win.destroy, width=8).pack(side="left")
        win.wait_window()

    # ------------------------------------------------------------------
    # Per-taxon popup (right-click on taxa list)
    # ------------------------------------------------------------------

    def show_taxon_states_popup(self, event):
        """Show a scrollable popup of all character states for the right-clicked taxon."""
        if not self.dataset:
            return
        iid = self._ana_tree.identify_row(event.y)
        if not iid:
            return
        display_name = self._ana_tree.item(iid, "text")
        taxon_name = self._nom_label_to_dataid.get(display_name, display_name)
        taxon = next((t for t in self.dataset.taxa if t.name == taxon_name), None)
        if taxon is None:
            return

        win = tk.Toplevel(self.root)
        win.title(display_name.replace("_", " "))
        win.geometry("640x520")
        win.resizable(True, True)
        win.transient(self.root)
        win.grid_rowconfigure(0, weight=1)
        win.grid_columnconfigure(0, weight=1)

        outer = tk.Frame(win)
        outer.grid(row=0, column=0, sticky="nsew", padx=6, pady=(6, 0))
        outer.grid_rowconfigure(1, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        self._states_column_header(outer)
        canvas, inner, _, name_labels, state_labels = self._build_states_canvas(outer)
        self._fill_states_table(inner, canvas, name_labels, state_labels, taxon)

        tk.Button(win, text="Close", command=win.destroy
                  ).grid(row=1, column=0, pady=6)

    # ------------------------------------------------------------------
    # Per-group popup (right-click context menu on groups list)
    # ------------------------------------------------------------------

    def show_group_states_popup(self):
        """Show character states for taxa in the selected group, with a taxon picker."""
        if not self.dataset:
            return
        sel = self._ana_tree.selection()
        group_name = next((self._ana_tree.item(iid, "text") for iid in sel
                           if "group_header" in set(self._ana_tree.item(iid, "tags"))), None)
        if group_name is None:
            return

        try:
            resolved = resolve_selection(
                self.dataset, self.groups, [], [group_name], flatten_groups=True
            )
        except Exception as e:
            messagebox.showerror("Resolution Error", str(e))
            return

        taxa = sorted({t.name for t in resolved})
        if not taxa:
            messagebox.showinfo("Group", f"No taxa found in '{group_name}'.")
            return
        taxon_objects = {t.name: t for t in resolved}

        win = tk.Toplevel(self.root)
        win.title(f"Group: {group_name}")
        win.geometry("640x560")
        win.resizable(True, True)
        win.transient(self.root)
        win.grid_rowconfigure(1, weight=1)
        win.grid_columnconfigure(0, weight=1)

        # Taxon selector
        sel_frame = tk.Frame(win)
        sel_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 2))
        sel_frame.grid_columnconfigure(1, weight=1)
        tk.Label(sel_frame, text="Taxon:").grid(row=0, column=0, padx=(0, 6))
        sel_var = tk.StringVar(value=taxa[0].replace("_", " "))
        combo = ttk.Combobox(
            sel_frame, textvariable=sel_var,
            values=[n.replace("_", " ") for n in taxa],
            state="readonly"
        )
        combo.grid(row=0, column=1, sticky="ew")

        outer = tk.Frame(win)
        outer.grid(row=1, column=0, sticky="nsew", padx=6, pady=(0, 0))
        outer.grid_rowconfigure(1, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        self._states_column_header(outer)
        canvas, inner, _, name_labels, state_labels = self._build_states_canvas(outer)
        self._fill_states_table(
            inner, canvas, name_labels, state_labels, taxon_objects[taxa[0]]
        )

        def _on_select(event=None):
            display = sel_var.get()
            raw_name = display.replace(" ", "_")
            taxon = taxon_objects.get(raw_name) or next(
                (t for t in taxon_objects.values()
                 if t.name.replace("_", " ") == display), None
            )
            if taxon:
                self._fill_states_table(
                    inner, canvas, name_labels, state_labels, taxon
                )

        combo.bind("<<ComboboxSelected>>", _on_select)

        tk.Button(win, text="Close", command=win.destroy
                  ).grid(row=2, column=0, pady=6)

    def _fill_group_states_table(self, inner, canvas, name_labels, state_labels,
                                  taxa):
        """Populate inner frame with aggregate character states across a group of taxa."""
        for widget in inner.winfo_children():
            widget.destroy()
        name_labels.clear()
        state_labels.clear()

        EVEN_BG = "#ffffff"
        ODD_BG  = "#f0f0f0"
        GRAY_FG = "#9e9e9e"
        VAR_FG  = "#1565c0"
        _f = self.app_ui_font

        for row_idx, char in enumerate(self.dataset.characters):
            bg = EVEN_BG if row_idx % 2 == 0 else ODD_BG

            # Collect all informative states across every member
            informative: set = set()
            all_na      = True
            all_missing = True

            for taxon in taxa:
                raw = taxon.states.get(char.index)
                if raw is None or raw == "M":
                    all_na = False
                elif raw == "N":
                    all_missing = False
                else:
                    all_missing = False
                    all_na = False
                    if isinstance(raw, set):
                        informative.update(raw)
                    else:
                        informative.add(raw)

            if not informative:
                state_str = "N/A" if all_na else "?"
                fg = GRAY_FG
            else:
                labels = [char.states.get(s, s) for s in sorted(informative)]
                state_str = " / ".join(labels)
                fg = VAR_FG if len(labels) > 1 else "black"

            tk.Label(inner, text=str(char.index + 1), bg=bg, fg="#757575",
                     anchor="nw", font=_f
                     ).grid(row=row_idx, column=0, sticky="nsew",
                            padx=(6, 4), pady=2)

            nl = tk.Label(inner, text=char.get_display_name(), bg=bg, fg="black",
                          anchor="nw", font=_f, justify="left", wraplength=200)
            nl.grid(row=row_idx, column=1, sticky="nsew", padx=(0, 4), pady=2)
            name_labels.append(nl)

            sl = tk.Label(inner, text=state_str, bg=bg, fg=fg,
                          anchor="nw", font=_f, justify="left", wraplength=200)
            sl.grid(row=row_idx, column=2, sticky="nsew", padx=(0, 6), pady=2)
            state_labels.append(sl)

        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.yview_moveto(0)

    def show_group_character_states_popup(self):
        """Show aggregate character states for the group as a whole."""
        if not self.dataset:
            return
        sel = self._ana_tree.selection()
        group_name = next((self._ana_tree.item(iid, "text") for iid in sel
                           if "group_header" in set(self._ana_tree.item(iid, "tags"))), None)
        if group_name is None:
            return

        try:
            resolved = resolve_selection(
                self.dataset, self.groups, [], [group_name], flatten_groups=True
            )
        except Exception as e:
            messagebox.showerror("Resolution Error", str(e))
            return

        taxa = list({t.name: t for t in resolved}.values())
        if not taxa:
            messagebox.showinfo("Group", f"No taxa found in '{group_name}'.")
            return

        win = tk.Toplevel(self.root)
        win.title(f"Group Character States: {group_name}  ({len(taxa)} taxa)")
        win.geometry("640x520")
        win.resizable(True, True)
        win.transient(self.root)
        win.grid_rowconfigure(0, weight=1)
        win.grid_columnconfigure(0, weight=1)

        outer = tk.Frame(win)
        outer.grid(row=0, column=0, sticky="nsew", padx=6, pady=(6, 0))
        outer.grid_rowconfigure(1, weight=1)
        outer.grid_columnconfigure(0, weight=1)

        self._states_column_header(outer)
        canvas, inner, _, name_labels, state_labels = self._build_states_canvas(outer)
        self._fill_group_states_table(inner, canvas, name_labels, state_labels, taxa)

        tk.Button(win, text="Close", command=win.destroy
                  ).grid(row=1, column=0, pady=6)


    def view_group_members(self):
        """Display a dialog showing the taxa contained in the selected group."""
        sel = self._ana_tree.selection()
        group_name = next((self._ana_tree.item(iid, "text") for iid in sel
                           if "group_header" in set(self._ana_tree.item(iid, "tags"))), None)
        if group_name is None:
            messagebox.showerror("Error", "No group selected.")
            return

        # Resolve the group into actual Taxon objects
        try:
            # Use positional arguments (consistent with run_action)
            resolved_taxa = resolve_selection(
            self.dataset,
            self.groups,
            [],
            [group_name],
            flatten_groups=True
            )
            taxa_names = sorted(taxon.name for taxon in resolved_taxa)

            # Extract and sort taxon names
            taxa_names = sorted({taxon.name for taxon in resolved_taxa})

        except Exception as e:
            messagebox.showerror(
                "Resolution Error",
                f"Unable to resolve group members:\n{str(e)}"
            )
            return

        # If no taxa were resolved, provide a fallback
        if not taxa_names:
            raw_members = self.groups.get(group_name, [])
            taxa_names = sorted(raw_members)

        # Create a dialog window
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Group Members: {group_name}")
        dialog.geometry("400x400")
        dialog.transient(self.root)
        dialog.grab_set()

        # Header label
        tk.Label(
            dialog,
            text=f"Taxa in '{group_name}' ({len(taxa_names)}):",
            font=self.app_ui_bold
        ).pack(pady=10)

        # Frame for listbox and scrollbar
        frame = tk.Frame(dialog)
        frame.pack(fill="both", expand=True, padx=10, pady=5)

        # Listbox with scrollbar
        listbox = tk.Listbox(frame)
        listbox.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(frame, orient="vertical", command=listbox.yview)
        scrollbar.pack(side="right", fill="y")
        listbox.config(yscrollcommand=scrollbar.set)

        # Populate the listbox with taxa
        for taxon in taxa_names:
            listbox.insert(tk.END, taxon)

        # Close button
        tk.Button(dialog, text="Close", command=dialog.destroy).pack(pady=10)
    # -------------------------
    # FILE LOADING
    # -------------------------
    def load_file(self):
        filepath = filedialog.askopenfilename(
            filetypes=[("NEXUS files", "*.nex *.nexus"), ("All files", "*.*")],
            **self._wd_kwargs()
        )
        if not filepath:
            return

        # Read raw text first (needed by CARL parser + dataset_text)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw_text = f.read()
        except Exception as exc:
            messagebox.showerror("Load Error", f"Cannot read file:\n{exc}")
            return

        state = detect_file_state(raw_text)

        if state == "invalid":
            messagebox.showerror(
                "Invalid File",
                "This file contains neither a CARL block nor a DATA block.\n"
                "Please open a valid NEXUS file."
            )
            return

        self.filepath = filepath
        self.dataset_text = raw_text
        self.analysis_raw_output = ""

        # ---- Parse DATA block (always present in Normal + Build) ----
        self.dataset = parse_nexus(filepath)
        self.kg = build_knowledge_graph(self.dataset)

        # ---- Parse CARL block ----
        if state == "normal":
            try:
                self.carl_block = parse_carl_block(raw_text)
            except ValueError as e:
                messagebox.showerror(
                    "CARL Block Error",
                    f"The CARL block could not be parsed:\n\n{e}\n\n"
                    "Please correct the error and reload the file."
                )
                return
            self.groups = {
                name: list(members)
                for name, members in self.carl_block.get_groups().items()
            }
            mode_text = "Edit mode — CARL block loaded"
            shared = self.carl_block.check_shared_data_ids()
            if shared:
                lines = []
                for data_id, names, is_divides in shared:
                    severity = "WARNING (divides)" if is_divides else "Warning"
                    lines.append(f"{severity}: dataID '{data_id}' shared by: {', '.join(names)}")
                messagebox.showwarning("Shared DataID Warning", "\n".join(lines))

            if self.carl_block.parse_errors:
                messagebox.showerror(
                    "CARL Block Errors",
                    "The following errors were found in the CARL block:\n\n"
                    + "\n".join(f"  • {e}" for e in self.carl_block.parse_errors)
                    + "\n\nPlease correct these statements."
                )

            if self.carl_block.parse_warnings:
                _fp = filepath or ""
                _w2 = [w for w in self.carl_block.parse_warnings if w.startswith("W2:")]
                _other = [w for w in self.carl_block.parse_warnings if not w.startswith("W2:")]
                _show = _other + (_w2 if _fp not in self._session_warned_files else [])
                if _show:
                    messagebox.showwarning(
                        "CARL Block Warnings",
                        "The following warnings were detected in the CARL block:\n\n"
                        + "\n".join(f"  • {w}" for w in _show)
                        + "\n\nPlease review these statements."
                    )
                if _w2:
                    self._session_warned_files.add(_fp)

            conflicts = self.carl_block.check_dataid_conflicts()
            if conflicts:
                lines = [
                    f"  • '{name}': entity DataID='{eid}', "
                    f"object DataID='{oid}'"
                    for name, eid, oid in conflicts
                ]
                messagebox.showwarning(
                    "DataID Conflict",
                    "The following taxa appear with two different DataIDs:\n\n"
                    + "\n".join(lines)
                    + "\n\nA taxon can only point to one DataID. "
                    "Please correct these statements."
                )
        else:  # build
            self.carl_block = CARLBlock([], [])
            self.groups = {}
            mode_text = "Build mode — no CARL block; analyses locked until CARL block added"

        self._file_state = state
        self._nom_mode_var.set(mode_text)

        self._build_display_name_maps()
        self.populate_lists()
        self.update_group_list()
        self._populate_nomenclature_tab(state)
        self._populate_editor_tab()
        self._update_filepath_display()

        # Switch File panel to Nomenclature tab
        self._file_nb.select(self.nomenclature_tab)

    # ================================================================
    # UNIFIED SAVE INFRASTRUCTURE
    # ================================================================

    def _save_nexus(self, path: str) -> bool:
        """Write DATA + CARL blocks to path, preserving other blocks (e.g. TREES)."""
        # Rank warning
        if self.carl_block and self.carl_block.entities:
            bad = [f"  • {e.name}"
                   for e in self.carl_block.entities
                   if not e.rank or e.rank == "unknown"]
            if bad:
                if not messagebox.askyesno(
                        "Incomplete Statements",
                        "Some CARL statements have no rank:\n"
                        + "\n".join(bad) + "\n\nSave anyway?"):
                    return False

        existing = None
        if self.filepath and os.path.exists(self.filepath):
            with open(self.filepath, "r", encoding="utf-8") as f:
                existing = f.read()

        content = build_nexus_content(
            self.dataset, self.carl_block, existing,
            update_data=self._char_edits_pending)

        try:
            write_nexus_atomic(path, content)
            self.filepath            = path
            self.dataset_text        = content
            self._char_edits_pending = False
            self._carl_modified      = False
            if self.dataset:
                self.kg = build_knowledge_graph(self.dataset)
            self._update_filepath_display()
            messagebox.showinfo("Saved", f"Saved to:\n{path}")
            return True
        except OSError as ex:
            messagebox.showerror("Save Error", str(ex))
            return False

    def save_file(self):
        """Save to the current file (prompts for path if none set)."""
        if not self.dataset and not self.carl_block:
            messagebox.showinfo("Nothing to Save",
                                "No data or declarations to save.")
            return
        if self.filepath:
            self._save_nexus(self.filepath)
        else:
            self.save_file_as()

    def save_file_as(self):
        """Save to a new file chosen via dialog."""
        if not self.dataset and not self.carl_block:
            messagebox.showinfo("Nothing to Save",
                                "No data or declarations to save.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".nex",
            filetypes=[("NEXUS files", "*.nex *.nexus"),
                       ("All files", "*.*")],
            title="Save As",
            **self._wd_kwargs()
        )
        if not path:
            return
        self._save_nexus(path)

    # ================================================================

    def update_current_file(self):
        """Update the currently loaded NEXUS file with CARL block, groups, and character edits."""
        if not hasattr(self, "filepath") or not self.filepath:
            messagebox.showerror("Error", "No NEXUS file loaded.")
            return

        has_carl_changes = (
            getattr(self, "_file_state", None) == "normal"
            and self.carl_block is not None
            and self._carl_modified
        )
        if not has_carl_changes and not self.groups and not self._char_edits_pending:
            messagebox.showinfo("Nothing to Save", "No changes to save.")
            return

        confirm = messagebox.askyesno(
            "Confirm Update",
            "This will modify the currently loaded NEXUS file.\n"
            "Do you want to continue?"
        )
        if not confirm:
            return

        with open(self.filepath, "r", encoding="utf-8") as f:
            original_text = f.read()

        updated_text = original_text

        if self._char_edits_pending and self.dataset:
            updated_text = update_charstatelabels_in_nexus(updated_text, self.dataset.characters)

        if has_carl_changes:
            carl_text = serialize_carl_block(self.carl_block, original_text)
            _carl_pat = re.compile(r'\nBEGIN\s+CARL\s*;.*?END\s*;',
                                   re.DOTALL | re.IGNORECASE)
            if _carl_pat.search(updated_text):
                updated_text = _carl_pat.sub("\n\n" + carl_text, updated_text)
            else:
                updated_text = updated_text.rstrip() + "\n\n" + carl_text + "\n"

        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write(updated_text)

        if self._char_edits_pending and self.dataset:
            self.kg = build_knowledge_graph(self.dataset)
            self._char_edits_pending = False
        if has_carl_changes:
            self.dataset_text  = updated_text
            self._carl_modified = False

        messagebox.showinfo("Success", "Current NEXUS file updated successfully.")

    def save_groups_as(self):
        """Save CARL block, groups, and character edits to a new NEXUS file."""
        if not hasattr(self, "filepath") or not self.filepath:
            messagebox.showerror("Error", "No NEXUS file loaded.")
            return

        has_carl_changes = (
            getattr(self, "_file_state", None) == "normal"
            and self.carl_block is not None
            and self._carl_modified
        )
        if not has_carl_changes and not self.groups and not self._char_edits_pending:
            messagebox.showinfo("Nothing to Save", "No changes to save.")
            return

        save_path = filedialog.asksaveasfilename(
            defaultextension=".nex",
            filetypes=[("NEXUS files", "*.nex *.nexus")],
            **self._wd_kwargs()
        )
        if not save_path:
            return

        with open(self.filepath, "r", encoding="utf-8") as f:
            original_text = f.read()

        updated_text = original_text

        if self._char_edits_pending and self.dataset:
            updated_text = update_charstatelabels_in_nexus(updated_text, self.dataset.characters)

        if has_carl_changes:
            carl_text = serialize_carl_block(self.carl_block, original_text)
            _carl_pat = re.compile(r'\nBEGIN\s+CARL\s*;.*?END\s*;',
                                   re.DOTALL | re.IGNORECASE)
            if _carl_pat.search(updated_text):
                updated_text = _carl_pat.sub("\n\n" + carl_text, updated_text)
            else:
                updated_text = updated_text.rstrip() + "\n\n" + carl_text + "\n"

        with open(save_path, "w", encoding="utf-8") as f:
            f.write(updated_text)

        if self._char_edits_pending and self.dataset:
            self.kg = build_knowledge_graph(self.dataset)
            self._char_edits_pending = False

        messagebox.showinfo("Success", f"File saved to:\n{save_path}")
    def _build_display_name_maps(self):
        """Populate data_id↔nom_label maps from the current CARL block."""
        self._nom_dataid_to_label = {}
        self._nom_label_to_dataid = {}
        if not self.carl_block or not self.carl_block.entities:
            return
        for row in self.carl_block.get_data_tab_rows():
            did = row.get("data_id")
            label = row.get("label")
            if did and label and not row.get("is_group_header"):
                self._nom_dataid_to_label[did] = label
                self._nom_label_to_dataid[label] = did

    def _update_filepath_display(self):
        """Update window title and Nomenclature file bar with the current filename."""
        if self.filepath:
            name = os.path.basename(self.filepath)
            self.root.title(f"CARL — {name}")
            self._nom_filepath_label.config(text=name)
        else:
            self.root.title("CARL")
            self._nom_filepath_label.config(text="No file loaded")

    def _refresh_derived_panels(self):
        """Rebuild display-name maps and refresh Analyses/Information panels.
        Called after any CARL block modification so derived taxa appear immediately."""
        self._build_display_name_maps()
        if self.carl_block is not None:
            self.groups = {
                name: list(members)
                for name, members in self.carl_block.get_groups().items()
            }
        if self.dataset:
            self.populate_lists()
            self.update_group_list()
            self.populate_literature_table()

    def _make_proxy_taxa(self, taxa):
        """Return Taxon objects with .name replaced by the CARL nom-label where
        available.  Proxy objects share the original .states dict (no copy needed
        — states are read-only during an analysis run)."""
        if not self._nom_dataid_to_label:
            return list(taxa)
        result = []
        for t in taxa:
            nom = self._nom_dataid_to_label.get(t.name)
            if nom and nom != t.name:
                proxy = t.__class__(nom)
                proxy.states = t.states
                result.append(proxy)
            else:
                result.append(t)
        return result

    def populate_lists(self):
        self._ana_mirror()
        self._mak_populate()

    def _ana_mirror(self):
        """Rebuild the Analyses tree by mirroring the Derived View (nom_tree)."""
        for iid in self._ana_tree.get_children():
            self._ana_tree.delete(iid)

        if not (self.carl_block and self.carl_block.entities):
            return

        _KEEP = {"group_header", "greyed", "nov", "includes_member"}

        def _walk(nom_parent, ana_parent):
            for nom_iid in self.nom_tree.get_children(nom_parent):
                if self._nom_iid_meta.get(nom_iid) is None:
                    continue
                nom_tags = set(self.nom_tree.item(nom_iid, "tags"))
                nom_text = self.nom_tree.item(nom_iid, "text")
                self._ana_tree.insert(
                    ana_parent, tk.END, iid=nom_iid,
                    text=nom_text, tags=tuple(nom_tags & _KEEP), open=True)
                _walk(nom_iid, nom_iid)

        _walk("", "")

        # Refresh the index taxon combobox for Diagnose
        _individual_taxa = sorted(self._nom_label_to_dataid.keys())
        self._diagnose_index_cb["values"] = _individual_taxa
        if self._diagnose_index_var.get() not in _individual_taxa:
            self._diagnose_index_var.set("")

    # ============================================================
    # MULTI-ACCESS KEY
    # ============================================================

    def _mak_populate(self):
        """Populate MAK character + taxa lists from current dataset. Resets criteria."""
        self._mak_char_list.delete(0, tk.END)
        self._mak_char_num_map.clear()

        if self.dataset:
            for i, char in enumerate(self.dataset.characters):
                cname = char.get_display_name()
                self._mak_char_list.insert(tk.END, f"{i + 1}. {cname}")
                self._mak_char_num_map[cname] = i + 1

        # Build flat taxa row list: (display_label, data_id)
        self._mak_taxa_rows = []
        if self.dataset and self.carl_block and self.carl_block.entities:
            for row in self.carl_block.get_data_tab_rows():
                if not row.get("is_group_header") and row.get("note") != "includes_member":
                    self._mak_taxa_rows.append(
                        (row["label"], row.get("data_id", row["label"]))
                    )

        # Reset criteria state and refresh display
        self._mak_state_selections.clear()
        self._mak_criteria_order.clear()
        self._mak_state_list.delete(0, tk.END)
        self._mak_criteria_list.delete(0, tk.END)
        self._mak_evaluate()

    def _mak_on_char_select(self, event):
        """Populate state listbox when a character is selected."""
        sel = self._mak_char_list.curselection()
        if not sel or not self.dataset:
            return
        self._mak_state_list.delete(0, tk.END)
        char = self.dataset.characters[sel[0]]
        for state_id, state_label in char.states.items():
            self._mak_state_list.insert(tk.END, f"{state_id}: {state_label}")

    def _mak_add_criterion(self):
        """Add or extend a character-state criterion and re-evaluate taxa."""
        char_sel  = self._mak_char_list.curselection()
        state_sel = self._mak_state_list.curselection()

        if not char_sel:
            messagebox.showerror("No character", "Please select a character first.")
            return
        if not state_sel:
            messagebox.showerror("No states", "Please select one or more states.")
            return

        char  = self.dataset.characters[char_sel[0]]
        cname = char.get_display_name()

        # Parse label from "state_id: state_label" format
        selected_labels = set()
        for i in state_sel:
            entry = self._mak_state_list.get(i)
            selected_labels.add(entry.split(": ", 1)[1] if ": " in entry else entry)

        # Union within character (H: re-adding same character = OR)
        if cname not in self._mak_state_selections:
            self._mak_state_selections[cname] = set()
            self._mak_criteria_order.append(cname)
        self._mak_state_selections[cname].update(selected_labels)

        self._mak_refresh_criteria_list()
        self._mak_evaluate()

    def _mak_remove_criterion(self):
        """Remove the selected criterion and re-evaluate taxa."""
        sel = self._mak_criteria_list.curselection()
        if not sel:
            return
        idx   = sel[0]
        cname = self._mak_criteria_order[idx]
        del self._mak_state_selections[cname]
        del self._mak_criteria_order[idx]
        self._mak_refresh_criteria_list()
        self._mak_evaluate()

    def _mak_clear_criteria(self):
        """Clear all criteria and restore full taxa list."""
        self._mak_state_selections.clear()
        self._mak_criteria_order.clear()
        self._mak_criteria_list.delete(0, tk.END)
        self._mak_evaluate()

    def _mak_refresh_criteria_list(self):
        """Rebuild the criteria listbox from current state_selections."""
        self._mak_criteria_list.delete(0, tk.END)
        for cname in self._mak_criteria_order:
            num        = self._mak_char_num_map.get(cname, "?")
            states_str = ", ".join(sorted(self._mak_state_selections[cname]))
            self._mak_criteria_list.insert(
                tk.END, f"Char {num} ({cname}): {states_str}"
            )

    def _mak_evaluate(self):
        """Re-evaluate all taxa against current criteria and update taxa listbox."""
        self._mak_taxa_list.delete(0, tk.END)

        if not self.dataset or not self._mak_taxa_rows:
            self._mak_taxa_list.insert(tk.END, "No data loaded.")
            self._mak_candidates_var.set("Candidates")
            return

        if not self._mak_state_selections:
            # No criteria — show all taxa active
            for label, _ in self._mak_taxa_rows:
                self._mak_taxa_list.insert(tk.END, label)
            self._mak_candidates_var.set(
                f"Candidates  ({len(self._mak_taxa_rows)} of {len(self._mak_taxa_rows)})"
            )
            return

        results = evaluate_taxa_for_mak(self.dataset, self._mak_state_selections)

        active_count = 0
        for label, data_id in self._mak_taxa_rows:
            res  = results.get(data_id, {"grey": False, "m_char_nums": []})
            grey = res["grey"]

            if res["m_char_nums"]:
                m_str   = ", ".join(f"Char {n}" for n in res["m_char_nums"])
                display = f"{label} [M: {m_str}]"
            else:
                display = label

            self._mak_taxa_list.insert(tk.END, display)
            if grey:
                self._mak_taxa_list.itemconfig(tk.END, fg="grey")
            else:
                active_count += 1

        self._mak_candidates_var.set(
            f"Candidates  ({active_count} of {len(self._mak_taxa_rows)} active)"
        )


    # -------------------------
    # GROUP FUNCTIONS
    # -------------------------
    def _ana_on_right_click(self, event):
        """Unified right-click handler for the Analyses panel tree."""
        iid = self._ana_tree.identify_row(event.y)
        if not iid:
            return
        self._ana_tree.selection_set(iid)
        tags = set(self._ana_tree.item(iid, "tags"))
        if "group_header" in tags:
            try:
                self._ana_group_context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self._ana_group_context_menu.grab_release()
        elif "includes_member" not in tags:
            self.show_taxon_states_popup(event)

    def update_group_list(self):
        pass  # superseded by _ana_mirror() called from populate_lists()

    def apply_nlg_formatting(self, raw_text: str, mode: str, label: str = ""):
        """Deterministic, non-LLM natural-language generation: render the raw
        output with the character↔state delimiter replaced by is/are (via
        description_verbs) and append it below the raw text.

        No-ops unless the output mode is 'nlg'. Safe to call from the Descriptions
        background thread or the Keys main thread — the transform runs inline
        (pure Python, offline) and the text-widget insert is marshalled onto the
        Tk thread, preserving raw→NLG ordering.
        """
        if self.output_mode.get() != "nlg":
            return
        from description_verbs import transform_text
        try:
            nlg_text, _ = transform_text(raw_text, mode=mode)
        except Exception as e:
            nlg_text = f"[NLG error: {e}]"
        header = f"\nNLG OUTPUT{' — ' + label if label else ''}\n\n"
        self.output.after(
            0, lambda: self.output.insert(tk.END, header + nlg_text.rstrip('\n') + "\n"))

    def apply_llm_formatting(self, raw_text: str, llm_config, verify_config,
                             is_key: bool = False, is_diagnosis: bool = False,
                             seq_delay: int = 0, label: str = "",
                             blocking: bool = False, on_done=None):
        """
        Apply LLM-based formatting to the provided text and display
        the results in the output window. Uses existing utilities
        from llm_formatter to avoid redundancy.
        """


        if self.output_mode.get() != "llm":
            if on_done:
                on_done()
            return
        if not self._llm_model_is_set(llm_config.model):
            if on_done:
                on_done()
            return
        self.output.after(0, lambda: self.progress.start(10))
        self.output.after(0, lambda: self.status_var.set("Running LLM..."))
        def run_llm():
            if seq_delay:
                time.sleep(seq_delay)

            def update_status(message):
                self.output.after(0, lambda m=message: self.status_var.set(m))
                if "Daily token limit" in message:
                    self._tpd_message = message

            try:
                if is_key:
                    update_status(f"Running {llm_config.model} (key rewrite)...")
                    key_lines = [l for l in raw_text.split("\n") if l.strip()]
                    header = f"\nLLM OUTPUT{' — ' + label if label else ''}\n\n"
                    self.output.after(0, lambda h=header: self.output.insert(tk.END, h))
                    accumulated = []
                    for chunk in naturalize_key_stream(
                        key_lines, llm_config, status_fn=update_status,
                        cancel_fn=self._llm_cancel.is_set):
                        if self._llm_cancel.is_set():
                            break
                        self.output.after(0, lambda c=chunk: self.output.insert(tk.END, c))
                        accumulated.append(chunk)
                    formatted = "".join(accumulated).strip() or "[No output — model returned empty response.]"
                    self.output.after(0, lambda: self.output.insert(tk.END, "\n"))

                elif is_diagnosis:
                    update_status(f"Running {llm_config.model} (diagnosis)...")
                    header = f"\nLLM OUTPUT{' — ' + label if label else ''}\n\n"
                    self.output.after(0, lambda h=header: self.output.insert(tk.END, h))
                    accumulated = []
                    for token in format_diagnosis_stream(
                        raw_text, config=llm_config, status_fn=update_status,
                        cancel_fn=self._llm_cancel.is_set):
                        if self._llm_cancel.is_set():
                            break
                        self.output.after(0, lambda t=token: self.output.insert(tk.END, t))
                        accumulated.append(token)
                    formatted = "".join(accumulated).strip() or "[No output — model returned empty response.]"
                    self.output.after(0, lambda: self.output.insert(tk.END, "\n"))

                else:
                    update_status(f"Running {llm_config.model} (generation)...")
                    header = f"\nLLM OUTPUT{' — ' + label if label else ''}\n\n"
                    self.output.after(0, lambda h=header: self.output.insert(tk.END, h))
                    accumulated = []
                    for token in format_fast_stream(
                        raw_text, llm_config, style="verbose",
                        status_fn=update_status,
                        cancel_fn=self._llm_cancel.is_set):
                        if self._llm_cancel.is_set():
                            break
                        self.output.after(0, lambda t=token: self.output.insert(tk.END, t))
                        accumulated.append(token)
                    formatted = "".join(accumulated).strip()
                    if not formatted:
                        formatted = (f"[{self._tpd_message}]" if self._tpd_message
                                     else "[No output — model returned empty response.]")
                        self.output.after(0, lambda f=formatted: self.output.insert(tk.END, f))
                    self.output.after(0, lambda: self.output.insert(tk.END, "\n"))

                # ---- Iterated verification (Full mode only; Corrector = Writer) ----
                def _emit(text):
                    self.output.after(0, lambda t=text: self.output.insert(tk.END, t))

                verify_requested = (
                    not self._llm_cancel.is_set()
                    and self.output_mode.get() == "llm"
                    and self.llm_mode.get() == "full")
                verify_model_ok = self._llm_model_is_set(verify_config.model)
                status_line = ""

                if verify_requested and not verify_model_ok:
                    status_line = ("STATUS: verification skipped — no verification "
                                   "model is set (LM Settings).")
                elif verify_requested:
                    rounds = max(1, int(getattr(self, "_active_verify_rounds", 3) or 3))
                    _emit(f"\nVERIFICATION{' — ' + label if label else ''}\n\n")
                    current = formatted
                    last_report = ""
                    outcome = "maxed"
                    reached = 0
                    for k in range(1, rounds + 1):
                        reached = k
                        if self._llm_cancel.is_set():
                            outcome = "cancelled"
                            break
                        update_status(
                            f"Running {verify_config.model} (verification {k}/{rounds})...")
                        try:
                            report = verify_output_with_llm(
                                raw_text, current, config=verify_config,
                                status_fn=update_status,
                                cancel_fn=self._llm_cancel.is_set)
                        except RateLimitError as rle:
                            _emit(f"\n⚠ Rate limit — {rle}\n")
                            outcome = "ratelimit"
                            last_report = ""
                            break
                        except Exception as ve:
                            _emit(f"Round {k}/{rounds}: verification error — {ve}\n")
                            outcome = "error"
                            last_report = ""
                            break
                        last_report = report
                        if verification_passed(report):
                            _emit(f"Round {k}/{rounds}: verifier found no issues.\n")
                            outcome = "passed"
                            break
                        if not verification_has_issues(report):
                            _emit(f"Round {k}/{rounds}: verifier returned no usable verdict.\n")
                            outcome = "noverdict"
                            break
                        if k == rounds:
                            _emit(f"Round {k}/{rounds}: issues still reported after the final round.\n")
                            outcome = "maxed"
                            break
                        # Correction runs on the WRITER model (llm_config), not the verifier.
                        _emit(f"Round {k}/{rounds}: issues found — correcting…\n")
                        update_status(
                            f"Running {llm_config.model} (correction {k}/{rounds - 1})...")
                        try:
                            if is_key:
                                current = correct_key_with_llm(
                                    raw_text, current, report,
                                    config=llm_config, status_fn=update_status,
                                    cancel_fn=self._llm_cancel.is_set)
                            else:
                                current = correct_prose_with_llm(
                                    raw_text, current, report, config=llm_config,
                                    analysis_kind="analysis", status_fn=update_status,
                                    cancel_fn=self._llm_cancel.is_set)
                        except RateLimitError as rle:
                            _emit(f"\n⚠ Rate limit — {rle}\n")
                            outcome = "ratelimit"
                            break
                        except Exception as ce:
                            _emit(f"Round {k}/{rounds}: correction failed — {ce}\n")
                            outcome = "correcterror"
                            break

                    if outcome == "passed":
                        if current != formatted:
                            _emit(f"\nFINAL OUTPUT{' — ' + label if label else ''}\n\n{current}\n")
                        status_line = (
                            f"STATUS: verifier found no issues (round {reached}/{rounds}). "
                            "This is the verifier's opinion, not a guarantee — compare with Raw above.")
                    elif outcome == "cancelled":
                        status_line = "STATUS: verification cancelled."
                    elif outcome == "ratelimit":
                        status_line = ("STATUS: rate limit reached — see the message "
                                       "above; try again shortly or switch models.")
                    elif outcome == "error":
                        status_line = ("STATUS: verification could not be completed "
                                       "(the verifier errored or timed out).")
                    else:
                        # maxed / noverdict / correcterror: show the last corrected
                        # version (so the issues are coherent) then the final issues.
                        if current != formatted:
                            _emit(f"\nFINAL OUTPUT{' — ' + label if label else ''}\n\n{current}\n")
                        if last_report:
                            hdr = ("REMAINING ISSUES"
                                   if outcome in ("maxed", "correcterror") else "VERIFIER OUTPUT")
                            display_report = verification_display_text(
                                last_report, include_reasoning=False)
                            _emit(f"\n{hdr}{' — ' + label if label else ''}\n\n{display_report}\n")
                        if outcome == "maxed":
                            status_line = (
                                f"STATUS: verifier still reported issues after {rounds} round(s). "
                                "The Raw output above is unmodified — compare and judge.")
                        elif outcome == "noverdict":
                            status_line = "STATUS: verifier returned no usable verdict."
                        else:  # correcterror
                            status_line = ("STATUS: a correction attempt failed; stopped. "
                                           "Compare the rewrite with the Raw output above.")

                def update():
                    if status_line:
                        self.output.insert(tk.END, "\n" + status_line + "\n")
                    self.output.after(0, lambda: self.progress.stop())
                    self.output.after(0, lambda: self.status_var.set("Ready"))
                    if on_done and not blocking:
                        self.output.after(0, on_done)

                self.output.after(0, update)

            except RateLimitError as rle:
                # Capture the message now: the `rle` binding is deleted when this
                # except block exits, but show_rate_limit runs later via after().
                rl_msg = str(rle)
                def show_rate_limit(rl_msg=rl_msg):
                    self.output.after(0, lambda: self.progress.stop())
                    self.output.after(0, lambda: self.status_var.set("Rate limit"))
                    self.output.insert(tk.END, f"\n⚠ Rate limit — {rl_msg}\n")
                    if on_done and not blocking:
                        self.output.after(0, on_done)

                self.output.after(0, show_rate_limit)

            except Exception as e:
                # Capture now — `e` is unbound once the except block exits, but
                # show_error runs later via after().
                err_msg = str(e)
                def show_error(err_msg=err_msg):
                    self.output.after(0, lambda: self.progress.stop())
                    self.output.after(0, lambda: self.status_var.set("LLM Error"))
                    self.output.insert(
                        tk.END,
                        f"\nLLM ERROR:\n{err_msg}\n"
                    )
                    if on_done and not blocking:
                        self.output.after(0, on_done)

                self.output.after(0, show_error)

        if blocking:
            run_llm()
        else:
            threading.Thread(target=run_llm, daemon=True).start()



    # ============================================================
    # CANCEL HELPER
    # ============================================================

    def _cancel_analysis(self):
        self._llm_cancel.set()
        try:
            self.status_var.set("Cancelling…")
            self.run_btn.config(state="disabled", text="Stopping…")
        except Exception:
            pass

    def _set_run_btn_running(self):
        self.run_btn.config(state="normal", text="Stop", command=self._cancel_analysis)

    def _set_run_btn_ready(self):
        cmds = {
            self._desc_run_btn: self._run_descriptions,
            self._comp_run_btn: self._run_comparisons,
            self._keys_run_btn: self._run_keys,
        }
        cmd = cmds.get(self.run_btn, self._run_descriptions)
        self.run_btn.config(state="normal", text="Run", command=cmd)

    # ============================================================
    # OUTPUT HELPERS
    # ============================================================

    def _copy_output(self):
        text = self.output.get("1.0", tk.END).strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

    def _save_output(self):
        text = self.output.get("1.0", tk.END).strip()
        if not text:
            messagebox.showinfo("Save Output", "No output to save.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save Output",
            **self._wd_kwargs()
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)

    # ============================================================
    # PREAMBLE PREVIEW
    # ============================================================

    def _preview_preamble(self, taxon_name=None):
        if taxon_name is None:
            taxon_name = self._lit_selected_taxon
        if not taxon_name:
            return
        entry = self._lit_cache.get(taxon_name)
        if not entry or not is_new_format(entry):
            messagebox.showinfo("Preview Preamble", "No Darwin Core entry for this taxon.")
            return

        ro_preamble  = build_preamble(entry, self._lit_include_fields, variant="raw")
        llm_preamble = build_preamble(entry, self._lit_include_fields, variant="llm")

        win = tk.Toplevel(self.root)
        win.title(f"Preamble — {taxon_name.replace('_', ' ')}")
        win.geometry("600x420")
        win.resizable(True, True)

        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=5, pady=5)

        for title, text in [("Raw (all fields)", ro_preamble), ("LLM (clean)", llm_preamble)]:
            frame = tk.Frame(nb)
            nb.add(frame, text=title)
            frame.grid_rowconfigure(0, weight=1)
            frame.grid_columnconfigure(0, weight=1)
            t = tk.Text(frame, wrap="word", padx=6, pady=6)
            t.insert("1.0", text)
            t.config(state="disabled")
            s = ttk.Scrollbar(frame, orient="vertical", command=t.yview)
            t.config(yscrollcommand=s.set)
            t.grid(row=0, column=0, sticky="nsew")
            s.grid(row=0, column=1, sticky="ns")

        tk.Button(win, text="Close", command=win.destroy).pack(pady=(0, 6))


#-------------------------
# CHAT FUNCTIONALITY -- delete as a block from here to end if you want to remove the chatbot
#-------------------------

    def introduce_carl(self):
        message = (
            "Hello! I am your taxonomy assistant. If you would like me to use an LLM to help you, please make sure that you have selected a model in the Settings > LM Settings tab. If you are not using an LLM, I can still help you by retrieving information from the Codes of Nomenclature. Please type in your query and click ‘Send’."
        )
        self.append_chat("Carl", message)


    def append_chat(self, speaker, message):
        self.chat_history.config(state="normal")
        self.chat_history.insert(tk.END, f"{speaker}: {message}\n\n")
        self.chat_history.config(state="disabled")
        self.chat_history.see(tk.END)

    def clear_chat(self):
        self.carl_history = []
        self.chat_history.config(state="normal")
        self.chat_history.delete("1.0", tk.END)
        self.chat_history.config(state="disabled")
        self.introduce_carl()

    def copy_chat(self):
        text = self.chat_history.get("1.0", tk.END).strip()
        if text:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)

    def send_chat_message(self):
        user_input = self.chat_input.get("1.0", "end").strip()
        if not user_input:
            return

        rag_code = getattr(self, "rag_code_var", None)
        rag_code = rag_code.get() if rag_code else "None"
        rag_code = None if rag_code == "None" else rag_code
        rag_k    = getattr(self, "rag_k_var", None)
        rag_k    = rag_k.get() if rag_k else 12

        has_llm = self._llm_model_is_set(self.chat_model_var.get())
        has_rag = rag_code is not None

        if not has_llm and not has_rag:
            self.chat_history.config(state="normal")
            self.chat_history.insert(tk.END,
                "Carl: [No model selected and no Code selected — "
                "choose a model in Settings > LM Settings, or select a "
                "Code of Nomenclature in the chat toolbar.]\n\n")
            self.chat_history.config(state="disabled")
            self.chat_history.see(tk.END)
            self.chat_input.delete("1.0", "end")
            return

        self.chat_input.delete("1.0", "end")
        self.append_chat("You", user_input)

        self.chat_history.config(state="normal")
        self.chat_history.insert(tk.END, "Carl: ")
        self.chat_history.config(state="disabled")
        self.chat_history.see(tk.END)

        llm_config = None
        if has_llm:
            llm_config = LLMConfig(
                model=self.chat_model_var.get(),
                temperature=0.1,
                num_predict=8192,
                style_guide="",
                think=False,
                use_chat=True,
            )

        use_memory       = getattr(self, "chat_memory_var", None)
        use_memory       = use_memory.get() if use_memory else True
        history_snapshot = list(self.carl_history) if use_memory else []
        token_queue      = _queue_mod.Queue()
        accumulated      = []
        _status_pos      = [None]

        def _status(msg):
            token_queue.put(("status", msg))

        def worker():
            try:
                if has_rag:
                    token_queue.put(("status", f"Retrieving from {rag_code.upper()}…"))
                    hit_chunks, code_name = get_rar_chunks(
                        user_input, rag_code, k=rag_k)
                    token_queue.put(("rar", format_rar_response(hit_chunks, code_name)))

                if has_llm:
                    for token in ask_stream(user_input, llm_config,
                                            history=history_snapshot,
                                            rag_code=rag_code, rag_k=rag_k,
                                            status_fn=_status if rag_code else None):
                        token_queue.put(("tok", token))
                        accumulated.append(token)
            except Exception as e:
                token_queue.put(("tok", _friendly_error(e)))
            token_queue.put(("done", None))

        def poll():
            try:
                while True:
                    kind, data = token_queue.get_nowait()
                    if kind == "done":
                        full = "".join(accumulated).strip()
                        if full and not full.startswith("[Error"):
                            self.carl_history.append((user_input, full))
                            if len(self.carl_history) > 3:
                                self.carl_history.pop(0)
                        self.chat_history.config(state="normal")
                        self.chat_history.insert(tk.END, "\n\n")
                        self.chat_history.config(state="disabled")
                        self.chat_history.see(tk.END)
                        return
                    if kind == "rar":
                        if _status_pos[0] is not None:
                            self.chat_history.config(state="normal")
                            self.chat_history.delete(_status_pos[0], tk.END)
                            self.chat_history.config(state="disabled")
                            _status_pos[0] = None
                        self.chat_history.config(state="normal")
                        _rar_lines = data.split("\n")
                        for _ri, _rl in enumerate(_rar_lines):
                            if _rl and all(c == "─" for c in _rl):
                                self.chat_history.insert(tk.END, _rl, "rag_sep")
                            else:
                                self.chat_history.insert(tk.END, _rl)
                            if _ri < len(_rar_lines) - 1:
                                self.chat_history.insert(tk.END, "\n")
                        if has_llm:
                            self.chat_history.insert(tk.END, "\n\n")
                        self.chat_history.config(state="disabled")
                        self.chat_history.see(tk.END)
                        continue
                    if kind == "status":
                        self.chat_history.config(state="normal")
                        _status_pos[0] = self.chat_history.index("end-1c")
                        self.chat_history.insert(tk.END, f"[{data}]")
                        self.chat_history.config(state="disabled")
                        self.chat_history.see(tk.END)
                        continue
                    # kind == "tok" — erase any status text before first token
                    if _status_pos[0] is not None:
                        self.chat_history.config(state="normal")
                        self.chat_history.delete(_status_pos[0], tk.END)
                        self.chat_history.config(state="disabled")
                        _status_pos[0] = None
                    self.chat_history.config(state="normal")
                    self.chat_history.insert(tk.END, data)
                    self.chat_history.config(state="disabled")
                    self.chat_history.see(tk.END)
            except _queue_mod.Empty:
                pass
            self.chat_history.after(50, poll)

        threading.Thread(target=worker, daemon=True).start()
        self.chat_history.after(50, poll)
#-------------------------
# END CHAT FUNCTIONALITY
#-------------------------

    def _on_action_change(self, *args):
        if self.action_var.get() == "diagnose_taxon":
            self.diagnose_frame.pack(fill="x", padx=5, pady=(0, 2))
        else:
            self.diagnose_frame.pack_forget()

    def _on_comp_action_change(self):
        if self._comp_action.get() == "diagnose_taxon":
            self.diagnose_frame.pack(fill="x", padx=5, pady=(0, 2))
        else:
            self.diagnose_frame.pack_forget()

    def _run_descriptions(self):
        self.output_mode.set(self._desc_output_mode.get())
        self.llm_mode.set(self._desc_llm_mode.get())
        self._active_verify_rounds = self._desc_verify_rounds.get()
        self.action_var.set(
            "generate_descriptions_with_lit" if self._desc_include_lit.get()
            else "generate_descriptions"
        )
        self.output  = self._desc_output
        self.run_btn = self._desc_run_btn
        self.run_action()

    def _run_comparisons(self):
        self.output_mode.set(self._comp_output_mode.get())
        self.llm_mode.set(self._comp_llm_mode.get())
        self._active_verify_rounds = self._comp_verify_rounds.get()
        self.action_var.set(self._comp_action.get())
        self.output  = self._comp_output
        self.run_btn = self._comp_run_btn
        self.run_action()

    def _run_keys(self):
        self.output_mode.set(self._keys_output_mode.get())
        self.llm_mode.set(self._keys_llm_mode.get())
        self._active_verify_rounds = self._keys_verify_rounds.get()
        self.action_var.set("generate_key")
        self.output  = self._keys_output
        self.run_btn = self._keys_run_btn
        self.run_action()

    def _show_preamble_popup(self):
        # Generate preview from the first selected analysis taxon (unless an override is set)
        if self._preamble_override:
            preview_text = self._preamble_override
        else:
            preview_text = ""
            label = ""
            for _iid in self._ana_tree.selection():
                _tags = set(self._ana_tree.item(_iid, "tags"))
                if "group_header" not in _tags and "includes_member" not in _tags:
                    label = self._ana_tree.item(_iid, "text")
                    break
            if label:
                cache_key = self._nom_label_to_dataid.get(label, label)
                report = self._resources_cache.get(cache_key, {}).get("report_text", "")
                # Preamble is sourced from the information report (name + hierarchy
                # + cleaned synonyms); falls back to just the name line.
                preview_text = build_preamble_from_report(report) or label

        win = tk.Toplevel(self.root)
        win.title("Preview / Edit Preamble")
        win.geometry("700x420")
        win.grab_set()

        info = ("Showing auto-generated preamble for the first selected taxon. "
                "Click 'Use This Preamble' to apply a custom preamble to all taxa, "
                "or 'Clear Override' to restore per-taxon auto-generation from cache.")
        tk.Label(win, text=info, wraplength=670, justify="left").pack(
            anchor="w", padx=10, pady=(10, 4))

        # Button row — packed FIRST with side="bottom" so the expanding text area never hides it
        btn_row = tk.Frame(win)
        btn_row.pack(side="bottom", fill="x", padx=10, pady=8)

        txt_frame = tk.Frame(win)
        txt_frame.pack(fill="both", expand=True, padx=10)
        txt_frame.grid_rowconfigure(0, weight=1)
        txt_frame.grid_columnconfigure(0, weight=1)
        txt = tk.Text(txt_frame, wrap="word")
        txt.grid(row=0, column=0, sticky="nsew")
        sb = tk.Scrollbar(txt_frame, orient="vertical", command=txt.yview)
        sb.grid(row=0, column=1, sticky="ns")
        txt.config(yscrollcommand=sb.set)
        if preview_text:
            txt.insert("1.0", preview_text)

        def _confirm():
            self._preamble_override = txt.get("1.0", tk.END).strip() or None
            win.destroy()
        def _clear():
            self._preamble_override = None
            win.destroy()
        tk.Button(btn_row, text="Use This Preamble", command=_confirm).pack(side="left", padx=(0, 8))
        tk.Button(btn_row, text="Clear Override",    command=_clear ).pack(side="left", padx=(0, 8))
        tk.Button(btn_row, text="Cancel", command=win.destroy).pack(side="left")
        win.wait_window()

    def _run_diagnose_taxon(self):
        """Run the diagnose_taxon action — separated from run_action for clarity."""
        # --- Build LLM configs (diagnose_taxon bypasses shared entity resolution) ---
        output_style_guide = self.load_style_guide_from_path(
            self.style_guide_path_var.get()
        )
        verify_style_path = self.verify_style_guide_path_var.get()
        verify_style_guide = (
            self.load_style_guide_from_path(verify_style_path)
            if verify_style_path else output_style_guide
        )
        llm_config = LLMConfig(
            model=self.output_model_var.get(),
            temperature=self.output_temp_var.get(),
            num_predict=2048,
            style_guide=output_style_guide,
            think=False,
            use_chat=False
        )
        verify_num_predict = max(self.verify_max_tokens_var.get(), 1024)
        verify_config = LLMConfig(
            model=self.verify_model_var.get(),
            temperature=self.verify_temp_var.get(),
            num_predict=verify_num_predict,
            style_guide=verify_style_guide,
            think=False,
            use_chat=False
        )

        # --- Validate index taxon from combobox ---
        index_display = self._diagnose_index_var.get().strip()
        if not index_display:
            messagebox.showerror(
                "Diagnose Taxon",
                "Select an index taxon from the drop-down."
            )
            return
        index_name = self._nom_label_to_dataid.get(index_display, index_display)
        index_taxon = next(
            (t for t in self.dataset.taxa if t.name == index_name), None
        )
        if index_taxon is None:
            messagebox.showerror("Diagnose Taxon", f"Taxon '{index_display}' not found in dataset.")
            return

        # --- Resolve comparison set from tree selection ---
        _sel_iids = self._ana_tree.selection()
        _group_names = [self._ana_tree.item(iid, "text") for iid in _sel_iids
                        if "group_header" in set(self._ana_tree.item(iid, "tags"))]
        _indiv_labels = [self._ana_tree.item(iid, "text") for iid in _sel_iids
                         if "group_header" not in set(self._ana_tree.item(iid, "tags"))
                         and "includes_member" not in set(self._ana_tree.item(iid, "tags"))]

        if _group_names or _indiv_labels:
            comparison_taxa = []
            if _group_names:
                try:
                    from group_operations import resolve_selection
                    flat_taxa = resolve_selection(
                        dataset=self.dataset, groups=self.groups,
                        selected_taxa=[], selected_groups=_group_names,
                        flatten_groups=True
                    )
                    comparison_taxa.extend(flat_taxa)
                except Exception as e:
                    messagebox.showerror("Group Error", str(e))
                    return
            for lbl in _indiv_labels:
                did = self._nom_label_to_dataid.get(lbl, lbl)
                t = next((x for x in self.dataset.taxa if x.name == did), None)
                if t:
                    comparison_taxa.append(t)
            comparison_taxa = [t for t in comparison_taxa if t.name != index_name]
        else:
            # No selection — all CARL-declared individual taxa except the index
            valid_ids = set(self._nom_label_to_dataid.values())
            comparison_taxa = [t for t in self.dataset.taxa
                               if t.name in valid_ids and t.name != index_name]

        # Deduplicate while preserving order
        seen = set()
        unique_comparison = []
        for t in comparison_taxa:
            if t.name not in seen:
                unique_comparison.append(t)
                seen.add(t.name)
        comparison_taxa = unique_comparison

        if len(comparison_taxa) < 2:
            messagebox.showerror(
                "Diagnose Taxon",
                "The comparison group must contain at least 2 taxa "
                "(after excluding the index taxon)."
            )
            return

        threshold = self.nn_threshold_var.get()

        self.output.delete(1.0, tk.END)
        self._llm_cancel.clear()
        self._set_run_btn_running()

        def _re_enable():
            self._set_run_btn_ready()

        try:
            _, _comp_excl, _ = (parse_wtsets(self.dataset_text)
                                if self.dataset_text else (set(), set(), {}))
            result = build_diagnosis_output(
                index_taxon, comparison_taxa, self.dataset, threshold,
                char_exclusions=_comp_excl
            )
            raw_text = format_diagnosis_output(result)

            self.output.insert(tk.END, "RAW OUTPUT\n\n")
            self.output.insert(tk.END, raw_text + "\n")
            self.analysis_raw_output = raw_text

            self.apply_llm_formatting(
                raw_text,
                llm_config=llm_config,
                verify_config=verify_config,
                is_diagnosis=True,
                on_done=_re_enable,
            )
        except Exception as e:
            _re_enable()
            traceback.print_exc()
            messagebox.showerror("Diagnosis Error", str(e))

    def run_action(self):
        """Execute the selected action."""

        # Ensure dataset is loaded
        if not self.dataset:
            messagebox.showerror("Error", "Please load a NEXUS file first.")
            return

        # Get selected action
        action = self.action_var.get()
        if not action:
            messagebox.showerror("Error", "Please select an action.")
            return

        # diagnose_taxon handles its own entity resolution and config building
        if action == "diagnose_taxon":
            self._run_diagnose_taxon()
            return

        # Get selected taxa and groups.
        # The taxa listbox shows nom-labels when a CARL block is loaded; convert
        # back to DataIDs so that resolve_selection() can match against dataset.taxa.
        _sel_iids = self._ana_tree.selection()
        selected_taxa_display, selected_groups = [], []
        for iid in _sel_iids:
            tags = set(self._ana_tree.item(iid, "tags"))
            text = self._ana_tree.item(iid, "text")
            if "group_header" in tags:
                selected_groups.append(text)
            elif "includes_member" not in tags:
                selected_taxa_display.append(text)
        selected_taxa = [self._nom_label_to_dataid.get(n, n)
                         for n in selected_taxa_display]

        # ==========================================================
        # RESOLVE TAXA AND GROUPS INTO TAXON OBJECTS
        # ==========================================================
        # When nothing is selected, resolve_selection() defaults to all
        # dataset taxa — bypassing the CARL-declared set.  Intercept here:
        # if the user selected nothing AND a CARL block is loaded, restrict
        # to the entities that have declared data pointers in the Derived View.
        nothing_selected = not selected_taxa and not selected_groups
        if nothing_selected and self._nom_label_to_dataid:
            valid_ids = set(self._nom_label_to_dataid.values())
            entities = [t for t in self.dataset.taxa if t.name in valid_ids]
        else:
            try:
                entities = resolve_selection(
                    dataset=self.dataset,
                    groups=self.groups,
                    selected_taxa=selected_taxa,
                    selected_groups=selected_groups,
                    flatten_groups=False,
                    group_data_ids=build_group_data_ids(self.carl_block),
                    member_data_ids=build_member_data_ids(self.carl_block),
                )
            except Exception as e:
                traceback.print_exc()
                messagebox.showerror("Selection Error", str(e))
                return
            if not entities:
                entities = list(self.dataset.taxa)

        # Rename DataID-named Taxon objects to their CARL nom-labels so that
        # build_temp_kg creates nom-label-keyed entries and all analysis output
        # uses proper nomenclatural names.  The permanent self.kg is untouched.
        entities = self._make_proxy_taxa(entities)

        # ==========================================================
        # BUILD TEMPORARY KNOWLEDGE GRAPH
        # ==========================================================
        try:
            temp_kg = build_temp_kg(self.dataset, self.kg, entities)
        except Exception as e:
            messagebox.showerror("Knowledge Graph Error", str(e))
            return

        _desc_exclusions, _comp_exclusions, _ = (
            parse_wtsets(self.dataset_text) if self.dataset_text else (set(), set(), {}))
        _char_groups = (parse_charsets(self.dataset_text)
                        if self.dataset_text else {})

        # Clear previous output
        self.output.delete(1.0, tk.END)

        action = self.action_var.get()
        # --------------------------------------------------
        # TOKEN MANAGEMENT (ALWAYS DYNAMIC)
        # --------------------------------------------------
        try:
            num_predict = estimate_num_predict_from_kg(
                self.dataset,
                entities,
                temp_kg,
                model_name=self.output_model_var.get(),
                model_size_gb=None,  # optional (you can add later)
                mode=self.llm_mode.get()  # or "fast"
            )
        except Exception as e:
            print(f"[WARNING] Token estimation failed: {e}")
            num_predict = 16384  # Fallback default

        # --------------------------------------------------
        # STYLE GUIDES
        # --------------------------------------------------
        output_style_guide = self.load_style_guide_from_path(
            self.style_guide_path_var.get()
        )

        # Optional override for verification
        verify_style_path = self.verify_style_guide_path_var.get()

        if verify_style_path:
            verify_style_guide = self.load_style_guide_from_path(verify_style_path)
        else:
            verify_style_guide = output_style_guide  # inherit

        # --------------------------------------------------
        # CONFIGS
        # --------------------------------------------------
        llm_config = LLMConfig(
            model=self.output_model_var.get(),
            temperature=self.output_temp_var.get(),
            num_predict=num_predict,
            style_guide=output_style_guide,
            think=False,
            use_chat=False
        )

        verify_num_predict = max(self.verify_max_tokens_var.get(), num_predict // 3)
        verify_config = LLMConfig(
            model=self.verify_model_var.get(),
            temperature=self.verify_temp_var.get(),
            num_predict=verify_num_predict,
            style_guide=verify_style_guide,
            think=False,
            use_chat=False
        )
        def _re_enable_run():
            self._set_run_btn_ready()

        # ==========================================================
        # 1. COMPARE TAXA / GROUPS
        # ==========================================================
        if action == "compare_taxa":
            self._llm_cancel.clear()
            self._set_run_btn_running()
            try:
                result = compare_taxa(self.dataset, entities, temp_kg,
                                     char_exclusions=_comp_exclusions)
                formatted_result = format_comparison(result)

                self.output.insert(tk.END, "RAW OUTPUT\n\n")
                self.output.insert(tk.END, formatted_result + "\n")
                self.analysis_raw_output = formatted_result

                self.apply_llm_formatting(
                    formatted_result,
                    llm_config=llm_config,
                    verify_config=verify_config,
                    on_done=_re_enable_run
                )

            except Exception as e:
                _re_enable_run()
                messagebox.showerror("Compare Error", str(e))

        # ==========================================================
        # 2. DISTINGUISH TAXA / GROUPS
        # ==========================================================
        elif action == "distinguish_taxa":
            self._llm_cancel.clear()
            self._set_run_btn_running()
            try:
                formatted_result = distinguish_taxa(
                    self.dataset,
                    entities,
                    temp_kg,
                    top_n=None,
                    char_exclusions=_comp_exclusions
                )

                self.output.insert(tk.END, "RAW OUTPUT\n\n")
                self.output.insert(tk.END, formatted_result + "\n")
                self.analysis_raw_output = formatted_result

                self.apply_llm_formatting(
                    formatted_result,
                    llm_config=llm_config,
                    verify_config=verify_config,
                    on_done=_re_enable_run
                )

            except Exception as e:
                _re_enable_run()
                messagebox.showerror("Distinguish Error", str(e))
        # ==========================================================
        # 2. GENERATE DESCRIPTIONS (STREAMING)
        # ==========================================================



        elif action == "generate_descriptions":

            def _is_api_model(model_name):
                return "/" in model_name or ":" not in model_name

            output_is_api = _is_api_model(llm_config.model)

            snapshot_entities = list(entities)
            snapshot_llm = llm_config
            snapshot_verify = verify_config

            if self._analysis_running:
                self.status_var.set("Analysis already running — please wait.")
                return

            def run_all():
                self._analysis_running = True
                self._llm_cancel.clear()
                self.output.after(0, self._set_run_btn_running)
                self._tpd_message = None
                try:
                    for i, taxon in enumerate(snapshot_entities):
                        if self._llm_cancel.is_set():
                            break
                        try:
                            raw_desc = generate_descriptions(
                                self.dataset,
                                self.kg,
                                [taxon],
                                build_base_description,
                                char_exclusions=_desc_exclusions,
                                char_groups=_char_groups
                            ).strip()

                            # Size the output budget to THIS taxon's raw text
                            # (per-taxon, from the actual text, capped realistically).
                            snapshot_llm.num_predict = estimate_num_predict_from_text(
                                raw_desc, model_name=snapshot_llm.model,
                                mode=self.llm_mode.get())

                            self.output.after(
                                0,
                                lambda r=raw_desc: self.output.insert(
                                    tk.END, f"\n{'='*60}\n{r}\n"
                                )
                            )
                            self.analysis_raw_output = raw_desc

                            self.apply_llm_formatting(
                                raw_desc,
                                llm_config=snapshot_llm,
                                verify_config=snapshot_verify,
                                seq_delay=0,
                                label=taxon.name.replace("_", " "),
                                blocking=True
                            )
                            if self._llm_cancel.is_set():
                                break
                            self.apply_nlg_formatting(
                                raw_desc, mode="description",
                                label=taxon.name.replace("_", " "))

                            if self._tpd_message:
                                msg = self._tpd_message
                                self.output.after(0, lambda m=msg: self.status_var.set(m))
                                break

                        except Exception as e:
                            self.output.after(
                                0,
                                lambda msg=str(e): self.output.insert(
                                    tk.END, f"\nERROR: {msg}\n"
                                )
                            )
                finally:
                    self._analysis_running = False
                    self.output.after(0, self._set_run_btn_ready)
                    status = "Cancelled." if self._llm_cancel.is_set() else "Ready"
                    self.output.after(0, lambda s=status: self.status_var.set(s))

            threading.Thread(target=run_all, daemon=True).start()

        # ==========================================================
        # 3. GENERATE DESCRIPTIONS WITH LITERATURE
        # ==========================================================
        elif action == "generate_descriptions_with_lit":

            def _is_api_model(model_name):
                return "/" in model_name or ":" not in model_name

            output_is_api = _is_api_model(llm_config.model)

            # Warn if some taxa have no cached literature
            uncached = [
                t for t in entities
                if not entry_has_data(self._lit_cache.get(t.name))
            ]
            if uncached:
                names = ", ".join(t.name.replace("_", " ") for t in uncached[:5])
                if len(uncached) > 5:
                    names += f" … (+{len(uncached) - 5} more)"
                if not messagebox.askyesno(
                    "Cache Incomplete",
                    f"{len(uncached)} taxon/taxa have no cached literature:\n{names}\n\n"
                    "These will be described from matrix data only. Continue?"
                ):
                    return

            snapshot_entities        = list(entities)
            snapshot_llm             = llm_config
            snapshot_verify          = verify_config
            snapshot_cache           = dict(self._lit_cache)
            snapshot_res_cache       = dict(self._resources_cache)
            snapshot_mode            = self.output_mode.get()
            snapshot_llm_mode        = self.llm_mode.get()
            snapshot_include_fields  = set(self._lit_include_fields)
            snapshot_preamble_override = self._preamble_override

            if self._analysis_running:
                self.status_var.set("Analysis already running — please wait.")
                return

            def run_all_lit():
                self._analysis_running = True
                self._llm_cancel.clear()
                self.output.after(0, self._set_run_btn_running)
                self._tpd_message = None
                try:
                    for i, taxon in enumerate(snapshot_entities):
                        if self._llm_cancel.is_set():
                            break
                        try:
                            # 1. Build matrix description
                            self.output.after(
                                0, lambda n=taxon.name: self.status_var.set(
                                    f"Building matrix description: {n}..."
                                )
                            )
                            matrix_desc = generate_descriptions(
                                self.dataset, self.kg, [taxon], build_base_description,
                                char_exclusions=_desc_exclusions,
                                char_groups=_char_groups
                            ).strip()

                            # 2. Build the preamble from the information report
                            # (name + hierarchy + cleaned synonyms); fall back to
                            # just the taxon name. Same text for the raw and LLM
                            # blocks.
                            if snapshot_preamble_override:
                                ro_preamble  = snapshot_preamble_override
                                llm_preamble = snapshot_preamble_override
                            else:
                                report = snapshot_res_cache.get(taxon.name, {}).get("report_text", "")
                                pre = (build_preamble_from_report(report)
                                       or taxon.name.replace("_", " "))
                                ro_preamble  = pre
                                llm_preamble = pre

                            display_name = taxon.name.replace("_", " ")

                            # 3. Raw output block: [RO preamble] --- [matrix output]
                            def _insert_raw(
                                dn=display_name, rp=ro_preamble, md=matrix_desc
                            ):
                                self.output.insert(tk.END, f"\n{'='*60}\n")
                                if rp:
                                    self.output.insert(tk.END, rp + "\n")
                                    self.output.insert(tk.END, "---\n")
                                else:
                                    self.output.insert(tk.END, f"{dn}\n\n")
                                self.output.insert(tk.END, md + "\n")

                            self.output.after(0, _insert_raw)

                            # 3b. NLG output block (deterministic, non-LLM) — mirrors
                            # the plain Descriptions path; transforms the matrix output.
                            self.apply_nlg_formatting(
                                matrix_desc, mode="description", label=display_name)

                            # 4. LLM output block (if LLM mode is on and a model is selected)
                            if snapshot_mode == "llm" and self._llm_model_is_set(snapshot_llm.model):
                                # Size the output budget to this taxon's raw text +
                                # preamble (per-taxon, capped realistically).
                                snapshot_llm.num_predict = estimate_num_predict_from_text(
                                    matrix_desc + "\n" + (llm_preamble or ""),
                                    model_name=snapshot_llm.model,
                                    mode=snapshot_llm_mode)
                                self.output.after(
                                    0, lambda n=taxon.name: self.status_var.set(
                                        f"Formatting with literature: {n}..."
                                    )
                                )

                                def _status(msg):
                                    self.output.after(
                                        0, lambda m=msg: self.status_var.set(m)
                                    )

                                # Always show the "LLM OUTPUT — taxon" header (as in
                                # the no-literature path), then the preamble (if any),
                                # then stream the prose tokens below.
                                def _insert_llm_header(dn=display_name, lp=llm_preamble):
                                    self.output.insert(tk.END, f"\nLLM OUTPUT — {dn}\n\n")
                                    if lp:
                                        self.output.insert(tk.END, lp + "\n")
                                        self.output.insert(tk.END, "---\n")
                                self.output.after(0, _insert_llm_header)

                                llm_tokens = []
                                for token in format_with_literature_stream(
                                    matrix_desc, llm_preamble, taxon.name, snapshot_llm,
                                    status_fn=_status,
                                    cancel_fn=self._llm_cancel.is_set,
                                ):
                                    if self._llm_cancel.is_set():
                                        break
                                    self.output.after(
                                        0, lambda t=token: self.output.insert(tk.END, t)
                                    )
                                    llm_tokens.append(token)
                                if self._llm_cancel.is_set():
                                    break
                                f_captured = (
                                    "".join(llm_tokens).strip()
                                    or "[No output — model returned empty response.]"
                                )
                                self.output.after(0, lambda: self.output.insert(tk.END, "\n"))

                                # 5. Verification (full mode only, and only if a verify model is set)
                                if not self._llm_cancel.is_set() and snapshot_llm_mode != "fast" and self._llm_model_is_set(snapshot_verify.model):
                                    combined_raw = (
                                        f"{llm_preamble}\n\n{matrix_desc}"
                                        if llm_preamble else matrix_desc
                                    )
                                    self.output.after(
                                        0, lambda: self.status_var.set(
                                            f"Running {snapshot_verify.model} "
                                            "(verification)..."
                                        )
                                    )
                                    verification = verify_output_with_llm(
                                        combined_raw, f_captured,
                                        config=snapshot_verify,
                                        status_fn=_status,
                                        cancel_fn=self._llm_cancel.is_set,
                                    )
                                    display_verification = verification_display_text(
                                        verification, include_reasoning=False)
                                    v_header = f"\nVERIFICATION — {display_name}\n\n"
                                    self.output.after(
                                        0, lambda vh=v_header, v=display_verification: (
                                            self.output.insert(tk.END, vh),
                                            self.output.insert(
                                                tk.END,
                                                (v or "[No verification output.]") + "\n"
                                            ),
                                        )
                                    )

                            if self._tpd_message:
                                msg = self._tpd_message
                                self.output.after(
                                    0, lambda m=msg: self.status_var.set(m)
                                )
                                break

                        except Exception as e:
                            self.output.after(
                                0, lambda msg=str(e): self.output.insert(
                                    tk.END, f"\nERROR: {msg}\n"
                                )
                            )
                finally:
                    self._analysis_running = False
                    self.output.after(0, self._set_run_btn_ready)
                    status = "Cancelled." if self._llm_cancel.is_set() else "Ready"
                    self.output.after(0, lambda s=status: self.status_var.set(s))

            threading.Thread(target=run_all_lit, daemon=True).start()

        # ==========================================================
        # 4. GENERATE IDENTIFICATION KEY
        # ==========================================================
        elif action == "generate_key":
            self._llm_cancel.clear()
            self._set_run_btn_running()
            try:
                if not entities:
                    self.output.insert(tk.END, "No taxa or groups selected.")
                    _re_enable_run()
                    return

                algo   = self._keys_algo_var.get()
                mode   = self._keys_format_var.get()
                try:
                    repeat_penalty = float(self._keys_penalty_var.get())
                    if not (0.0 < repeat_penalty <= 1.0):
                        raise ValueError
                except ValueError:
                    messagebox.showerror(
                        "Invalid Repeat Penalty",
                        "Repeat penalty must be a number between 0 (exclusive) and 1 (inclusive).")
                    _re_enable_run()
                    return

                preclusion = (parse_precludes(self.dataset_text, self.dataset)
                              if self.dataset_text else {})
                _, _, char_weights = (parse_wtsets(self.dataset_text)
                                      if self.dataset_text else (set(), set(), {}))

                stats_lines, key_lines = generate_key(
                    temp_kg, self.dataset, entities,
                    algo=algo, mode=mode,
                    repeat_penalty=repeat_penalty,
                    preclusion=preclusion,
                    char_weights=char_weights)

                n_taxa  = len(entities)
                algo_label = "DG" if algo == "si" else algo.upper()
                mode_label = "Multi-arm" if mode == "multi" else "Binary"
                header = (f"IDENTIFICATION KEY  [{algo_label} / {mode_label}]"
                          f"  —  {n_taxa} taxon/taxa")
                SEP = "=" * 70

                # Programmatic If/then scaffold: deterministic structure and
                # routing; the LLM only naturalises the "X = Y" conditions.
                scaffold_lines = preformat_key_lines(key_lines)
                out_lines = [SEP, header, SEP, *stats_lines, *scaffold_lines]
                key_text  = "\n".join(out_lines)

                self.output.insert(tk.END, key_text + "\n")
                self.analysis_raw_output = key_text

                # Rewrite/verify only the couplet lines — the header and key
                # statistics are metadata, not key content, and including them
                # makes the verifier flag them as "omitted" from the rewrite.
                self.apply_llm_formatting(
                    "\n".join(scaffold_lines),
                    llm_config=llm_config,
                    verify_config=verify_config,
                    is_key=True,
                    on_done=_re_enable_run
                )
                # NLG: naturalise the full key ("=" -> is/are); banner/stats/
                # separators pass through untouched.
                self.apply_nlg_formatting(key_text, mode="key")

            except Exception as e:
                self.output.insert(tk.END, f"Key Generation Error: {e}\n")
                _re_enable_run()
    # ==========================================================
    # UNKNOWN ACTION
    # ==========================================================
        else:
            messagebox.showerror("Error", f"Unknown action: {action}")


    



# -------------------------
# RUN APP
# -------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = TaxonGPT_UI(root)
    root.mainloop()
