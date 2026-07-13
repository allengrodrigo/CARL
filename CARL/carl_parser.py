"""
CARL block parser for TaxonGPT/CARL.

Two-pass parser: reads BEGIN CARL; ... END; from NEXUS text and produces
a CARLBlock holding TaxonEntity and TaxonRelationship dataclass lists.

Parsing strategy
----------------
Pass 1 — scan every statement header (name is|is_new rank) to build the
         name registry, and scan every [&D left:right] block to build the
         subject data_id registry.  Named block headers (DEFINE TAXA etc.)
         are silently discarded.  Conflicting is/is_new for the same name
         raises ValueError.

Pass 2 — process definition statements (no action keyword) first, then
         action statements (renames / synonymizes / includes / divides).
         Order of statements in the file is irrelevant.

Output
------
CARLBlock.entities         List[TaxonEntity]
CARLBlock.relationships    List[TaxonRelationship]
"""

import re
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
from collections import defaultdict


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NONE_ID = 'none'  # sentinel: user wrote =none (explicit "no data"); distinct from Python None (blank)


def _is_real(did: Optional[str]) -> bool:
    """True only for a real DataID — not blank (None) and not explicit-none (NONE_ID)."""
    return did is not None and did != NONE_ID

RANK_ABBREVS: Dict[str, str] = {
    'genus': 'gen',
    'family': 'fam',
    'subfamily': 'subfam',
    'tribe': 'trib',
    'species': 'sp',
    'subspecies': 'subsp',
    'order': 'ord',
    'suborder': 'subord',
    'class': 'cl',
}

ACTION_KEYWORDS = frozenset({'renames', 'synonymizes', 'includes', 'divides'})

_REL_TYPE = {
    'renames':     'renames_from',
    'synonymizes': 'synonymizes',
    'includes':    'includes',
    'divides':     'divides_to',
}

_NAMED_HEADERS = frozenset({
    'DEFINE TAXA', 'RENAME TAXA', 'UNITE TAXA', 'DIVIDE TAXA',
    'DEFINE_TAXA', 'RENAME_TAXA', 'UNITE_TAXA', 'DIVIDE_TAXA',
})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TaxonEntity:
    entity_id: int           # stable int primary key
    name: str                # nomenclatural name as declared
    status: str              # 'is' | 'is_new'
    rank: str                # any rank string (lower-cased)
    data_id: Optional[str]   # DATA block row label, or None
    action: str              # 'definition'|'renames'|'synonymizes'|'includes'|'divides'
    comment: Optional[str] = None  # text after # inside [&D ...]


@dataclass
class TaxonRelationship:
    subject_id: int          # entity_id of the subject TaxonEntity
    rel_type: str            # 'renames_from'|'synonymizes'|'includes'|'divides_to'
    object_name: str         # name string of the object taxon
    object_data_id: Optional[str]  # object's DATA variable, or None
    object_entity_id: Optional[int] = None  # in-memory only; set by UI picker for W2 disambiguation


# ---------------------------------------------------------------------------
# CARLBlock container
# ---------------------------------------------------------------------------

