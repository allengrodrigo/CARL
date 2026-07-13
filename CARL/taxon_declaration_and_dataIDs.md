# Rules for taxon declaration and dataIDs in CARL blocks

## 1. What is a taxon?

In CARL, taxa are nomenclatural entities. Each taxon is defined by a name and its nomenclatural actions: a mandatory establishment action and, optionally, one further action.

Every taxon MUST have a name and an **establishment action** — the mandatory nomenclatural action, which sets its status (new or existing) and its rank. A taxon that has these features is **declared**. A taxon that does not is **undeclared** and throws an exception (E1).

A **simple taxon** has only these mandatory features. Simple taxa are written in **simple statements**.

A **compound taxon** has a name, an establishment action, a rank, and exactly one further nomenclatural action. The four further actions are **renames**, **synonymizes**, **divides**, and **includes**. In a compound taxon, the taxon is the **subject** that performs the action, and the action is applied to one or more **object** taxa. Every object taxon MUST itself be a declared simple or compound taxon (E2). Compound taxa are written in **compound statements**.

A taxon is identified by its establishment and its actions: a **simple taxon** by its name, status, and rank; a **compound taxon** by its name, status, rank, and further action. The object list of a compound statement is **not** part of this identity. Two declarations that match on identity declare the **same** taxon, and MUST then agree on the rest — the dataID (Section 3), and (for a compound taxon) the object list; a disagreement on the object list throws an exception (E3), and a disagreement on dataID throws E5. A repeat that agrees on everything is harmless. Two declarations that differ on any identity attribute (name, status, rank, or further action) are **different** taxa.

A name may belong to more than one declared taxon. For example, a simple taxon and a compound taxon may share a name. CARL warns when a name gains a second declared taxon (W2), because references to that name may become ambiguous in some contexts. When a name is used to refer to an object, it must resolve to a single taxon. Two same-named taxa are **interchangeable** when substituting one for the other in any reference makes no difference to downstream analyses or information retrieval — they contribute the same character data and share the same status. If it matches two or more declared taxa that differ in the character data they contribute or in status, the reference is ambiguous and throws an exception (E4); if the matching taxa are interchangeable, the reference is fine. Section 5 explains how the user resolves an ambiguous reference.

CARL keeps two kinds of information separate. The **nomenclatural** side holds taxa, as described above. The **data** side holds rows of character data in the NEXUS matrix. A taxon is linked to a data row by a **dataID** (Section 3). Because the two sides are separate, all nomenclatural work — declaring taxa, renaming, synonymizing, dividing, grouping, and retrieving information — can be done with every dataID left blank; dataIDs are needed only for character-based analyses (Section 5).

## 2. Declaring taxa

A **simple statement** has this form:

```
<name> <is | is_new> <rank> [&D <name>=<dataID> : #<comment>]
```

`is` means the taxon is an existing, published name. `is_new` means the taxon is new to science. The `[&D … ]` part is the **data block** (Section 3); it is optional. The data block always contains a colon; in a simple statement the right side of the colon is empty. A free-text annotation may appear at the end of the data block: a `#` followed by any text up to the closing `]`; the annotation is ignored by the parser.

A **compound statement** has this form:

```
<name> <is | is_new> <rank> <action> <object>, <object>, … [&D <name>=<dataID> : <object>=<dataID>, … #<comment>]
```

The part before the action is the establishment action, exactly as in a simple statement. The action and its objects follow. The data block is optional.

Every object named in a compound statement MUST be a declared taxon (E2). An object may be declared before or after the statement that uses it: all declarations are collected before any reference is resolved.

When an object name is resolved, the subject of its own compound statement is **not** a candidate. A compound statement never refers to itself. For example, in

```
Hexurella is genus synonymizes Hexurella, Atypus
```

the object `Hexurella` does not mean the compound taxon being declared here. It means another declared `Hexurella` — a simple `Hexurella`, or a compound `Hexurella` with a different action. There are three outcomes:

