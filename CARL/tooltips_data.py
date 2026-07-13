"""
tooltips_data.py — single source of truth for CARL tooltip text AND the
manual's button-reference / tab-reference tables (dict-first).

Hand-authored. CARL_user_manual.html's reference tables are GENERATED from
GROUPS/TABS below (see manual_tables.py) — never hand-edit those tables in the
HTML directly; edit here and regenerate.

Each GROUPS entry is a dict:
  label        : the control's real, stable widget text — used to match a live
                 widget for tooltips (normalised). Omit when the widget has no
                 stable/unique text (use `key` instead).
  manual_label : text shown in the manual's Button/Widget column. Defaults to
                 `label` if omitted — set explicitly when the manual should show
                 a fuller/compound description (e.g. "Output Mode: Raw only")
                 that differs from the plain widget text ("Raw only").
  key          : explicit `_carl_tooltip_key`, for label-less widgets
                 (spinboxes/entries/dropdowns), per-instance text, or to
                 disambiguate a label that collides with another control
                 elsewhere in the app (see NOTES below).
  location     : optional, for the manual table's Location column.
  html         : rich HTML — the manual table's Function/Description cell.
                 The tooltip is derived from it (tags stripped, first sentence).

NOTES on collisions / label-less widgets handled via `key` (set in code with
`widget._carl_tooltip_key = "..."`, optionally `_carl_tooltip_fmt = {...}`):
  lm.style_guide_entry, lm.style_guide_browse, lm.model_test_dropdown
  db.priority (per-instance, {name}), dwc.include, help.clear
  nom.preview_toggle        (button text alternates ▼/▲ Preview)
  analyses.save_output      ("Save…" collides with Nomenclature's "Save")
  analyses.llm_mode_dropdown (OptionMenu text changes to the selected value)
  comp.max_differences, keys.repeat_weight
  pref.working_dir_browse, pref.font_size_general, pref.font_size_mono
Widgets whose plain label is unique across the app (Run, Copy, Stop, Apply,
Compare/Distinguish/Diagnose, IG/DG, Binary/Multi-arm, etc.) are matched by
label — Plugins' own Run/Stop/Apply/etc. are protected from the shared
Analyses-tab wording by the Plugins panel's `_carl_tooltip_text` override,
which is checked before the dict (see plugin_operations.apply_manual_tooltips).
"""