class CARLBlock:

    def __init__(self,
                 entities: List[TaxonEntity],
                 relationships: List[TaxonRelationship],
                 parse_warnings: Optional[List[str]] = None,
                 parse_errors: Optional[List[str]] = None) -> None:
        self.entities = entities
        self.relationships = relationships
        self.parse_warnings: List[str] = list(parse_warnings or [])
        self.parse_errors: List[str] = list(parse_errors or [])
        self._shared_dataid_warned: bool = False
        self._eid: Dict[int, TaxonEntity] = {e.entity_id: e for e in entities}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _entity(self, eid: int) -> Optional[TaxonEntity]:
        return self._eid.get(eid)

    def _by_name(self, name: str) -> Optional[TaxonEntity]:
        for e in self.entities:
            if e.name == name:
                return e
        return None

    def _rels_for(self, eid: int, rel_type: str) -> List[TaxonRelationship]:
        return [r for r in self.relationships
                if r.subject_id == eid and r.rel_type == rel_type]

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    def effective_data_id(self, entity_id: int) -> Optional[str]:
        """Return the effective dataID for an entity, applying renames inheritance.

        For a renames subject whose own data_id is blank, the effective dataID
        is the object's data_id (which may itself be blank, NONE_ID, or real).
        For all other entities, returns the entity's own data_id unchanged.
        """
        e = self._entity(entity_id)
        if e is None:
            return None
        if e.action == 'renames' and e.data_id is None:
            rels = self._rels_for(entity_id, 'renames_from')
            if rels:
                return rels[0].object_data_id
        return e.data_id

    def get_display_label(self, entity_id: int) -> str:
        e = self._entity(entity_id)
        if e is None:
            return ''

        if e.action == 'definition':
            if e.status == 'is_new':
                abbrev = RANK_ABBREVS.get(e.rank, e.rank)
                return f"{e.name}_{abbrev}_nov"
            return e.name

        if e.action == 'renames':
            rels = self._rels_for(entity_id, 'renames_from')
            old = rels[0].object_name if rels else '?'
            if e.status == 'is_new':
                return f"{e.name} nom. nov. (syn. {old})"
            return f"{e.name} (syn. {old})"

        if e.action == 'synonymizes':
            return f"{e.name}_syn"

        if e.action in ('includes', 'divides'):
            return e.name

        return e.name

    def get_data_tab_rows(self) -> List[dict]:
        """
        Apply display rules per action.  Returns a list of row dicts:
          entity_id, label, data_id, greyed, is_group_header, group_name,
          status ('is'|'is_new'|''), query_name (group headers only),
          object_name (synonymizes members only)

        Display rules summary
        ---------------------
        definition  → normal if dataID, greyed if none
        renames     → subject shown (data inherited if subject=none + object≠none);
                      object NEVER shown as standalone row
        synonymizes → subject as group header + each object as member row
        includes    → subject as group header only; objects appear via own entities
        divides     → subject shown as group header labelled '<name> (Parent)';
                      daughters shown as child rows labelled '<name> (Daughter)'
        """
        rows: List[dict] = []

        # Names that appear only as renames objects (no subject TaxonEntity of their own)
        renames_objects_no_entity: set = set()
        for r in self.relationships:
            if r.rel_type == 'renames_from':
                if self._by_name(r.object_name) is None:
                    renames_objects_no_entity.add(r.object_name)

        for e in self.entities:

            if e.action == 'definition':
                greyed = not _is_real(e.data_id)
                rows.append(_row(e.entity_id,
                                 self.get_display_label(e.entity_id),
                                 e.data_id, greyed, status=e.status))

            elif e.action == 'renames':
                effective_did = self.effective_data_id(e.entity_id)
                greyed = not _is_real(effective_did)
                rows.append(_row(e.entity_id,
                                 self.get_display_label(e.entity_id),
                                 effective_did, greyed, status=e.status))

            elif e.action == 'synonymizes':
                # Group header
                greyed_hdr = not _is_real(e.data_id)
                rows.append({**_row(e.entity_id,
                                    f"{e.name}_syn",
                                    e.data_id, greyed_hdr, status=e.status),
                             'is_group_header': True,
                             'group_name': f"{e.name}_syn",
                             'query_name': e.name})
                # Member rows — look up member entity to get its own status
                for r in self._rels_for(e.entity_id, 'synonymizes'):
                    member_ent = self._by_name(r.object_name)
                    m_status   = member_ent.status if member_ent else ''
                    greyed_m   = not _is_real(r.object_data_id)
                    rows.append({**_row(e.entity_id,
                                        f"{e.name}_syn_{r.object_name}",
                                        r.object_data_id, greyed_m, status=m_status),
                                 'group_name': f"{e.name}_syn",
                                 'object_name': r.object_name})

            elif e.action == 'includes':
                # includes subject: group header; data_id is the group's own coded row (if any)
                rows.append({**_row(e.entity_id, e.name, e.data_id, False, status=e.status),
                             'is_group_header': True,
                             'group_name': e.name,
                             'query_name': e.name})
                # Member rows — each object appears as a child of this header AND
                # also as its own standalone row (from its definition statement).
                for r in self._rels_for(e.entity_id, 'includes'):
                    member_ent = (self._eid.get(r.object_entity_id)
                                  if r.object_entity_id is not None
                                  else self._by_name(r.object_name))
                    if member_ent is not None:
                        m_label  = self.get_display_label(member_ent.entity_id)
                        m_did    = member_ent.data_id
                        m_greyed = m_did is None
                        rows.append({**_row(member_ent.entity_id, m_label, m_did, m_greyed,
                                            status=member_ent.status),
                                     'group_name': e.name,
                                     'note': 'includes_member'})
                    else:
                        m_did    = r.object_data_id
                        m_greyed = m_did is None
                        rows.append({**_row(None, r.object_name, m_did, m_greyed, status=''),
                                     'group_name': e.name,
                                     'note': 'includes_member'})

            elif e.action == 'divides':
                # Parent shown as collapsible group header (fetchable if is)
                p_label = self.get_display_label(e.entity_id) + ' (Parent)'
                rows.append({**_row(e.entity_id, p_label, e.data_id,
                                    not _is_real(e.data_id), status=e.status),
                             'is_group_header': True,
                             'group_name':      f'{e.name}_div',
                             'query_name':      e.name,
                             'note':            'divides_parent'})
                # Daughter member rows (daughters also appear via own entity rows elsewhere)
                for r in self._rels_for(e.entity_id, 'divides_to'):
                    d_ent    = (self._eid.get(r.object_entity_id)
                                if r.object_entity_id is not None
                                else self._by_name(r.object_name))
                    d_did    = r.object_data_id
                    d_greyed = d_did is None
                    if d_ent is not None:
                        d_label = self.get_display_label(d_ent.entity_id) + ' (Daughter)'
                        rows.append({**_row(d_ent.entity_id, d_label, d_did,
                                            d_greyed, status=d_ent.status),
                                     'group_name':  f'{e.name}_div',
                                     'note':        'divides_daughter',
                                     'object_name': r.object_name,
                                     'subject_id':  e.entity_id})
                    else:
                        rows.append({**_row(None, f'{r.object_name} (Daughter)',
                                            d_did, d_greyed, status=''),
                                     'group_name':  f'{e.name}_div',
                                     'note':        'divides_daughter',
                                     'object_name': r.object_name,
                                     'subject_id':  e.entity_id})

        return rows

    def get_groups(self) -> Dict[str, List[str]]:
        """
        Return {group_name: [member_names]} for synonymizes and includes actions.
        Suitable for building the Groups listbox.
        """
        groups: Dict[str, List[str]] = {}
        for e in self.entities:
            if e.action == 'synonymizes':
                members = [r.object_name
                           for r in self._rels_for(e.entity_id, 'synonymizes')]
                groups[f"{e.name}_syn"] = members
            elif e.action == 'includes':
                members = [r.object_name
                           for r in self._rels_for(e.entity_id, 'includes')]
                if members:
                    groups[e.name] = members
        return groups

    def get_retrieval_targets(self, entity_id: int) -> List[str]:
        """
        Names to query externally: current name + historical names via renames_from.
        """
        e = self._entity(entity_id)
        if e is None:
            return []
        targets = [e.name]
        for r in self._rels_for(entity_id, 'renames_from'):
            targets.append(r.object_name)
        return targets

    def check_shared_data_ids(self) -> List[Tuple[str, List[str], bool]]:
        """
        Scan all effective data_id assignments and return shared ones.
        Returns list of (data_id, [taxon_names], is_divides_case).
        None data_ids are exempt.
        """
        mapping: Dict[str, List[Tuple[str, bool]]] = defaultdict(list)
        # Entities' own data_ids (real only — blank and NONE_ID cannot be shared)
        for e in self.entities:
            if _is_real(e.data_id):
                mapping[e.data_id].append((e.name, False))
        # renames inheritance: subject blank → effective = object's data_id
        for r in self.relationships:
            if r.rel_type == 'renames_from' and _is_real(r.object_data_id):
                subj = self._entity(r.subject_id)
                if subj and subj.data_id is None:  # only blank subjects inherit
                    mapping[r.object_data_id].append((subj.name, False))
        # divides daughters' data_ids (from relationship, not entity)
        for r in self.relationships:
            if r.rel_type == 'divides_to' and _is_real(r.object_data_id):
                daughter_entity = self._by_name(r.object_name)
                if daughter_entity is None or daughter_entity.data_id != r.object_data_id:
                    mapping[r.object_data_id].append((r.object_name, True))

        result = []
        for did, entries in mapping.items():
            if len(entries) > 1:
                names = [n for n, _ in entries]
                is_divides = any(d for _, d in entries)
                result.append((did, names, is_divides))
        return result

    def check_dataid_conflicts(self) -> List[Tuple[str, str, str]]:
        """
        Detect taxa that point to two different DataIDs.  Two cases:

        Case A — object/entity mismatch: a relationship's object_data_id
        conflicts with the same taxon's own entity data_id.

        Case B — renames double-assignment: a renames_from relationship has
        BOTH subject.data_id and object_data_id non-None.  The inheritance
        rule fires when object_data_id is non-None, giving the subject two
        data rows (its own explicit one plus the inherited one).  Valid forms
        are subject=DataID/object=none (explicit claim) or
        subject=none/object=DataID (inheritance); never both non-None.

        Returns list of (taxon_name, data_id_a, data_id_b).
        None data_ids are exempt.
        """
        conflicts = []
        seen: set = set()

        # Case A: object in relationship conflicts with its own entity data_id
        for r in self.relationships:
            if r.object_data_id is None:
                continue
            entity = self._by_name(r.object_name)
            if entity is None:
                continue
            if entity.data_id is not None and entity.data_id != r.object_data_id:
                key = (r.object_name, entity.data_id, r.object_data_id)
                if key not in seen:
                    seen.add(key)
                    conflicts.append(key)

        # Case B: renames subject has explicit data_id AND object also has data_id
        for r in self.relationships:
            if r.rel_type != 'renames_from':
                continue
            if r.object_data_id is None:
                continue
            subj = self._entity(r.subject_id)
            if subj is None or subj.data_id is None:
                continue
            key = (subj.name, subj.data_id, r.object_data_id)
            if key not in seen:
                seen.add(key)
                conflicts.append(key)

        return conflicts

    def format_statement(self, entity_id: int) -> str:
        """Return the full CARL syntax string for a single entity (one-liner)."""
        e = self._entity(entity_id)
        if e is None:
            return ''

        cmt_str = f' #{e.comment}' if e.comment else ''

        def _bracket(left: str, right: str) -> str:
            return f'[&D {left}:{right}{cmt_str}]'

        if e.action == 'definition':
            return (f'{e.name} {e.status} {e.rank} '
                    f'{_bracket(_did_part(e.name, e.data_id), "")}')

        if e.action == 'renames':
            rels = self._rels_for(entity_id, 'renames_from')
            if rels:
                r = rels[0]
                return (f'{e.name} {e.status} {e.rank} renames {r.object_name} '
                        f'{_bracket(_did_part(e.name, e.data_id), _did_part(r.object_name, r.object_data_id))}')
            return f'{e.name} {e.status} {e.rank} renames ?'

        if e.action == 'synonymizes':
            rels = self._rels_for(entity_id, 'synonymizes')
            objs = ', '.join(r.object_name for r in rels)
            right_parts = [_did_part(r.object_name, r.object_data_id) for r in rels]
            right = ', '.join(p for p in right_parts if p)
            return (f'{e.name} {e.status} {e.rank} synonymizes {objs} '
                    f'{_bracket(_did_part(e.name, e.data_id), right)}')

        if e.action == 'includes':
            rels = self._rels_for(entity_id, 'includes')
            objs = ', '.join(r.object_name for r in rels)
            right_parts = [_did_part(r.object_name, r.object_data_id) for r in rels]
            right = ', '.join(p for p in right_parts if p)
            return (f'{e.name} {e.status} {e.rank} includes {objs} '
                    f'{_bracket(_did_part(e.name, e.data_id), right)}')

        if e.action == 'divides':
            rels = self._rels_for(entity_id, 'divides_to')
            objs = ', '.join(r.object_name for r in rels)
            right_parts = [_did_part(r.object_name, r.object_data_id) for r in rels]
            right = ', '.join(p for p in right_parts if p)
            return (f'{e.name} {e.status} {e.rank} divides {objs} '
                    f'{_bracket(_did_part(e.name, e.data_id), right)}')

        return f'{e.name} {e.status} {e.rank}'

    def serialize(self) -> str:
        """Serialise CARLBlock back to BEGIN CARL; ... END; text."""
        lines = ['BEGIN CARL;', '']

        def cmt(e: TaxonEntity) -> str:
            return f' #{e.comment}' if e.comment else ''

        def _bracket(left: str, right: str, e: TaxonEntity) -> str:
            return f'[&D {left}:{right}{cmt(e)}]'

        for e in self.entities:
            if e.action == 'definition':
                dp = _bracket(_did_part(e.name, e.data_id), '', e)
                lines.append(f'{e.name} {e.status} {e.rank} {dp}')

            elif e.action == 'renames':
                rels = self._rels_for(e.entity_id, 'renames_from')
                if rels:
                    r = rels[0]
                    dp = _bracket(_did_part(e.name, e.data_id),
                                  _did_part(r.object_name, r.object_data_id), e)
                    lines.append(f'{e.name} {e.status} {e.rank} renames '
                                 f'{r.object_name} {dp}')

            elif e.action == 'synonymizes':
                rels = self._rels_for(e.entity_id, 'synonymizes')
                objs = ', '.join(r.object_name for r in rels)
                right_parts = [_did_part(r.object_name, r.object_data_id) for r in rels]
                right = ', '.join(p for p in right_parts if p)
                dp = _bracket(_did_part(e.name, e.data_id), right, e)
                lines.append(f'{e.name} {e.status} {e.rank} synonymizes {objs} {dp}')

            elif e.action == 'includes':
                rels = self._rels_for(e.entity_id, 'includes')
                objs = ', '.join(r.object_name for r in rels)
                right_parts = [_did_part(r.object_name, r.object_data_id) for r in rels]
                right = ', '.join(p for p in right_parts if p)
                dp = _bracket(_did_part(e.name, e.data_id), right, e)
                lines.append(f'{e.name} {e.status} {e.rank} includes {objs} {dp}')

            elif e.action == 'divides':
                rels = self._rels_for(e.entity_id, 'divides_to')
                objs = ', '.join(r.object_name for r in rels)
                right_parts = [_did_part(r.object_name, r.object_data_id) for r in rels]
                right = ', '.join(p for p in right_parts if p)
                dp = _bracket(_did_part(e.name, e.data_id), right, e)
                lines.append(f'{e.name} {e.status} {e.rank} divides {objs} {dp}')

        lines.extend(['', 'END;'])
        return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Row helper