- exactly one other declared `Hexurella` exists → the object points to it;
- no other declared `Hexurella` exists → the object is undeclared and throws an exception (E2);
- two or more exist → the reference is ambiguous if those taxa differ in the character data they contribute or in status (E4, Section 5); if they are interchangeable, it is fine.

## 3. Assigning dataIDs

A **dataID** links a taxon to one row of character data in the NEXUS matrix. A dataID is written in the data block `[&D … ]`.

A data block uses a colon. The value to the left of the colon is the dataID of the subject. The values to the right of the colon are the dataIDs of the objects. A simple statement has no objects, so the right side of the colon is empty — but the colon is still written.

A dataID has one of three values:

- a **real** dataID — the label of a data row in the matrix;
- **None** — this taxon definitely has no character data;
- **blank** — no dataID is given (the name is left out of the data block).

**None** and **blank** are different. `[&D Hexurella=None]` says Hexurella has no data. Leaving Hexurella out of the data block says nothing about Hexurella's data: the dataID, if any, may be given by another statement (for an object, by its own declaration), and if none is given, the taxon simply has no data for analysis.

A declared taxon points to **at most one** dataID. If one taxon is given two different real dataIDs, or is given **None** in one place and a real dataID in another, this throws an exception (E5). Blank is not an explicit value, so a blank together with any explicit value — a real dataID or **None** — is not a conflict; the explicit value is used.

A single dataID **may** be shared by more than one taxon. This is allowed, because two taxa may have the same character data. CARL warns when two taxa share a real dataID (W1): they cannot be told apart in analyses. This warning is **not** raised for a `renames` subject and its object that share a dataID (whether inherited or explicitly assigned) — that sharing is expected.

## 4. Actions

A compound statement applies one action to its objects. Every action needs at least one object (E8).