GROUPS = {
    "Main navigation": [
        {"label": "File",        "text": "Load, create, and edit data."},
        {"label": "Information", "text": "Retrieve taxonomic information."},
        {"label": "Analyses",    "text": "Build descriptions, comparisons, and keys."},
        {"label": "Chatbot",     "text": "Ask CARL about the nomenclatural codes."},
        {"label": "Plugins",     "text": "Generate plugin descriptors and run plugins."},
        {"label": "Settings",    "text": "Select databases, language models, and CARL settings."},
        {"label": "About",       "text": "Help and citation."},
    ],

    "Nomenclature tab": [
        {"label": "Load NEXUS", "location": "File toolbar",
         "html": 'Opens a file dialog to load a <code>.nex</code> file. Replaces the current '
                 'session. Accepts any NEXUS file containing a <code>BEGIN CARL;</code> block, a '
                 '<code>BEGIN DATA;</code> block, or both.'},
        {"label": "Save", "location": "File toolbar",
         "html": 'Saves all current content — DATA block, CARL block, and any other blocks in '
                 'the file (e.g. TREES) — to the currently loaded file, overwriting it in place. '
                 'If no file is loaded yet (e.g. after clicking <strong>New</strong> in the '
                 'Editor), this behaves as <strong>Save As…</strong> and prompts for a path. '
                 'This is the only place in CARL where file saving occurs.'},
        {"label": "Save As…", "location": "File toolbar",
         "html": 'Saves all current content to a new file chosen via a save dialog. The DATA '
                 'block is regenerated in full from the in-memory dataset (so any added DataIDs '
                 'or characters are included), the CARL block is serialised from current '
                 'declarations, and any other blocks (e.g. TREES) in the original file are '
                 'preserved. The new file becomes the active file for subsequent saves.'},
        {"label": "+ Add", "location": "Statement toolbar",
         "html": 'Opens the Add Statement dialog. Select a statement type (Definition, Renames, '
                 'Synonymizes, Includes, Divides) at the top, then fill in the required fields. '
                 'The new statement appears in the Statements list immediately and the Derived '
                 'View updates in real time. See <a href="#nom-add">Adding declarations</a> for '
                 'full field descriptions.'},
        {"label": "Edit", "location": "Statement toolbar",
         "html": 'Opens the Edit Statement dialog for the statement currently selected in the '
                 'Statements list. Pre-fills all fields from the existing statement. Also '
                 'triggered by double-clicking any row in the Statements list.'},
        {"label": "Delete", "location": "Statement toolbar",
         "html": 'Deletes all selected statements after a confirmation prompt. Multiple '
                 'statements can be selected with <kbd>Ctrl+click</kbd> or <kbd>Shift+click</kbd> '
                 'before clicking Delete. Changes propagate immediately to the Derived View and '
                 'Records tab.'},
        {"label": "Assign Rank…", "location": "Statement toolbar",
         "html": 'Opens a small dialog with a rank dropdown (species, genus, family, etc.). '
                 'Applies the chosen rank to <em>all</em> selected statements at once. Useful for '
                 'bulk rank assignment after using <strong>Create Taxa…</strong> to import many '
                 'DataIDs simultaneously.'},
        {"key": "nom.preview_toggle", "manual_label": "▼ Preview / ▲ Preview",
         "location": "Statement toolbar",
         "html": 'Toggles a collapsible panel below the main three-pane area showing the '
                 'serialised <code>BEGIN CARL;</code> block text exactly as it will be written '
                 'to the file. Useful for reviewing block syntax before saving. The Copy button '
                 'inside the panel copies the text to the clipboard.'},
        {"label": "+Add", "location": "Derived View header",
         "html": 'Opens the Add Statement dialog pre-filled with the entity (or entities) '
                 'currently selected in the Derived View as objects. Useful for quickly creating '
                 'a relationship starting from a taxon already visible in the tree — for '
                 'example, select two species in the Derived View and click <strong>+Add</strong> '
                 'to open a Synonymizes dialog with those species pre-filled as objects.'},
        {"label": "Create Taxa…", "location": "DataID Pool header",
         "html": 'Opens a dialog listing all unassigned DataIDs in the pool. Set a single status '
                 '(<code>is</code> or <code>is_new</code>) and a rank that will apply to all of '
                 'them, then confirm. CARL creates one Definition statement per unassigned '
                 'DataID, each pointing back to its own DataID. Already-assigned DataIDs are '
                 'highlighted grey and skipped. Combine with <strong>Assign Rank…</strong> to '
                 'update ranks in bulk afterwards.'},
    ],

    "Editor tab": [
        {"label": "New",
         "html": 'Starts a blank session: creates an empty dataset and an empty CARL block. Both '
                 'the Editor and the Nomenclature tab become active immediately. DataIDs added '
                 "afterwards appear in the Nomenclature tab's DataID Pool in real time. If a "
                 'file is already loaded, CARL asks for confirmation before discarding it.'},
        {"label": "+ Add DataID",
         "html": 'Prompts for a DataID name (underscores required in place of spaces, e.g. '
                 '<code>Puma_concolor</code>). Appends a new row to the matrix with all states '
                 'coded as missing (<code>M</code>). The new DataID immediately appears in the '
                 "left pane and in the Nomenclature tab's DataID Pool. Select it and click "
                 'states in the right pane to begin coding.'},
        {"label": "+ Add Character",
         "html": 'Opens a dialog to define a new character: enter the character name, then add '
                 'at least two state labels using the <strong>+ Add State</strong> button. On '
                 'confirmation, the character is appended to the matrix (all existing DataIDs '
                 'get <code>M</code> for it) and immediately appears in the right pane for every '
                 'DataID.'},
    ],

    "Information tab": [
        {"label": "Fetch All",
         "html": 'Queries all enabled data providers for every fetchable, uncached taxon. The '
                 'cache is written after each taxon so a partial run is never lost. '
                 'Already-fetched taxa are skipped.'},
        {"label": "Fetch Selected",
         "html": 'Fetches only the currently selected rows. Use <kbd>Shift+click</kbd> for a '
                 'range; <kbd>Ctrl+click</kbd> for individual toggles.'},
        {"key": "info.cancel_fetch", "manual_label": "Cancel (stop fetch)",
         "html": 'Stops the current fetch run after the current taxon completes. Already-cached '
                 'taxa are preserved.'},
        {"label": "Clear All",
         "html": 'Deletes every cached record for the current file &mdash; both the fetched '
                 'reports and the Darwin Core fields. This cannot be undone.'},
        {"label": "Clear Selected",
         "html": 'Deletes the cached report and Darwin Core fields for the currently selected '
                 'taxa only. Use <kbd>Shift+click</kbd> for a range; <kbd>Ctrl+click</kbd> for '
                 'individual toggles.'},
        {"label": "Export as .txt",
         "html": 'Writes the full plain-text report for the selected taxon to a <code>.txt</code> '
                 'file. Select a single row first, then choose a save location.'},
        {"label": "Export DC",
         "html": 'Writes Darwin Core records for all selected taxa to a CSV file. The format is '
                 "compatible with GBIF's Integrated Publishing Toolkit (IPT). Each row is one "
                 'taxon; columns are the Darwin Core terms ticked Retrieve in Settings → '
                 'Databases.'},
        {"label": "Commit DC", "location": "Darwin Core Fields popup",
         "html": 'Save DC edits.'},
        {"label": "Save Comments", "location": "Darwin Core Fields popup",
         "html": 'Save comments.'},
        {"label": "Use This Preamble", "location": "Darwin Core Fields popup",
         "html": 'Use this record as the preamble in Analyses → Descriptions (for every taxon).'},
        {"label": "Clear Override", "location": "Darwin Core Fields popup",
         "html": 'Clear the fixed preamble set by “Use This Preamble” — Analyses → Descriptions '
                 'goes back to generating each taxon’s preamble from its own record.'},
    ],

    "Descriptions tab": [
        {"key": "analyses.output_mode_raw", "manual_label": "Output Mode: Raw only",
         "html": 'Generate output deterministically from the matrix — no LLM required.'},
        {"key": "analyses.output_mode_llm", "manual_label": "Output Mode: Raw + LLM",
         "html": 'Generate raw output first, then pass it to the Output Model for reformatting '
                 'as prose. Requires a model configured in Settings → LLM Settings.'},
        {"key": "analyses.output_mode_nlg", "manual_label": "Output Mode: Raw + NLG",
         "html": 'Generate raw output first, then a deterministic natural-language rendering '
                 'below it: the character↔state delimiter is replaced by "is"/"are", chosen '
                 'from the grammatical number of the character name\'s head noun. Programmatic, '
                 'offline, no LLM required.'},
        {"key": "analyses.llm_mode_dropdown", "manual_label": "LLM Mode: Fast / Full",
         "html": 'Fast = reformat only, no verification. Full = reformat, then verify (and '
                 'optionally correct) with the Verification Model. See Part B.'},
        {"label": "Include Literature", "manual_label": "Include Literature (checkbox)",
         "html": 'Prepend a preamble from the cached Information tab record to each description. '
                 'Has no effect if no record is cached for that taxon.'},
        {"label": "Preview/Edit Preamble",
         "html": 'Opens an editable preview of the preamble for the current selection. Changes '
                 'apply to the current run only.'},
        {"key": "analyses.run", "manual_label": "Run",
         "html": 'Runs the current analysis for the selected taxa or groups (all taxa if none '
                 'selected). Processed one at a time; output appears progressively.'},
        {"key": "analyses.copy", "manual_label": "Copy",
         "html": 'Copies the currently displayed output to the clipboard.'},
        {"key": "analyses.save_output", "manual_label": "Save…",
         "html": 'Writes the output text to a plain-text <code>.txt</code> file at a path you '
                 'choose.'},
    ],

    "Comparisons tab": [
        {"key": "analyses.output_mode_raw", "manual_label": "Output Mode: Raw only",
         "html": 'Generate output deterministically from the matrix — no LLM required.'},
        {"key": "analyses.output_mode_llm", "manual_label": "Output Mode: Raw + LLM",
         "html": 'Generate raw output first, then pass it to the Output Model for reformatting '
                 'as prose.'},
        {"key": "analyses.llm_mode_dropdown", "manual_label": "LLM Mode: Fast / Full",
         "html": 'Fast = reformat only; Full = reformat then verify. See Part B.'},
        {"label": "Compare", "manual_label": "Action: Compare",
         "html": 'Full character-by-character table for all selected taxa.'},
        {"label": "Distinguish", "manual_label": "Action: Distinguish",
         "html": 'Table of only the characters on which the selected taxa differ.'},
        {"label": "Diagnose", "manual_label": "Action: Diagnose",
         "html": 'Minimal diagnostic character combinations (size 1, 2, or 3) that uniquely '
                 'identify the index taxon against all comparison taxa, plus nearest '
                 'neighbours.'},
        {"key": "comp.max_differences", "manual_label": "Max differences (spinner)",
         "html": 'Nearest-neighbour threshold for Diagnose: comparison taxa differing from the '
                 'index taxon by at most this many character states are listed as nearest '
                 'neighbours. Range 1–20; default 3.'},
        {"key": "analyses.run", "manual_label": "Run",
         "html": 'Executes the selected action for the current taxon/group selection.'},
        {"key": "analyses.copy", "manual_label": "Copy",
         "html": 'Copies the currently displayed output to the clipboard.'},
        {"key": "analyses.save_output", "manual_label": "Save…",
         "html": 'Writes the output to a plain-text <code>.txt</code> file.'},
    ],

    "Keys tab": [
        {"label": "IG", "manual_label": "Algorithm: IG",
         "html": 'Use Information Gain (Shannon entropy) scoring. Maximises entropy reduction at '
                 'each node. Recommended default.'},
        {"label": "DG", "manual_label": "Algorithm: DG",
         "html": "Use Diversity Gain (Simpson's Index) scoring. Lookahead approach; may produce "
                 'shallower keys for skewed state distributions.'},
        {"label": "Binary", "manual_label": "Format: Binary",
         "html": 'Classic two-lead dichotomous couplets (a / b).'},
        {"label": "Multi-arm", "manual_label": "Format: Multi-arm",
         "html": 'One lead per distinct character state; produces shorter keys.'},
        {"key": "keys.repeat_weight", "manual_label": "Repeat weight (field)",
         "html": 'Multiplicative penalty on reusing a character within a branch. Lower = '
                 'stronger penalty. Default 0.05. Range 0–1.'},
        {"key": "analyses.run", "manual_label": "Run",
         "html": 'Generates the key for the selected taxa and groups.'},
        {"key": "analyses.copy", "manual_label": "Copy",
         "html": 'Copies the full key output to the clipboard.'},
        {"key": "analyses.save_output", "manual_label": "Save…",
         "html": 'Writes the key output to a plain-text <code>.txt</code> file.'},
    ],

    "Preferences tab": [
        {"key": "pref.font_size_general", "manual_label": "General text (pt) (spinbox 7–24)",
         "html": 'Point size for all interface text: labels, menus, buttons, and tree rows.'},
        {"key": "pref.font_size_mono", "manual_label": "Code/output text (pt) (spinbox 7–24)",
         "html": 'Point size for monospace text: analyses output, CARL block preview, and the '
                 'information report.'},
        {"label": "Apply",
         "html": 'Applies the new font sizes immediately without restarting CARL. Sizes are '
                 'saved to settings and restored at next launch.'},
        {"key": "pref.working_dir_browse",
         "manual_label": "Working Directory (entry + Browse…)",
         "html": 'Default folder opened by File → Open and File → Save dialogs. When blank, '
                 'dialogs open at the operating system default location.'},
    ],

    "LM Settings tab": [
        {"label": "Show", "location": "API keys",
         "text": "Show the API key."},
        {"label": "Free Models Only (OpenRouter)",
         "text": "Only show free OpenRouter models."},
        {"label": "Save API Keys",
         "text": "Save the API keys to CARL's local settings file."},
        {"label": "Fetch Models",
         "text": "Populate the model dropdowns with available models from the listed sources."},
        {"label": "Test Model",
         "text": "Test the selected model with a simple “Hello” query."},
        {"label": "Reset to Defaults",
         "text": "Restore all settings to their defaults."},
        {"key": "lm.style_guide_entry", "location": "Style guide",
         "text": "Path to the style guide file."},
        {"key": "lm.style_guide_browse", "location": "Style guide",
         "text": "Select the style guide file."},
        {"key": "lm.model_test_dropdown", "location": "Model test",
         "text": "Select a model to test."},
    ],

    "Databases tab": [
        {"label": "Open ZooBank verification page",
         "text": "Open ZooBank so this computer's network address can complete verification."},
        {"key": "db.priority", "location": "Data providers",
         "text": "Set the {name} search priority (1 = highest)."},
        {"key": "dwc.include", "location": "Darwin Core fields",
         "text": "Include this field in exported Darwin Core records."},
    ],

    "Help tab": [
        {"label": "Search",   "text": "Search the manual."},
        {"label": "Next",     "text": "Go to the next match."},
        {"label": "Previous", "text": "Go to the previous match."},
        {"key": "help.clear", "text": "Clear the search."},
    ],

    "Plugins tab": [
        {"label": "Open Descriptor…", "location": "Run Plugin",
         "html": 'Load a plugin <code>.json</code> descriptor into the Run Plugin tab.'},
        {"label": "Run", "location": "Run Plugin — command bar",
         "html": 'Execute the assembled command. Required fields must be filled in first.'},
        {"label": "Stop", "location": "Run Plugin — command bar",
         "html": 'Terminate the running plugin process.'},
        {"label": "Rebuild", "location": "Run Plugin — command bar",
         "html": 'Discard manual edits to the command box and regenerate it from the current '
                 'field values.'},
        {"label": "Clear", "location": "Run Plugin — Output",
         "html": 'Clear the terminal output area.'},
        {"label": "Text…", "location": "Run Plugin — Results",
         "html": 'Browse to a text or log file and add it to Results.'},
        {"label": "Tree…", "location": "Run Plugin — Results",
         "html": 'Browse to a tree file and add it to Results.'},
        {"label": "Image…", "location": "Run Plugin — Results",
         "html": 'Browse to an image file and add it to Results.'},
        {"label": "⧉ Pop out", "location": "Run Plugin — Results",
         "html": 'Open the selected result in a dedicated window — the text editor, Phylogeny '
                 'Viewer, or Image Viewer.'},
        {"label": "New", "location": "Generate Descriptor — toolbar",
         "html": 'Start a new, empty descriptor after confirming any unsaved changes.'},
        {"label": "Open…", "location": "Generate Descriptor — toolbar",
         "html": 'Open an existing descriptor for editing.'},
        {"label": "Save", "location": "Generate Descriptor — toolbar",
         "html": 'Save the descriptor to its current file (prompts for a path if it has none).'},
        {"label": "Save As…", "location": "Generate Descriptor — toolbar",
         "html": 'Save the descriptor to a new file.'},
        {"label": "+ Add", "location": "Generate Descriptor — Sections / Fields / Output",
         "html": 'Add a new section, field, or output-file entry to the active editor.'},
        {"label": "Delete", "location": "Generate Descriptor — Sections / Fields / Output",
         "html": 'Remove the selected section, field, or output-file entry.'},
        {"label": "Duplicate", "location": "Generate Descriptor — Fields",
         "html": 'Copy the selected field.'},
        {"label": "▲", "location": "Generate Descriptor — Sections / Fields / Output",
         "html": 'Move the selected section, field, or output-file entry up.'},
        {"label": "▼", "location": "Generate Descriptor — Sections / Fields / Output",
         "html": 'Move the selected section, field, or output-file entry down.'},
        {"label": "Rename", "location": "Generate Descriptor — Fields",
         "html": 'Rename the selected section.'},
        {"label": "Apply", "location": "Generate Descriptor — Plugin Info / Field / Output",
         "html": "Commit the current form's edits to the descriptor."},
    ],

    "Common dialog buttons": [
        {"label": "OK", "location": "Dialogs",
         "html": 'Save and close.'},
        {"label": "Cancel", "location": "Dialogs",
         "html": 'Close without saving.'},
        {"label": "Close", "location": "Dialogs",
         "html": 'Close without saving.'},
    ],
}