# ---------------------------------------------------------------------------

def _row(entity_id, label: str, data_id: Optional[str],
         greyed: bool, note: str = '', status: str = '') -> dict:
    return {
        'entity_id':       entity_id,
        'label':           label,
        'data_id':         data_id,
        'greyed':          greyed,
        'is_group_header': False,
        'group_name':      None,
        'note':            note,
        'status':          status,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def parse_carl_block(nexus_text: str) -> Optional[CARLBlock]:
    """
    Extract and parse a BEGIN CARL; ... END; block from NEXUS file text.
    Returns CARLBlock, or None if no CARL block is present.
    Raises ValueError on parse errors (conflicting status, malformed syntax).
    """
    m = re.search(r'BEGIN\s+CARL\s*;(.*?)END\s*;',
                  nexus_text, re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    return _parse_content(m.group(1))


def has_data_block(nexus_text: str) -> bool:
    """True if the NEXUS text contains a BEGIN DATA; block."""
    return bool(re.search(r'BEGIN\s+DATA\s*;', nexus_text,
                          re.IGNORECASE))


# ---------------------------------------------------------------------------
# Internal parser
# ---------------------------------------------------------------------------

def _parse_content(block_text: str) -> CARLBlock:
    raw_stmts = _tokenize(block_text)
    if not raw_stmts:
        return CARLBlock([], [])

    registry = _pass1(raw_stmts)
    entities, relationships, parse_warnings, parse_errors = _pass2(raw_stmts, registry)
    return CARLBlock(entities, relationships,
                     parse_warnings=parse_warnings,
                     parse_errors=parse_errors)


# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

def _tokenize(block_text: str) -> List[Tuple[str, str]]:
    """
    Return list of (clean_text, dp_content) tuples — one per statement.

    Strategy: strip all NEXUS [...]  comments from the entire block text
    BEFORE splitting into lines.  Iterative stripping handles nested brackets
    (e.g. [&D ...] appearing inside a multi-line outer comment).  [&D ...]
    blocks are extracted as numbered placeholders so their content survives.
    """
    dp_store: Dict[str, str] = {}
    counter = [0]

    def _replace(m: re.Match) -> str:
        inner = m.group(1).strip()
        if re.match(r'^&D\b', inner, re.IGNORECASE):
            key = f'__DP{counter[0]}__'
            counter[0] += 1
            dp_store[key] = inner
            return key
        return ' '   # non-data comment → whitespace

    # Iterative bracket stripping: handles nested [[ ]] by peeling inside-out
    text = block_text
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r'\[([^\[\]]*)\]', _replace, text, flags=re.DOTALL)

    stmts = []
    for raw_line in text.splitlines():
        line = raw_line.strip().rstrip(',').strip()
        if not line:
            continue

        # Skip lines that start with an unmatched '[' (malformed/remnant comments)
        if line.startswith('['):
            continue

        # Extract DP placeholder (first one per line; CARL statements have one [&D])
        dp_keys = re.findall(r'__DP\d+__', line)
        dp_content = dp_store.get(dp_keys[0], '') if dp_keys else ''
        clean = re.sub(r'__DP\d+__', '', line).strip()

        if not clean:
            continue

        upper = clean.upper()
        if upper in _NAMED_HEADERS:
            continue

        # Keep only lines that carry a status keyword
        if not re.search(r'\bis_new\b|\bis\b', clean, re.IGNORECASE):
            continue

        # Must begin with a word character (taxon name)
        if not re.match(r'^\w', clean):
            continue

        stmts.append((clean, dp_content))

    return stmts


# ---------------------------------------------------------------------------
# Pass 1 — build registries
# ---------------------------------------------------------------------------

def _pass1(stmts: List[Tuple[str, str]]) -> dict:
    """
    Returns:
      registry — {name: {'status': ..., 'rank': ...}}
    """
    registry: Dict[str, dict] = {}

    for clean, dp in stmts:
        m = re.match(r'^(\S+)\s+(is_new|is)\s+(\S+)', clean, re.IGNORECASE)
        if not m:
            continue
        name = m.group(1)
        status = m.group(2).lower()
        rank = m.group(3).lower()

        if name in registry:
            if registry[name]['status'] != status:
                raise ValueError(
                    f"CARL parse error: '{name}' declared as both "
                    f"'is' and 'is_new'."
                )
            if registry[name]['rank'] != rank:
                raise ValueError(
                    f"CARL parse error: '{name}' declared at two different "
                    f"ranks ('{registry[name]['rank']}' and '{rank}')."
                )
        else:
            registry[name] = {'status': status, 'rank': rank}

    return registry


# ---------------------------------------------------------------------------
# Pass 2 — create entities and relationships
# ---------------------------------------------------------------------------

def _pass2(stmts: List[Tuple[str, str]],
           registry: dict) -> Tuple[List[TaxonEntity], List[TaxonRelationship], List[str], List[str]]:

    entities: List[TaxonEntity] = []
    relationships: List[TaxonRelationship] = []
    entity_map: Dict[str, List[int]] = {}   # name → list of entity_ids (multiple entities per name allowed)
    eid_obj: Dict[int, TaxonEntity] = {}
    next_id = [1]
    warnings: List[str] = []
    errors: List[str] = []

    def new_entity(name: str, action: str,
                   data_id: Optional[str] = None, comment=None) -> int:
        eid = next_id[0]
        next_id[0] += 1
        reg = registry.get(name, {'status': 'is', 'rank': ''})
        e = TaxonEntity(
            entity_id=eid,
            name=name,
            status=reg['status'],
            rank=reg['rank'],
            data_id=data_id,
            action=action,
            comment=comment,
        )
        entities.append(e)
        entity_map.setdefault(name, []).append(eid)
        eid_obj[eid] = e
        return eid

    def _find_entity(name: str, action: str) -> Optional[int]:
        return next((eid for eid in entity_map.get(name, [])
                     if eid_obj[eid].action == action), None)

    def _merge_data_id(e: TaxonEntity, did: Optional[str], label: str) -> None:
        """Blank + explicit → use explicit. Two differing explicits → E5."""
        if did is None:
            return
        if e.data_id is None:
            e.data_id = did
        elif e.data_id != did:
            errors.append(
                f"E5: '{label}' has conflicting dataIDs "
                f"'{e.data_id}' and '{did}'."
            )

    # Separate into definition vs action statements
    def_stmts = []
    act_stmts = []

    for clean, dp in stmts:
        m = re.match(r'^(\S+)\s+(is_new|is)\s+(\S+)(.*)',
                     clean, re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        name = m.group(1)
        rest = m.group(4).strip()

        a = re.match(r'^(renames|synonymizes|includes|divides)\s*(.*)',
                     rest, re.IGNORECASE | re.DOTALL)
        if a:
            act_stmts.append((name, a.group(1).lower(),
                               a.group(2).strip(), dp))
        else:
            def_stmts.append((name, dp))

    # --- 2a: definitions ---
    for name, dp in def_stmts:
        left, _, comment = _parse_dp(dp)
        did = left.get(name)   # explicit left side only; blank if not present

        existing = _find_entity(name, 'definition')
        if existing is not None:
            e = eid_obj[existing]
            _merge_data_id(e, did, name)
            if e.comment is None and comment is not None:
                e.comment = comment
        else:
            new_entity(name, 'definition', did, comment=comment)

    # --- 2b: action statements ---
    for name, action_kw, objects_str, dp in act_stmts:
        left, right, comment = _parse_dp(dp)
        subject_did = left.get(name)   # explicit left side only; blank if not present

        obj_names = [o.strip() for o in objects_str.split(',') if o.strip()]

        # E8: malformed action
        if not obj_names:
            errors.append(f"E8: '{name} {action_kw}' has no objects.")
            continue
        if action_kw == 'renames' and len(obj_names) != 1:
            errors.append(
                f"E8: '{name} renames' requires exactly one object "
                f"(found {len(obj_names)}: {', '.join(obj_names)})."
            )
            continue

        # E6: self-renaming
        if action_kw == 'renames' and obj_names[0] == name:
            errors.append(f"E6: '{name}' renames itself.")
            continue

        rel_type = _REL_TYPE[action_kw]
        existing = _find_entity(name, action_kw)

        if existing is not None:
            e = eid_obj[existing]
            # E3: object list must match
            existing_objs = [r.object_name for r in relationships
                             if r.subject_id == existing and r.rel_type == rel_type]
            if set(existing_objs) != set(obj_names):
                errors.append(
                    f"E3: '{name} {action_kw}' declared with conflicting object "
                    f"lists: {existing_objs} vs {obj_names}."
                )
                continue
            # E5-A: subject DataID
            _merge_data_id(e, subject_did, name)
            # E5-C: in-statement object DataIDs must agree with stored relationships
            for r in relationships:
                if r.subject_id == existing and r.rel_type == rel_type:
                    new_obj_did = right.get(r.object_name)
                    if new_obj_did is not None:
                        if r.object_data_id is None:
                            r.object_data_id = new_obj_did
                        elif r.object_data_id != new_obj_did:
                            errors.append(
                                f"E5: object '{r.object_name}' in "
                                f"'{name} {action_kw}' has conflicting "
                                f"in-statement dataIDs "
                                f"'{r.object_data_id}' and '{new_obj_did}'."
                            )
            if e.comment is None and comment is not None:
                e.comment = comment
        else:
            subject_id = new_entity(name, action_kw, subject_did, comment=comment)
            for obj_name in obj_names:
                obj_did = right.get(obj_name)   # explicit right side only; blank if not present
                relationships.append(TaxonRelationship(
                    subject_id=subject_id,
                    rel_type=rel_type,
                    object_name=obj_name,
                    object_data_id=obj_did,
                ))

    # --- Post-parse checks ---

    # E5-B: in-statement object DataID must match object's own persistent DataID
    for r in relationships:
        if r.object_data_id is not None:
            obj_entity = next((e for e in entities if e.name == r.object_name), None)
            if (obj_entity is not None
                    and obj_entity.data_id is not None
                    and r.object_data_id != obj_entity.data_id):
                errors.append(
                    f"E5: in-statement dataID '{r.object_data_id}' for "
                    f"'{r.object_name}' conflicts with its declared dataID "
                    f"'{obj_entity.data_id}'."
                )

    # W2: name shared by more than one distinct taxon
    for nm, eids in entity_map.items():
        if len(eids) > 1:
            actions = [eid_obj[eid].action for eid in eids]
            warnings.append(
                f"W2: '{nm}' is declared as more than one taxon "
                f"({', '.join(actions)})."
            )

    return entities, relationships, warnings, errors


# ---------------------------------------------------------------------------
# [&D ...] pointer parser
# ---------------------------------------------------------------------------

def _parse_dp(dp_content: str) -> Tuple[Dict[str, Optional[str]],
                                         Dict[str, Optional[str]],
                                         Optional[str]]:
    """
    Parse content of a [&D ...] block.
    Returns (left_dict, right_dict, comment) where comment is the text after
    the first # (stripped), or None if absent.
    """
    # Strip '&D' prefix
    content = re.sub(r'^&D\s*', '', dp_content, flags=re.IGNORECASE).strip()
    # Extract inline comment before removing it
    comment_match = re.search(r'#(.*)$', content)
    comment = comment_match.group(1).strip() or None if comment_match else None
    content = re.sub(r'#.*$', '', content).strip()

    if ':' in content:
        left_str, right_str = content.split(':', 1)
    else:
        left_str, right_str = content, ''

    return _parse_side(left_str), _parse_side(right_str), comment


def _did_part(name: str, did: Optional[str]) -> str:
    """Serialise one name=dataID slot. Blank (None) → empty string (name omitted)."""
    if did is None:
        return ''
    return f'{name}={did}'  # NONE_ID serialises as 'name=none'; real as 'name=T1'


def _parse_side(s: str) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {}
    s = s.strip()
    if not s:
        return result
    for part in s.split(','):
        part = part.strip()
        if '=' in part:
            name, did = part.split('=', 1)
            name = name.strip()
            did = did.strip()
            if not did:
                result[name] = None          # name= with empty value → blank
            elif did.lower() == 'none':
                result[name] = NONE_ID       # name=none → explicit None
            else:
                result[name] = did           # name=T1  → real DataID
        elif part:
            result[part] = None              # bare name with no = → blank
    return result


# ---------------------------------------------------------------------------
# Convenience: detect file state for ui_app loading
# ---------------------------------------------------------------------------

def detect_file_state(nexus_text: str) -> str:
    """
    Returns 'normal', 'build', or 'invalid'.
    normal  — CARL block present (DATA may or may not exist)
    build   — no CARL, DATA present
    invalid — neither
    """
    has_carl = bool(re.search(r'BEGIN\s+CARL\s*;', nexus_text, re.IGNORECASE))
    has_data = has_data_block(nexus_text)
    if has_carl:
        return 'normal'
    if has_data:
        return 'build'
    return 'invalid'


# ---------------------------------------------------------------------------
# ASSUMPTIONS block parsers (WTSET and precludes)
# ---------------------------------------------------------------------------

_KEY_LINE   = re.compile(r'(\d+)\((\d+)\)\s+precludes\s+([\d,\s\-]+)', re.IGNORECASE)
_WTSET_LINE = re.compile(r'WTSET\s+(\w+)\s*=\s*([^;]+)', re.IGNORECASE)


def _expand_char_tokens(token_str: str) -> list:
    """Expand a comma-separated char list (1-based, ranges like '3-7' allowed) to 0-based indices."""
    result = []
    for tok in token_str.split(','):
        tok = tok.strip()
        if not tok:
            continue
        if '-' in tok:
            a, b = tok.split('-', 1)
            result.extend(range(int(a) - 1, int(b)))
        else:
            result.append(int(tok) - 1)
    return result


def _parse_wtset_rhs(rhs: str) -> list:
    """Parse 'weight:charlist, weight:charlist' groups from a WTSET right-hand side.

    charlist uses spaces as separators; commas separate weight groups.
    Returns [(weight_float, [0-based_indices]), ...].
    """
    groups = []
    for group in rhs.split(','):
        group = group.strip()
        if ':' not in group:
            continue
        weight_str, charlist_str = group.split(':', 1)
        try:
            weight = float(weight_str.strip())
        except ValueError:
            continue
        charlist_str = re.sub(r'\s*-\s*', '-', charlist_str)
        chars = []
        for tok in charlist_str.split():
            tok = tok.strip()
            if not tok:
                continue
            if '-' in tok:
                a, b = tok.split('-', 1)
                chars.extend(range(int(a) - 1, int(b)))
            else:
                chars.append(int(tok) - 1)
        groups.append((weight, chars))
    return groups


def parse_wtsets(nexus_text: str) -> tuple:
    """Parse WTSET statements from BEGIN ASSUMPTIONS; ... END;

    Only the labels 'descriptions', 'compare', and 'key' are recognised;
    all other WTSET statements (used by other software) are ignored.

    For 'descriptions' and 'compare', only weight 0 is meaningful — those
    characters are excluded from the relevant analysis.

    Returns:
        (descriptions_excluded, compare_excluded, key_weights)

        descriptions_excluded — set of 0-based char indices with weight 0
        compare_excluded      — set of 0-based char indices with weight 0
        key_weights           — {char_0based: float}; unlisted chars default
                                to 1.0 at use-site; 0.0 = hard exclusion
    """
    assump_m = re.search(r'BEGIN\s+ASSUMPTIONS\s*;(.*?)END\s*;', nexus_text,
                         re.IGNORECASE | re.DOTALL)
    if not assump_m:
        return set(), set(), {}

    desc_excl   = set()
    comp_excl   = set()
    key_weights = {}

    for m in _WTSET_LINE.finditer(assump_m.group(1)):
        label = m.group(1).lower()
        if label not in ('descriptions', 'compare', 'key'):
            continue
        for weight, chars in _parse_wtset_rhs(m.group(2)):
            if label == 'descriptions':
                if weight == 0.0:
                    desc_excl.update(chars)
            elif label == 'compare':
                if weight == 0.0:
                    comp_excl.update(chars)
            else:  # key
                for c0 in chars:
                    if c0 in key_weights:
                        print(f"  WARNING: WTSET key duplicate for C{c0 + 1} "
                              f"(existing W={key_weights[c0]}, new W={weight}) — "
                              f"last-write wins")
                    key_weights[c0] = weight

    return desc_excl, comp_excl, key_weights


def parse_precludes(nexus_text: str, dataset) -> dict:
    """Parse precludes statements from the CARL block body.

    Format: CharNum(StateNum) precludes CharNum, CharNum, ...
    Numbers are 1-based; converted to 0-based internally.
    StateNum is resolved to a state label via dataset.

    Returns {(cond_char_0based, state_label): [precluded_char_0based, ...]}
    Empty dict if no CARL block or no precludes statements present.
    """
    carl_m = re.search(r'BEGIN\s+CARL\s*;(.*?)END\s*;', nexus_text,
                       re.IGNORECASE | re.DOTALL)
    if not carl_m:
        return {}

    char_states = {c.index: c.states for c in dataset.characters}
    preclusion  = {}

    for line in carl_m.group(1).splitlines():
        line = line.strip()
        if not line:
            continue
        m = _KEY_LINE.match(line)
        if m:
            cond_char_0  = int(m.group(1)) - 1
            cond_state_i = int(m.group(2))
            precluded_0  = _expand_char_tokens(m.group(3))
            state_label  = (char_states.get(cond_char_0, {})
                            .get(cond_state_i, str(cond_state_i)))
            preclusion[(cond_char_0, state_label)] = precluded_0

    return preclusion


def serialize_carl_block(carl_block, existing_content: str = "") -> str:
    """Serialise the CARL block, preserving verbatim any preclusion lines
    ('N(S) precludes ...') from the existing file's CARL block.

    Preclusion statements are used for key building but are NOT part of the
    CARLBlock model, so a plain ``serialize()`` would drop them on save. Here
    they are extracted from the existing CARL block and re-inserted before END;.
    """
    text = carl_block.serialize()
    if not existing_content:
        return text
    m = re.search(r'BEGIN\s+CARL\s*;(.*?)END\s*;', existing_content,
                  re.IGNORECASE | re.DOTALL)
    if not m:
        return text
    precludes = [l.rstrip() for l in m.group(1).splitlines()
                 if _KEY_LINE.match(l.strip())]
    if not precludes:
        return text
    block = "\n".join(precludes)
    idx = text.rstrip().rfind("END;")
    if idx < 0:
        return text.rstrip() + "\n" + block + "\n"
    return text[:idx].rstrip() + "\n\n" + block + "\nEND;\n"