**renames.** The subject is a new name for the object, and the object is the old name. A renames statement has exactly one object (E8 otherwise). The subject and object MUST NOT have the same name (E6). **`renames` inheritance:** if the subject's dataID is blank, the subject takes on the object's dataID state — real, `None`, or blank (given by the object's own declaration, or by an in-statement pointer). This is the one place a taxon's dataID is determined by another taxon.

**synonymizes.** The subject is the accepted name. The objects are names that become synonyms of the subject. The subject may keep its own name by listing that name as an object (resolved by the rule in Section 2).

**divides.** The subject is a taxon that is split. The objects are the taxa it is split into. The subject may keep its name for one of them by listing that name as an object (resolved by the rule in Section 2).

**includes.** The subject is a taxon that contains the objects as members. It is used to build a higher taxon, or to group taxa of the same rank. The subject may share a name with a member (resolved by the Section 2 self-exclusion rule, as for `synonymizes` and `divides`); no special semantics apply.

DataIDs in a compound statement follow these rules:

- **Subject.** The subject's dataID is the value to the left of the colon. The compound statement is the subject's own declaration, so this dataID **persists** — it is the subject's dataID everywhere it is used. (Exception: a `renames` subject whose left slot is blank takes the object's dataID as its own — that value, which may itself be blank, is then the subject's dataID.)
- **Objects.** An object's dataID normally comes from its own declaration. A dataID written for an object here (to the right of the colon) is only a reference, so it is **local to this statement and does not persist**: the object's own declaration is unchanged, and the object is blank again wherever else it is used. If the object's own declaration already gives it a dataID, the in-statement value MUST match it (E5).
- **Use.** The object's dataID as used in this statement — its in-statement value if one is given, otherwise the dataID from its own declaration — is what feeds the group's character union (Section 5) and, for `renames`, what the subject inherits.
- **Selecting.** When an object name matches more than one declared taxon, the in-statement dataID also selects which one is meant (Section 5).

Each compound statement also creates a group (Section 5).

## 5. Analyses and Information Retrieval

**Groups.** Every compound statement creates a **group**. The subject is the head of the group, and the objects are its members. A group is not a separate kind of entity — it is simply what a compound taxon and its objects constitute (one group per compound taxon). Groups are used in analyses.

A group's character data is found as follows:

- if the subject has a real dataID, the group uses that data row;
- if the subject has **None**, the group has no character data;
- if the subject is blank, the group uses the union of the character data of its members. A member's data is its in-statement value if one is given in this statement, otherwise the member's dataID (which, for a renamed member, is the inherited one). If a member is itself a group, its data is found the same way.

Group membership MUST be acyclic. If a group contains itself, directly or through other groups, this throws an exception (E7). Acyclic membership is what lets the union above finish.

**Analysis eligibility.** A taxon can take part in character-based analyses (descriptions, keys, comparisons) only if it has character data — a real dataID, or, for a group, a non-empty union. A taxon with **None**, or with no data, cannot.

**Information retrieval.** A taxon can have information retrieved from external databases only if its status is `is` (an existing, published name). A taxon with status `is_new` cannot, because it is not yet in any database. Retrieval depends only on status, not on the dataID.

These are two separate properties. Status decides retrieval. The dataID decides analysis. A taxon may be eligible for one and not the other.

**Resolving an ambiguous reference.** A reference is ambiguous (E4) only when the same-named declared taxa differ in what they contribute — the **character data** they supply to a group (found as above) or their **status**. This is not merely their dataID: a blank *simple* taxon supplies nothing, whereas a blank *compound* taxon may supply its members' union of character data, so those two are **not** interchangeable. When the same-named taxa supply the same character data and share a status, they are interchangeable **for this reference** — though they remain distinct taxa — so the reference is not ambiguous and needs no resolution (W2 still reports the duplicate name). To resolve a real ambiguity, the user names the intended taxon by writing its dataID (`=<dataID>` or `=None`) in the data block (Section 4), or by choosing it in the Edit popup. The value written in the data block names the intended taxon only if it is a real dataID or `None`; leaving that slot blank names no particular taxon, so a taxon whose dataID is **blank** is chosen with the Edit popup.

## 6. Exceptions and warnings

The following throw an **exception** for the user to resolve. Each is cross-referenced where it arises.

- **E1. Undeclared taxon** — a statement does not give a name, a status (`is` or `is_new`), and a rank (Section 1).
- **E2. Undeclared object** — an object in a compound statement is not a declared taxon (Sections 1, 2).
- **E3. Conflicting objects** — two compound declarations match a compound taxon's identity (name, status, rank, action) but list different objects (Section 1). (Differing rank or status makes declarations *different* taxa, not a conflict; a dataID disagreement is E5.)
- **E4. Ambiguous reference** — a name used as an object matches two or more declared taxa that differ in the character data they contribute or in status, and none is singled out (Sections 1, 5). (Declared taxa that are interchangeable — same character data and status — do not trigger E4; the duplicate name is reported by W2.)
- **E5. Conflicting dataIDs** — a taxon is associated with two different dataIDs (two different real dataIDs, or **None** together with a real dataID), whether from its own declaration, a repeated declaration of the same taxon, or an in-statement value that must match it (Sections 3, 4).
- **E6. Self-renaming** — a renames subject and its object have the same name (Section 4).
- **E7. Cyclic group** — a group contains itself, directly or through other groups (Section 5).
- **E8. Malformed action** — a compound statement's action lacks the objects it requires: every action needs at least one object, and `renames` needs exactly one (Section 4).

The following raise a **warning**, not an exception. Work continues.

- **W1. Shared dataID** — two different taxa point to the same real dataID; they cannot be told apart in analyses (Section 3). Not raised for a `renames` subject and object that share a dataID (inherited or explicitly assigned).
- **W2. Repeated name** — a name belongs to more than one declared taxon; references to that name may become ambiguous in some contexts (Section 1).