# Notebook tab-label tooltips / Overview "Tab reference" table, keyed by tab label.
TABS = {
    "Nomenclature": "Load a NEXUS file and create, edit, rank, and preview the taxonomic "
                    "statements in its CARL block.",
    "Editor": "Enter and edit DataIDs, characters, and character states in the NEXUS matrix.",
    "Information": "Retrieve, review, resolve, and export external biodiversity records for "
                   "your taxa.",
    "Descriptions": "Generate one ordered, matrix-derived description per selected taxon or "
                    "group, with an optional natural-language rewrite.",
    "Comparisons": "Compare shared and differing states, distinguish taxa, or diagnose one "
                   "taxon against others.",
    "Keys": "Build a dichotomous identification key using Information Gain or Diversity Gain "
            "scoring, in binary or multi-arm form.",
    "Multi-Access Key": "Build an interactive polyclave — add character-state criteria in any "
                        "order and see which taxa remain compatible.",
    "Chat": "Ask Carl questions about your data and the nomenclatural codes.",
    "Run Plugin": "Configure and run an external command-line program from a plugin descriptor.",
    "Generate Descriptor": "Create or edit a plugin descriptor and preview its JSON.",
    "LM Settings": "Configure language-model providers, API keys, generation and verification "
                   "models, temperatures, and style guides.",
    "Databases": "Choose biodiversity data providers, priorities, retrieval limits, API keys, "
                 "and Darwin Core fields.",
    "Preferences": "Adjust interface and output font sizes and the default working directory.",
    "Help": "Search and browse this user manual.",
    "Citation": "View the recommended CARL citation, acknowledgements, and licence.",
}


