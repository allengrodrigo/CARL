# CARL Plugin Descriptor Specification — v1.0

A CARL plugin descriptor is a JSON file that describes a single external
command-line tool. CARL reads the descriptor at startup, generates a UI panel
dynamically from it, assembles the command line when the user clicks **Run**,
streams the tool's output, and lists the files it produces.

CARL also ships a graphical **descriptor builder** (the *Generate Descriptor*
tab) that writes conformant descriptors without hand-editing JSON.

---

## 1. File naming and location

| Location | Purpose |
|---|---|
| `plugins/bundled/` | Shipped with CARL; maintained by CARL authors. |
| `plugins/user/` | Dropped in by the user or third-party developers. |

File name: `<plugin_id>.json` (must match the `plugin_id` field inside).

---

## 2. Top-level fields

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | string | **Yes** | Descriptor format version. Current: `"1.0"`. |
| `plugin_id` | string | **Yes** | Unique snake_case identifier, e.g. `"iqtree3"`. Must match the filename. |
| `name` | string | **Yes** | Human-readable display name shown in the Plugins panel. |
| `executable` | string | **Yes** | Primary command name or path. See §2.1 for how it is resolved. |
| `alt_executables` | array of strings | No | Fallback commands/paths, tried in order if `executable` cannot be resolved. |
| `description` | string | No | One-sentence description shown below the panel title. |
| `homepage` | string | No | URL to the tool's documentation or home page. |
| `citation` | string | No | Suggested citation string (plain text). Shown in the run summary. |
| `license` | string | No | License under which the tool is distributed, e.g. `"GPL-3.0"`, `"MIT"`. Use an SPDX identifier where possible. |
| `min_version` | string | No | Minimum supported tool version (informational only; CARL does not enforce it). |
| `sections` | array of Section | **Yes** | Ordered list of UI sections. See §3. |
| `output` | Output object | No | Describes files the tool produces. See §5. |

### 2.1 Executable resolution

CARL resolves the command by trying `executable`, then each entry of
`alt_executables`, in order. For each candidate:

- A `~` prefix is expanded to the user's home directory.
- If the candidate **looks like a path** (absolute, or containing a path
  separator), it is accepted only when it points to an existing file with the
  execute permission.
- Otherwise it is treated as a **bare command name** and looked up on the
  system `PATH`.

The first candidate that resolves is used. If none resolve, the raw
`executable` string is used as-is, so the operating system surfaces a clear
"not found" error. Because fallbacks are declared here, a descriptor should
list every reasonable alternative name (e.g. `["iqtree3", "iqtree2", "iqtree",
"iqtree3.exe", "iqtree2.exe", "iqtree.exe"]`) rather than relying on any
hard-coded knowledge inside CARL.

**Python-script tools.** If the resolved executable ends in `.py`, CARL runs
it through the Python interpreter that is running CARL
(`<python> <script> …`). The script path is resolved relative to the
descriptor's directory first, then CARL's own directory, then the current
working directory. This lets a small Python wrapper act as a plugin without
being frozen or placed on `PATH`.

---

## 3. Section object

Sections map to collapsible groups / sub-panels in the plugin UI.

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | **Yes** | Unique identifier within this descriptor, e.g. `"general"`. |
| `name` | string | **Yes** | Display name for the section heading, e.g. `"General Options"`. |
| `fields` | array of Field | **Yes** | Ordered list of UI fields. See §4. |

A synthetic **Common Options** section is assembled at runtime from all fields
marked `"common": true` across every section.

---

## 4. Field object

Each field corresponds to one CLI flag or one positional argument.

### 4.1 Required attributes

| Attribute | Type | Description |
|---|---|---|
| `flag` | string | The CLI flag as written on the command line, e.g. `"-s"`, `"--prefix"`. Set to `""` (empty string) to define a **positional argument** — the value is emitted with no preceding flag token; use `positional_order` (§4.3) to order it. |
| `label` | string | Short human-readable label for the UI widget. |
| `type` | string | Widget type. See §4.2. |

### 4.2 Field types

| Type | Widget | Value emitted |
|---|---|---|
| `boolean` | Checkbox | Flag token alone when checked; omitted when unchecked. |
| `string` | Text entry | `flag` + value |
| `integer` | Integer spinner | `flag` + value |
| `float` | Float entry | `flag` + value |
| `choice` | Drop-down (Combobox) | `flag` + selected option |
| `file` | File-picker + path entry | `flag` + path |
| `directory` | Folder-picker + path entry | `flag` + path |

The flag/value join is controlled by `separator` (§4.3).

### 4.3 Optional attributes

