# description_verbs

Replace the `character ↔ state` delimiter in programmatically generated
taxonomic text with the verb **is**/**are**, choosing it from the grammatical
number of the *head noun* of the character name — using programmatic NLP only
(**no LLMs**), and correctly handling scientific Latin/Greek singular vs plural
nouns.

Two input formats are supported (`--mode`):

**Description** (`:` delimiter):
```
Anterior lateral spinnerets: present.   ->   Anterior lateral spinnerets are present.
Chelicerae rastellum: absent.           ->   Chelicerae rastellum is absent.
```

**Identification key** (`=` delimiter):
```
2a. If anterior lateral spinnerets = present, then go to 3.
        ->  2a. If anterior lateral spinnerets are present, then go to 3.
9a. If maxillae anterior lobe = unmodified, then the taxon is Ischnothele.
        ->  9a. If maxillae anterior lobe is unmodified, then the taxon is Ischnothele.
```

Both formats share the same head-noun/number engine; only the delimiter and the
surrounding boilerplate (which passes through untouched) differ.

## How it decides

1. **Segment** (`segmenter.py`) — split the text into `Name: state` sentences,
   leaving headings, separators, `DESCRIPTION FOR …` banners, blank lines and the
   trailing `(Not applicable: …)` note untouched.
2. **Head noun** (`head_noun.py`) — spaCy tokenises/POS-tags the name (the first
   call), then a deterministic structural rule selects the head:
   *trailing word after the last numeral* (`… of leg III **chaetotaxy**`) →
   *last word before the first preposition* (`**Type** of burrow entrance`) →
   *rightmost word* (`Anterior lateral **spinnerets**`). spaCy's raw dependency
   root is kept only as a logged cross-check, because on these telegraphic,
   Latin-heavy fragments it mis-handles coordinated NPs, trailing heads and
   hyphen artifacts.
3. **Number** (`latin_number.py` → `number.py`) — first confident answer wins:
   curated Latin/Greek **lexicon** → conservative Latin **suffix rules**
   (`-ae/-i` plural, `-um/-us/-is/-ix/-ex` singular; the ambiguous `-a/-ia/-ina`
   are lexicon-only) → English via **`inflect`** → default singular. The Latin
   stage runs first because `inflect` mis-handles scientific vocabulary in both
   directions (*tarsi/setae* → “singular”, *tarsus/genus* → “plural”).

## Usage

```
python -m description_verbs INPUT.txt                    # auto-detect; writes INPUT_rec.txt
python -m description_verbs INPUT.txt -m description     # force ':' description mode
python -m description_verbs INPUT.txt -m key            # force '=' key mode
python -m description_verbs INPUT.txt -o OUT.txt
python -m description_verbs INPUT.txt --report decisions.tsv
```

`-m/--mode` is `description`, `key`, or `auto` (default). Auto-detection counts
key-couplet lines vs `Name: state` lines and picks the majority; pass the flag
explicitly if a file is ambiguous. The original line-ending style (LF or CRLF)
is preserved.

`--report` writes a tab-separated audit (one row per distinct character name:
head noun, number, verb, method, spaCy root, agreement). Nothing blocks on it —
it lets you spot-check coverage on a new taxonomic group and, if a head noun is
resolved wrongly by `inflect`/`default`, add it to `lexicon.json`.

### As a library (for CARL / a plugin)

```python
from description_verbs import transform_text, transform_file

new_text, records = transform_text(open("desc.txt").read())
transform_file("desc.txt")                 # -> desc_rec.txt
```

## Dependencies (open-source, offline)

- `spacy` (MIT) + `en_core_web_sm` (~12 MB, MIT) — `python -m spacy download en_core_web_sm`
- `inflect` (MIT) — pure Python

Everything runs fully offline once the model is installed, so the package
freezes cleanly (PyInstaller) and drops into the CARL plugin architecture.

## Extending the lexicon

`lexicon.json` has `singular` and `plural` lists of lower-case words. Add the
genuinely ambiguous cases (especially `-a` neuter plurals like *sigilla* and
`-a`/`-ia` feminine singulars like *fovea*, *tibia*, *fascia*) as you encounter
new groups; lexicon entries always override the suffix rules.
```