def _normalise(value: str) -> str:
    value = " ".join((value or "").replace("…", "").split()).strip()
    return value.lower().rstrip(":").replace("▼ ", "").replace("▲ ", "").replace("↗", "").strip()


def _strip_tags(fragment: str) -> str:
    import re, html as htmllib
    text = re.sub(r"<[^>]+>", "", fragment)
    return " ".join(htmllib.unescape(text).split()).strip()


def _first_sentence(text: str, cap: int = 220) -> str:
    import re
    match = re.search(r"(.+?[.!?])(?:\s+[A-Z(]|\s*$)", text)
    sentence = match.group(1).strip() if match else text.strip()
    if len(sentence) > cap:
        sentence = sentence[:cap - 1].rstrip() + "…"
    return sentence


def _tooltip_text_for(entry: dict) -> str:
    if entry.get("text"):
        return entry["text"]
    return _first_sentence(_strip_tags(entry.get("html", "")))


def build_maps():
    """Return (by_label, by_key, tab_help) derived from GROUPS and TABS."""
    by_label, by_key = {}, {}
    for entries in GROUPS.values():
        for entry in entries:
            tip = _tooltip_text_for(entry)
            if entry.get("key"):
                by_key.setdefault(entry["key"], tip)
            elif entry.get("label"):
                by_label.setdefault(_normalise(entry["label"]), tip)
    tab_help = {_normalise(k): v for k, v in TABS.items()}
    return by_label, by_key, tab_help