| Attribute | Type | Default | Description |
|---|---|---|---|
| `required` | boolean | `false` | If `true`, CARL blocks Run and highlights the field when it is empty (descriptor-assembled commands only; see §6). |
| `common` | boolean | `false` | If `true`, this field also appears in the synthetic Common Options section. |
| `default` | string / number / boolean | `null` | **Pre-fills** the widget. It is *not* used to suppress emission — see the note in §6. |
| `value_hint` | string | — | Placeholder text shown in an empty text/number entry. |
| `help` | string | — | Tooltip and help-pane text. |
| `options` | array of strings | — | Required for `choice`; lists the selectable values. |
| `mutex_group` | string | — | Fields sharing the same group string are mutually exclusive; selecting one clears the others, and only one is emitted. |
| `condition` | Condition object | — | Hide/disable this field unless the condition is met. See §4.4. |
| `positional_order` | integer | `0` | When `flag` is `""`, the emit order among positional fields (1, 2, 3 …). Positional fields are always emitted after all flagged fields. Leave `0` for normal flags. |
| `separator` | string | `" "` | Separator between flag and value: `" "` (default → two tokens, `flag value`), `"="` (→ `flag=value`), or `""` (→ `flagvalue`, e.g. `-T4`). Ignored for `boolean` and positional fields. |

### 4.4 Condition object

Controls whether a field is visible/enabled and whether it is emitted.

| Key | Type | Description |
|---|---|---|
| `field` | string | The `flag` string of the controlling field. |
| `present` | boolean | Show this field only when the controlling field is checked/non-empty (`true`) or empty/unchecked (`false`). |
| `equals` | string | Show this field only when the controlling field's value equals this string. |

Provide **at most one** of `present` / `equals`. If both are supplied, `equals`
is evaluated (it takes precedence). When neither key is present but a
`condition` object is given, the field shows whenever the controlling field is
non-empty.

**Example** — show `-bnni` only when `-bb` is filled:

```json
{
  "flag": "-bnni",
  "label": "Optimise UFBoot trees",
  "type": "boolean",
  "condition": { "field": "-bb", "present": true }
}
```

---

## 5. Output object

Tells CARL what the tool produces so the launcher can display it. The Run tab
always shows **both** a live stdout/stderr terminal pane and a **Results** pane;
the fields below configure what each contains.

| Field | Type | Required | Description |
|---|---|---|---|
| `display_mode` | string | No | Advisory hint — `"file"`, `"terminal"`, or `"both"`. Recorded on the descriptor; the current launcher shows both panes regardless, so this does not switch views. |
| `stdout_file` | string | No | If set, CARL tees the process's streamed stdout into this file (used as a **literal path** — pattern tokens are not substituted). Needed for tools that write their primary result to stdout (e.g. FastTree, MAFFT). |
| `files` | array of OutputFile | No | Files the tool may produce. Drives the Results pane. |
| `primary_file` | string | No | Reserved; accepted but not currently consumed by the launcher (the Results pane is populated from `files`). |

### 5.1 OutputFile object

| Field | Type | Required | Description |
|---|---|---|---|
| `pattern` | string | **Yes** | File-name pattern with `{…}` tokens (see below). The file is listed in the Results pane only if it exists on disk after the run. |
| `output_type` | string | No | How the file is rendered when selected, and its list icon. One of `text`, `table`, `trace` (plain-text viewer), `tree` (tree viewer), `image` (image viewer). Unknown values fall back to `text`. Default `text`. |
| `description` | string | No | One-line description shown in the Results list. |

**Pattern substitution.** A `{name}` token is replaced by the value of the
field whose `flag` is `name`, `-name`, or `--name` (the leading dashes are
optional in the token). Unresolved tokens are left unchanged.

| Token | Resolves to |
|---|---|
| `{pre}` | Value of the field with flag `-pre` |
| `{prefix}` | Value of the field with flag `--prefix` (or `-prefix`) |
| `{s}` | Value of the field with flag `-s` (e.g. the alignment filename) |

**Example OutputFile:**

```json
{ "pattern": "{pre}.treefile", "output_type": "tree",
  "description": "Maximum-likelihood tree" }
```

---

## 6. Command assembly rules

CARL assembles the command as a **list of tokens** (never a shell string):

1. **Resolve the executable** (§2.1) and form the launch prefix: for a `.py`
   executable, `[<python>, <resolved script>]`; otherwise `[<executable>]`.
2. Walk `sections` in order, then `fields` in order. A field is **active** only
   if its `condition` (if any) passes. Skip inactive fields, and skip a field
   whose `mutex_group` has already emitted a member.
3. For each active field, collect flagged and positional tokens:
   - **boolean**: if checked, emit the `flag` token alone.
   - **positional** (`flag == ""`): if the value is non-empty, remember it with
     its `positional_order`.
   - **all other flagged fields**: if the value is non-empty (not `""`, `null`,
     or `false`), emit the flag and value joined by `separator` — `" "` yields
     two tokens `flag value`; `"="` yields `flag=value`; `""` yields
     `flagvalue`.
   - **`default` note:** `default` only pre-fills the widget. A value equal to
     the default is still emitted; CARL does not compare against `default` to
     suppress a token.
4. Append the positional tokens, sorted by `positional_order` ascending, each
   as its bare value.
5. If any `required` field is empty, Run is blocked and the missing fields are
   listed (descriptor-assembled commands only — see below).
6. The token list is passed directly to the OS process API as a list. On
   Windows a no-console flag is set so tools don't spawn a stray terminal
   window. If `output.stdout_file` is set, CARL opens that file and tees the
   process's streamed stdout into it while also displaying it.

**Manual editing.** The assembled command is shown in an editable preview. If
the user edits it, CARL runs the edited text instead, tokenising it with
shell-style quoting rules; descriptor-based assembly and the required-field
check are bypassed for a manually edited command.

---

## 7. Schema versioning policy

The `schema_version` field is a `"MAJOR.MINOR"` string.

| Change | Version bump |
|---|---|
| New optional field added | MINOR |
| New required field / field removed / semantics changed | MAJOR |

CARL logs a warning and skips descriptors with an unrecognised MAJOR version.
Descriptors with a higher MINOR version than CARL expects are loaded with
unknown fields ignored.

---

## 8. Example descriptor

TreeAnnotator (BEAST package) — demonstrates `choice`, `integer` with
`mutex_group`, `file`, `float`, `boolean`, and two positional arguments:

```json
{
  "schema_version": "1.0",
  "plugin_id": "treeannotator",
  "name": "TreeAnnotator",
  "executable": "treeannotator",
  "description": "Summarises a BEAST posterior tree sample into a single Maximum Clade Credibility tree with annotated node statistics.",
  "homepage": "https://beast.community/treeannotator",
  "citation": "Rambaut A. and Drummond A.J. TreeAnnotator v1.10, 2002-2017.",
  "license": "LGPL-2.1",
  "sections": [
    {
      "id": "burnin",
      "name": "Burn-in",
      "fields": [
        {
          "flag": "-burnin",
          "label": "Burn-in (states)",
          "type": "integer",
          "common": true,
          "mutex_group": "burnin_method",
          "value_hint": "10000000",
          "help": "Number of MCMC states to discard as burn-in. Mutually exclusive with -burninTrees."
        },
        {
          "flag": "-burninTrees",
          "label": "Burn-in (trees)",
          "type": "integer",
          "mutex_group": "burnin_method",
          "value_hint": "1000",
          "help": "Number of trees to discard as burn-in. Mutually exclusive with -burnin."
        }
      ]
    },
    {
      "id": "summary",
      "name": "Summary Tree",
      "fields": [
        {
          "flag": "-heights",
          "label": "Node heights",
          "type": "choice",
          "common": true,
          "default": "keep",
          "options": ["keep", "median", "mean", "ca"],
          "help": "How to set node heights on the summary tree: keep (from MCC topology), median, mean, or common ancestor (ca)."
        },
        {
          "flag": "-target",
          "label": "Target tree file",
          "type": "file",
          "help": "User-supplied target tree to annotate instead of the MCC tree."
        },
        {
          "flag": "-limit",
          "label": "Posterior probability limit",
          "type": "float",
          "value_hint": "0.5",
          "help": "Minimum posterior probability for a node to be annotated."
        }
      ]
    },
    {
      "id": "options",
      "name": "Options",
      "fields": [
        {
          "flag": "-forceDiscrete",
          "label": "Force discrete traits",
          "type": "boolean",
          "help": "Treat integer-valued traits as discrete rather than continuous when summarising."
        },
        {
          "flag": "-hpd2D",
          "label": "2D HPD proportion(s)",
          "type": "string",
          "value_hint": "0.80,0.95",
          "help": "Comma-separated HPD proportions for 2D spatial trait summaries."
        }
      ]
    },
    {
      "id": "files",
      "name": "Files",
      "fields": [
        {
          "flag": "",
          "label": "Input trees file",
          "type": "file",
          "required": true,
          "common": true,
          "positional_order": 1,
          "value_hint": "posterior.trees",
          "help": "BEAST posterior tree sample (.trees file) to summarise."
        },
        {
          "flag": "",
          "label": "Output file",
          "type": "file",
          "required": true,
          "common": true,
          "positional_order": 2,
          "value_hint": "mcc.tree",
          "help": "Path for the annotated MCC tree output file."
        }
      ]
    }
  ],
  "output": {
    "display_mode": "terminal"
  }
}
```

---

## 9. Reserved for future versions

The following are **not** implemented in v1. They are reserved so that adding
them later is a MINOR (additive) change:

- **`env`** — a block of environment variables to set for the child process
  (e.g. `OMP_NUM_THREADS`).
- **Version detection** — a `version_flag` (e.g. `"--version"`) so CARL could
  read the installed version and compare it against `min_version`.
- **`fixed_args`** — a top-level array of tokens inserted between the resolved
  executable and the user-controlled fields, for tools with fixed pre-flag
  arguments (e.g. `java -jar app.jar`, `mpirun -np N`). *Workaround:* for a
  Python tool, point `executable` at a `.py` script (§2.1); for others, install
  a small shell wrapper named after the tool and set `executable` to it.
- **`multiple` / `multi_separator`** on a field — repeated or comma-joined
  multi-value emission. The descriptor builder exposes `multi_separator`, but
  the v1 command assembler does not yet act on it.
- **`interaction_model`** — a top-level field (`"flags"` / `"script"` /
  `"stdin_menu"`) for tools driven by a command/scripting language (PAUP\*, TNT,
  RevBayes) or an interactive stdin menu (the PHYLIP suite). These tools are
  incompatible with the v1 flag-based model and are out of scope for v1.
