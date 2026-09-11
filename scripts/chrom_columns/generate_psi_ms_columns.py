#!/usr/bin/env python3
"""Generate psi-ms-columns.obo-fragment: model-level chromatographic column terms.

Reads the repo-rt column catalog (a TSV) and writes an OBO *fragment* -- [Term]
stanzas only, no header and no typedefs -- holding the vendor and model terms in
the MS:5000000 namespace:

    MS:5000000+  <vendor> chromatographic column model      (one per vendor)
      MS:5001000+  <product>                                (one per model)
        is_a <vendor> chromatographic column model
        is_a MS:1003921 ! liquid chromatographic column
        relationship: has_separation_mode ...               (when known)
        property_value: usp_designation "..." xsd:string    (per USP code)

The branch parent (MS:1004011 chromatographic column model) lives in psi-ms-core.obo,
as do every typedef and the `columns` subsetdef these stanzas use. The fragment is
deliberately not a standalone OBO document: scripts/build_release_obo.py splices it
into psi-ms-core.obo to produce the psi-ms.obo release artefact, and a header clause
appearing mid-file would be a syntax error there.

This generator does not correct or infer data — it only
verifies the input is valid UTF-8 and well-formed (correct field counts) and aborts
otherwise. Separation mode is read from the "mode" column and USP designation from
the "usp" column; each should be identical on every row of a model, so a field is
emitted only when every row agrees — any within-model disagreement emits nothing for
that field and is reported for upstream fixing (no majority guess is made).

Every term this fragment references but does not define is listed in
REQUIRED_CORE_TERMS and checked against psi-ms-core.obo before any output is written
(also available standalone via --check-core-refs, which CI runs on PRs touching core).

IDs are stable across runs: the committed .github/repo-rt/psi-ms-column-ids.tsv is
the id LEDGER -- the sole authority binding (company, column) catalog keys to MS
ids -- and is read back before any id is minted. Identity is the catalog key, never
the displayed label, so a model gaining or losing a collision suffix (or any other
label change) keeps its id. The ledger is append-only: a model that leaves the
catalog keeps its row (its term is dropped from the fragment, but its id is never
handed to another term) and a model that returns under the same key reclaims its
original id. Vendor terms have ledger rows too, with an empty column field -- inert
to repo-rt's join, since every real catalog row has a non-empty column.

repo-rt mirrors each assigned id in a "psi_ms_id" catalog column (the ledger is the
contract its add_psi_ms_id.py joins on to back-propagate ids). When present, the
mirror is cross-validated against the ledger: a blank cell is a new model; a known
key whose mirror disagrees aborts the run; a new key whose rows carry the id of a
key that has left the catalog is a mirror-proven rename, and the id is transferred
to the new key; a new key carrying any other id (live or never minted) aborts. A
rename consumes the old key's ledger row, so -- unlike a retirement -- reverting one
upstream mints a second id for the same physical column.
--reset-ids ignores the committed ledger and assigns clean sequential ids (used once
to mint the initial baseline; the mirror cross-check is skipped, having nothing to
reconcile against). --allow-shrink acknowledges an intentional mass removal of
models; --dry-run prints the report without writing either file. No flag ever moves
or reuses an id.

This fragment is versioned by Git and carries no data-version of its own; the release
version is psi-ms-core.obo's `data-version`, which the splice copies through.

Usage:
    python scripts/chrom_columns/generate_psi_ms_columns.py \\
        --input column_database.tsv --output psi-ms-columns.obo-fragment
    python scripts/chrom_columns/generate_psi_ms_columns.py --check-core-refs
"""

import argparse
import csv
import io
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

OUTPUT_DEFAULT = "psi-ms-columns.obo-fragment"
INPUT_DEFAULT = ".jeh-local/column_database_fixed.tsv"
MAPPING_DEFAULT = ".github/repo-rt/psi-ms-column-ids.tsv"
CORE_DEFAULT = "psi-ms-core.obo"

# ID bands within the MS:5000000 namespace (kept separate so the file stays
# grouped scaffold-then-leaves even as new terms are appended over time).
# The vendor band opens at MS:5000000: that id previously held the branch parent,
# which now lives in psi-ms-core.obo as MS:1004011. Id assignment is append-only:
# retired keys keep their ledger rows, so max(used) covers every id ever minted and
# a retired id is never handed to a different term. 5000000 is therefore only
# reachable on a --reset-ids run, not by the next vendor to appear.
VENDOR_BAND = (5000000, 5000999)
LEAF_BAND = (5001000, 5999999)

LEDGER_HEADER = "company\tcolumn\tpsi_ms_id"


def ms_num(ms_id):
    return int(ms_id.split(":")[1])


# A regenerated catalog retaining fewer than this fraction of the prior model count
# is treated as a truncated/corrupt download and aborts (guarded in build_columns_obo).
MIN_RETAIN_FRACTION = 0.5

# Subset carried by every term in this fragment, so consumers can include or exclude the
# whole column branch. `subsetdef: columns` is declared once, in psi-ms-core.obo -- the
# fragment has no header to declare it in, and after the splice there is only one document.
SUBSET = "columns"

# Separation-mode key -> (technique term id, label, definition adjective).
MODE_INFO = {
    "RP": ("MS:1003582", "reversed phase chromatography", "reversed-phase"),
    "NP": ("MS:1003583", "normal phase chromatography", "normal-phase"),
    "HILIC": ("MS:1003584", "hydrophilic interaction liquid chromatography", "HILIC"),
    "IEX": ("MS:1003579", "ion-exchange chromatography", "ion-exchange"),
    "SEC": ("MS:1003580", "size-exclusion chromatography", "size-exclusion"),
    "mixed": ("MS:1003586", "mixed mode chromatography", "mixed-mode"),
}

# The branch parent, plus every other term these stanzas reference but do not define.
# All live in psi-ms-core.obo. Checked before writing output (see check_core_refs): a
# deletion breaks the release, and a rename leaves `! label` comments contradicting the
# term they point at, which nothing downstream would flag.
# The technique terms are derived from MODE_INFO rather than repeated, so a mode added
# there cannot be left unchecked here.
PARENT_ID = "MS:1004011"
LIQUID_COLUMN = "MS:1003921"
REQUIRED_CORE_TERMS = {
    PARENT_ID: "chromatographic column model",
    LIQUID_COLUMN: "liquid chromatographic column",
    **{term_id: label for term_id, label, _ in MODE_INFO.values()},
}

# The typedefs the leaf stanzas use. Also core's, also unresolvable from this file
# alone, and likelier than a term to be dropped unnoticed in a core edit.
REQUIRED_CORE_TYPEDEFS = ("has_separation_mode", "usp_designation")

# repo-rt "mode" column value -> separation-mode key.
TSV_MODE = {
    "RP": "RP",
    "NP": "NP",
    "HILIC": "HILIC",
    "IEX": "IEX",
    "SEC": "SEC",
    "mixed-Mode": "mixed",
}

# Cells that legitimately carry no separation mode (compared casefolded). Any OTHER
# unmapped value is upstream vocabulary drift -- a single casing change would strip
# has_separation_mode from every affected term -- so it is counted and reported rather
# than silently treated as "no mode".
NON_MODES = {"", "na", "n/a", "other", "unknown"}

# --- reading the catalog ----------------------------------------------------

REQUIRED_COLUMNS = ("company", "column", "mode", "usp")


# Invisible characters folded away by clean(). They are indistinguishable from a plain
# space (or from nothing) in a rendered term label but distinct to ==, so two catalog
# rows differing only by one would form two identity keys, mint two ids and emit two
# terms with identical-looking names -- which the duplicate-label guard cannot see
# either, because the strings genuinely differ.
INVISIBLE = str.maketrans(
    {
        "\u00a0": " ",  # no-break space
        "\u200b": "",  # zero-width space
        "\u200c": "",  # zero-width non-joiner
        "\u200d": "",  # zero-width joiner
        "\u2060": "",  # word joiner
        "\ufeff": "",  # zero-width no-break space / BOM
    }
)


def clean(text):
    """Normalize a catalog cell for use as an OBO name/def value and as an identity key:
    drop control characters, fold invisible/non-breaking characters, collapse whitespace."""
    text = "".join(ch for ch in text if ch >= " " and ch != "\x7f")
    return re.sub(r"\s+", " ", text.translate(INVISIBLE)).strip()


def read_catalog(tsv_path):
    """Load the pre-cleaned repo-rt catalog into a DataFrame, keeping every cell as
    a literal string. The catalog must be valid UTF-8 (names and USP codes are
    corrected upstream); a stray non-UTF-8 byte means the input skipped that fix,
    so we abort rather than silently recover it. na_filter=False keeps 'NA' and
    blanks as text; fillna covers cells missing from a short row.

    An over-length row (more tab-separated fields than the header) ABORTS the run.
    A TSV has no quoting, so a tab count is authoritative; pandas would otherwise
    either treat the surplus field as a row index (silently shifting every column)
    or drop/truncate the row, and a vanished or shifted model would silently lose its
    stable id. Short rows are still tolerated (padded by fillna). index_col=False is
    belt-and-braces against the index-shift heuristic, and quoting=QUOTE_NONE keeps a
    stray double-quote from merging rows and matches the raw tab-count check above.

    Because QUOTE_NONE does no quote processing, a field an upstream export wrapped in
    double quotes (the CSV convention for a value containing a comma) keeps those quotes
    as literal characters. In the identity columns they would leak into term names and
    — since a quoted name differs from the previously assigned unquoted one — mint fresh
    ids and churn the mapping; in the value columns they corrupt the emitted annotation
    instead (a `usp` cell of '"L1, L11"' yields the codes '"L1' and 'L11"'). Either way
    the file is not the tab-delimited catalog this reads, so a wrapped-quote cell in any
    required column ABORTS the run."""
    try:
        text = Path(tsv_path).read_bytes().decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(
            f"{tsv_path} is not valid UTF-8 ({e}); the catalog must be pre-cleaned "
        )
    lines = text.split("\n")
    ncols = len(lines[0].split("\t")) if lines and lines[0] else 0
    if ncols == 0:
        raise ValueError(f"{tsv_path} is empty or has no header row")
    overlong = [
        i
        for i, ln in enumerate(lines[1:], start=2)
        if ln != "" and len(ln.split("\t")) > ncols
    ]
    if overlong:
        raise ValueError(
            f"{tsv_path} has over-length row(s) at line(s) "
            f"{overlong[:10]}{' ...' if len(overlong) > 10 else ''} "
            f"(more than {ncols} tab-separated fields); fix the field count upstream "
            "rather than letting the row be dropped or shifted"
        )
    df = pd.read_csv(
        io.StringIO(text),
        sep="\t",
        dtype=str,
        na_filter=False,
        index_col=False,
        quoting=csv.QUOTE_NONE,
    ).fillna("")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"catalog is missing required columns: {missing}")
    # CSV-quoting guard (see docstring): a proper tab-delimited catalog wraps no field
    # in quotes. Flag any required cell that arrives wrapped in a matched double-quote
    # pair so the quoting is stripped upstream rather than silently corrupting the
    # names and ids (company/column) or the emitted annotations (mode/usp).
    quoted = sorted(
        {
            f"{col}={cell!r}"
            for col in REQUIRED_COLUMNS
            for cell in df[col].str.strip()
            if len(cell) >= 2 and cell.startswith('"') and cell.endswith('"')
        }
    )
    if quoted:
        raise ValueError(
            f"{tsv_path} has CSV-quoted field(s): "
            f"{quoted[:10]}{' ...' if len(quoted) > 10 else ''}; a tab-delimited catalog "
            "must not wrap fields in double quotes (strip the quoting upstream)"
        )
    return df


def load_models(tsv_path):
    """Return (models, notes).

    models  {(vendor, product): {"modes": Counter, "usps": Counter, "ms_ids": Counter}}
    notes   input-quality counts for the report: rows dropped for a blank identity cell,
            unmapped `mode` values, and `usp` tokens that are not USP packing codes.
            All three are silent data loss otherwise -- the affected terms simply come
            out missing a field -- so they are surfaced with the id changes.

    A catalog has many rows per model (one per physical size); grouping by
    (vendor, product) lets resolve_model vote over those rows. USP cells are
    normalized before counting so representational variants ("L1/L11" vs "L11/L1")
    aggregate instead of tying.

    product is the model name read straight from the catalog's "column" field (e.g.
    "ACE C18" for company "Advanced Chromatography Technologies") — the authoritative,
    vendor-stripped model label. (vendor, product) is the model's identity throughout:
    the grouping key, the leaf-label base, and the repo-rt mapping join key.
    """
    df = read_catalog(tsv_path)
    # psi_ms_id is an optional mirror column (absent on the first catalog); default to
    # an all-"" Series so the cross-check simply sees no ids rather than raising on a
    # KeyError. Both branches yield a Series (never a bare scalar) so the column is a
    # consistent type for static analysis as well as pandas' scalar broadcasting.
    if "psi_ms_id" in df.columns:
        ms_id = df["psi_ms_id"].str.strip()
    else:
        ms_id = pd.Series("", index=df.index, dtype=str)
    # Whitespace is trimmed with the vectorized .str.strip() accessor rather than a
    # per-element lambda: it is typed to return a string Series, so the callbacks below
    # never touch .strip() on a cell the checker widens to NAType (read_catalog's
    # dtype=str/na_filter=False guarantee a real str at runtime regardless).
    df = df.assign(
        vendor=df["company"].str.strip().map(clean),
        product=df["column"].str.strip().map(clean),
        # "" (not None) for unknown modes / no codes so the columns stay all-string
        # (a None would become a truthy NaN and slip past the `if` filters below).
        mode_raw=df["mode"].str.strip(),
        mode_key=df["mode"].str.strip().map(lambda m: TSV_MODE.get(m, "")),
        usp_canon=df["usp"].map(
            lambda u: "/".join(sorted(split_usp_codes(u), key=usp_sort_key))
        ),
        ms_id=ms_id,
    )
    named = df[(df["vendor"] != "") & (df["product"] != "")]

    notes = {
        "dropped_rows": len(df) - len(named),
        "unmapped_modes": Counter(
            raw
            for raw, key in zip(named["mode_raw"], named["mode_key"])
            if not key and raw.casefold() not in NON_MODES
        ),
        "rejected_usp": Counter(
            token for cell in named["usp"] for token in usp_tokens(cell)[1]
        ),
    }

    models = {}
    for (vendor, product), group in named.groupby(["vendor", "product"], sort=False):
        models[(vendor, product)] = {
            "modes": Counter(m for m in group["mode_key"] if m),
            "usps": Counter(u for u in group["usp_canon"] if u),
            "ms_ids": Counter(i for i in group["ms_id"] if i),
        }
    return models, notes


# --- resolving a model's separation mode and USP designation ----------------


# Whole-cell "no value" spellings (compared casefolded), recognised BEFORE the cell is
# split: 'N/A' shares its separator with a real multi-code cell, so splitting first would
# turn it into the codes 'N' and 'A'. A USP packing code is a letter class plus a number.
USP_PLACEHOLDERS = {"", "na", "n/a", "n.a.", "n.d.", "nd", "-", "--", "none", "null",
                    "unknown", "?"}
USP_CODE = re.compile(r"[LGS]\d{1,3}")


def usp_tokens(cell):
    """Split a raw USP cell into (codes, rejected), e.g. 'L1/L11' or 'L20, L33'.

    A placeholder cell yields nothing and rejects nothing. Every other token must be a
    USP packing code: these become permanent annotations on a published term, so an
    unrecognised one is rejected and reported for upstream fixing rather than emitted."""
    if cell.strip().casefold() in USP_PLACEHOLDERS:
        return [], []
    codes, rejected = [], []
    for token in re.split(r"[/,;]", cell):
        token = token.strip()
        if not token:
            continue
        if USP_CODE.fullmatch(token.upper()):
            codes.append(token.upper())
        else:
            rejected.append(token)
    return codes, rejected


def split_usp_codes(cell):
    """The emittable codes of a raw USP cell (see usp_tokens)."""
    return usp_tokens(cell)[0]


def usp_sort_key(code):
    # Numeric order so L9 sorts before L114 (plain string sort would invert them), then
    # the code itself so that L1/S1 and S1/L1 canonicalise to the same string: on the
    # number alone they tie, Python's stable sort keeps input order, and one model's rows
    # would read as two different values and be reported as a deviation.
    digits = re.sub(r"\D", "", code)
    return int(digits) if digits else 0, code


def resolve_usp(usp_counter):
    """Resolve a model's USP designation from its per-row cells.

    A column model should carry the same USP code (or combined cell) on every row, so
    this returns (codes, deviated): when every row agrees, codes is that single value
    and deviated is False; when the rows disagree at all, there is no trustworthy value
    so codes is empty and deviated is True, flagging the model for an upstream fix. No
    majority vote is taken — any inconsistency is surfaced rather than guessed through.
    """
    if len(usp_counter) == 1:
        (value,) = usp_counter
        return sorted(split_usp_codes(value), key=usp_sort_key), False
    return [], len(usp_counter) > 1


def resolve_mode(mode_counter):
    """Resolve a model's separation mode from its per-row cells, like resolve_usp.

    Returns (mode_key or None, deviated): a single agreed value is emitted, any
    disagreement emits nothing and sets deviated for the report, and no-data emits
    nothing without flagging."""
    if len(mode_counter) == 1:
        (value,) = mode_counter
        return value, False
    return None, len(mode_counter) > 1


def resolve_model(entry):
    """Resolve a model to (mode, usp_literals, deviations).

    mode          separation-mode key for has_separation_mode, or None.
    usp_literals  USP codes to emit as usp_designation (empty when unresolved).
    deviations    {field: {value: count}} for every field (usp, mode) whose rows do
                  not agree, surfaced in the report so the inconsistency is fixed
                  upstream. A field whose rows disagree emits nothing (no majority
                  guess); only a field on which every row agrees is emitted.
    """
    codes, usp_deviated = resolve_usp(entry["usps"])
    mode, mode_deviated = resolve_mode(entry["modes"])
    deviations = {}
    if usp_deviated:
        deviations["usp"] = dict(entry["usps"])
    if mode_deviated:
        deviations["mode"] = dict(entry["modes"])
    return mode, codes, deviations


# --- naming ------------------------------------------------------------------


def colliding_names(models):
    """Model names (the catalog "column" field) shared by more than one vendor and so
    needing vendor disambiguation in the leaf label."""
    vendors_by_name = defaultdict(set)
    for vendor, product in models:
        vendors_by_name[product].add(vendor)
    return {name for name, vendors in vendors_by_name.items() if len(vendors) > 1}


def leaf_label(product, vendor, colliding):
    """Leaf term label: the model name, suffixed with the vendor only when that name is
    shared across vendors (so the emitted labels stay unique)."""
    return f"{product} ({vendor})" if product in colliding else product


def with_period(sentence):
    """End a sentence with a period unless it already does (vendors ending 'Inc.')."""
    return sentence if sentence.endswith(".") else sentence + "."


def escape_def(text):
    """Escape a value for an OBO quoted def: string (upstream names may contain " or \\)."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def escape_tag(text):
    """Escape a value for an unquoted OBO tag line (name:). Three characters are
    structural in an unquoted value and each silently truncates or mangles the name:
    backslash is the escape character (a trailing one folds the next line into the name,
    a mid-string one deletes a character), `!` starts a comment the parser discards to
    end of line, and `{`/`}` open a trailing-modifier block. clean() already removes the
    newlines and tabs that would also need escaping. Backslash is doubled first, so the
    escapes introduced below are not themselves escaped."""
    for char in "\\", "!", "{", "}":
        text = text.replace(char, "\\" + char)
    return text


def leaf_definition(vendor, mode):
    if not mode:
        return with_period(
            f"A liquid chromatographic column model manufactured by {vendor}"
        )
    adjective = MODE_INFO[mode][2]
    article = "An" if adjective[0].lower() in "aeiou" else "A"
    return with_period(
        f"{article} {adjective} liquid chromatographic column model manufactured by {vendor}"
    )


# --- stanza builders (return text, no trailing blank line) ------------------


def vendor_stanza(vendor, vendor_id):
    definition = with_period(f"Chromatographic column model manufactured by {vendor}")
    lines = [
        "[Term]",
        f"id: {vendor_id}",
        f"name: {escape_tag(vendor)} chromatographic column model",
        f'def: "{escape_def(definition)}" [PSI:MS]',
        f"subset: {SUBSET}",
        f"is_a: {PARENT_ID} ! chromatographic column model",
    ]
    return "\n".join(lines)


def leaf_stanza(leaf_id, vendor, vendor_id, label, mode, usp_literals):
    lines = [
        "[Term]",
        f"id: {leaf_id}",
        f"name: {escape_tag(label)}",
        f'def: "{escape_def(leaf_definition(vendor, mode))}" [PSI:MS]',
        f"subset: {SUBSET}",
        f"is_a: {vendor_id} ! {vendor} chromatographic column model",
        f"is_a: {LIQUID_COLUMN} ! liquid chromatographic column",
    ]
    if mode:
        mode_id, mode_label, _ = MODE_INFO[mode]
        lines.append(f"relationship: has_separation_mode {mode_id} ! {mode_label}")
    for code in usp_literals:
        lines.append(f'property_value: usp_designation "{escape_def(code)}" xsd:string')
    return "\n".join(lines)


# --- cross-file reference check ----------------------------------------------


def check_core_refs(core_path):
    """Verify core still provides every term and typedef the fragment references.

    The fragment references these but cannot define them, and no per-file validator can
    see the mismatch: the fragment referencing core is legitimate by design. Terms are
    checked by name as well as id because a rename is the likelier accident -- the id
    still resolves after one, so the merged release ships silently wrong `! label`
    comments -- and obsoletion is likelier still in a CV maintained over years, leaving
    the release pointing live axioms at a deprecated term.

    Raises ValueError listing every problem, rather than stopping at the first.
    """
    terms, typedefs, obsolete, replaced_by = {}, {}, set(), {}
    table, current = None, None
    with open(core_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if line.startswith("["):
                table = {"[Term]": terms, "[Typedef]": typedefs}.get(line.strip())
                current = None
            elif table is None:  # header clauses, before the first stanza
                continue
            elif line.startswith("id: ") and current is None:
                current = line[len("id: ") :].strip()
            elif not current:
                continue
            elif line.startswith("name: "):
                table[current] = line[len("name: ") :].strip()
            elif line.startswith("is_obsolete: true"):
                obsolete.add(current)
            elif line.startswith("replaced_by: "):
                replaced_by[current] = line[len("replaced_by: ") :].strip()

    def obsolete_note(ref_id):
        successor = replaced_by.get(ref_id)
        return f"{ref_id} is obsolete in {core_path}" + (
            f" (replaced_by {successor}; point the fragment at it)"
            if successor
            else " and has no replaced_by"
        )

    problems = []
    for term_id, expected in sorted(REQUIRED_CORE_TERMS.items()):
        actual = terms.get(term_id)
        if actual is None:
            problems.append(
                f"{term_id} is not defined in {core_path} (expected {expected!r})"
            )
        elif actual != expected:
            problems.append(
                f"{term_id} is named {actual!r} in {core_path}, expected {expected!r}"
            )
        elif term_id in obsolete:
            problems.append(obsolete_note(term_id))
    for typedef_id in sorted(REQUIRED_CORE_TYPEDEFS):
        if typedef_id not in typedefs:
            problems.append(f"typedef {typedef_id} is not declared in {core_path}")
        elif typedef_id in obsolete:
            problems.append(obsolete_note(typedef_id))
    if problems:
        raise ValueError(
            f"{core_path} no longer provides what this fragment references:\n  "
            + "\n  ".join(problems)
        )
    return len(REQUIRED_CORE_TERMS) + len(REQUIRED_CORE_TYPEDEFS)


# --- stable id assignment (the ledger) ---------------------------------------


def read_ledger(path: str) -> dict[tuple[str, str], str]:
    """Read the committed id ledger: {(company, column): "MS:nnnnnnn"}.

    The ledger is the sole authority for id assignment. column == "" marks a vendor
    row. Rows whose key has left the catalog stay in the ledger permanently, so a
    retired id is never re-minted and a model that returns under the same key reclaims
    its old id. Identity lives here, not in the fragment: names there are display labels
    (escaped, collision-suffixed) and are never read back.

    ponytail: a mirror-proven rename CONSUMES the old key's row (apply_mirror rebinds
    it), so a rename reverted upstream mints a second id for the same physical column.
    Retiring the old key instead needs a fourth ledger field, which is the cross-repo
    contract repo-rt's add_psi_ms_id.py joins on -- add it there and here together, on
    evidence that renames actually get reverted.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} not found: the id ledger is required to preserve published ids. "
            "Pass --reset-ids only to mint a fresh baseline (every id changes)."
        )
    ledger, bound = {}, {}
    lines = Path(path).read_text(encoding="utf-8").split("\n")
    if lines[0] != LEDGER_HEADER:
        raise ValueError(f"{path}: header must be {LEDGER_HEADER!r}, got {lines[0]!r}")
    for n, line in enumerate(lines[1:], start=2):
        if line == "":
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            raise ValueError(
                f"{path} line {n}: expected 3 tab-separated fields, got {len(fields)}"
            )
        company, column, ms_id = fields
        if not re.fullmatch(r"MS:\d{7}", ms_id):
            raise ValueError(f"{path} line {n}: malformed psi_ms_id {ms_id!r}")
        key = (company, column)
        if key in ledger:
            raise ValueError(f"{path} line {n}: duplicate key {key!r}")
        if ms_id in bound:
            raise ValueError(
                f"{path} line {n}: id {ms_id} already bound to {bound[ms_id]!r}"
            )
        ledger[key] = ms_id
        bound[ms_id] = key
    return ledger


def read_fragment_ids(path: str) -> set[str]:
    """Set of term ids in the previously generated fragment. Liveness only -- which
    ledger rows had a term last run, for the shrink floor and the retired/resurrected
    report. Identity never comes from here; a missing fragment just means no
    liveness info (the ids themselves are safe in the ledger)."""
    if not os.path.exists(path):
        return set()
    return {
        line[len("id: ") :].strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.startswith("id: MS:")
    }


def assign_ids(
    keys, ledger: dict[tuple[str, str], str], band: tuple[int, int]
) -> dict[tuple[str, str], str]:
    """Assign ids in [lo, hi]: reuse the ledger id for a known key, else the next free
    id above the highest EVER used in the band -- retired keys keep their ledger rows,
    so no id ever moves and no retired id is ever reassigned."""
    lo, hi = band
    used = [ms_num(i) for i in ledger.values()]
    used = [n for n in used if lo <= n <= hi]
    nxt = max(used) + 1 if used else lo
    result = {}
    for key in keys:
        if key in ledger:
            if not (lo <= ms_num(ledger[key]) <= hi):
                raise RuntimeError(
                    f"ledger id {ledger[key]} for {key!r} is outside band {band}"
                )
            result[key] = ledger[key]
        else:
            if nxt > hi:  # fail loudly rather than mint a colliding out-of-band id
                raise RuntimeError(f"id band {band} exhausted; widen it")
            result[key] = f"MS:{nxt}"
            nxt += 1
    return result


# --- writing -----------------------------------------------------------------


def apply_mirror(models, ledger: dict[tuple[str, str], str]):
    """Reconcile the catalog's psi_ms_id mirror column with the ledger, BEFORE any id
    is assigned. Returns (ledger, renames): the ledger with mirror-proven renames
    rebound, and the (old_key, new_key, id) transfers for the report.

    The ledger is authoritative; the mirror is cross-validation plus the one signal
    that can prove a rename. Every disagreement is decidable, so nothing is warn-only:
      - blank cell                        -> new model / not yet back-propagated (ok)
      - id matches the key's ledger row   -> mirror agrees (ok)
      - known key, id differs             -> drift, abort
      - rows of one model disagree        -> corrupt mirror, abort
      - new key carrying the id of a key that LEFT the catalog
                                          -> rename: the id transfers to the new key
      - new key carrying a live term's id -> copy-paste error upstream, abort
      - new key carrying an id the ledger never minted -> corrupt mirror, abort
    """
    by_id = {i: k for k, i in ledger.items()}
    drift, conflicts, corrupt, renames = [], [], [], []
    for key, entry in sorted(models.items()):
        col_ids = set(entry["ms_ids"])
        if not col_ids:
            continue
        if len(col_ids) > 1:
            conflicts.append((key, sorted(col_ids)))
            continue
        (col_id,) = col_ids
        if key in ledger:
            if col_id != ledger[key]:
                drift.append((key, col_id, ledger[key]))
            continue
        holder = by_id.get(col_id)
        if holder is None:
            corrupt.append((key, col_id, "an id the ledger never minted"))
        elif holder in models:
            corrupt.append((key, col_id, f"the id of live model {holder!r}"))
        elif holder[1] == "":
            corrupt.append((key, col_id, f"the id of vendor row {holder[0]!r}"))
        else:  # holder left the catalog and its id rides rows under a new key: a rename
            del ledger[holder]
            ledger[key] = col_id
            by_id[col_id] = key
            renames.append((holder, key, col_id))
    if drift or conflicts or corrupt:
        lines = ["psi_ms_id mirror disagrees with the id ledger (aborting sync):"]
        lines += [f"  drift: {k!r} mirror={c} ledger={l}" for k, c, l in drift]
        lines += [
            f"  conflicting ids within model {k!r}: {ids}" for k, ids in conflicts
        ]
        lines += [
            f"  new key {k!r} carries {why} (mirror={c})" for k, c, why in corrupt
        ]
        raise ValueError("\n".join(lines))
    return ledger, renames


def render_ledger(ledger):
    """Serialize the id ledger: one (company, column, psi_ms_id) row per key, sorted by
    key so a vendor row (empty column) leads its company block. This one file is both
    the id authority read back next run and the cross-repo contract repo-rt joins on
    (its add_psi_ms_id.py must join on the same company + column keys; vendor and
    retired rows can never match a catalog row, so they are inert to that join).
    Keys are the cleaned company / column; clean() drops the C0 control chars
    (including tab and newline), so no value can contain a TSV delimiter and the rows
    need no quoting."""
    lines = [LEDGER_HEADER]
    lines += [f"{c}\t{p}\t{i}" for (c, p), i in sorted(ledger.items())]
    return "\n".join(lines) + "\n"


def build_columns_obo(models, ledger, prior_ids=frozenset(), allow_shrink=False):
    """Return (obo_text, ledger_text, report). Terms are emitted in id order so the
    file stays sorted and stable.

    `ledger` is the committed (company, column) -> id map, the sole id authority; it
    is only ever extended (or rebound by a mirror-proven rename), never rewritten.
    `prior_ids` are the ids present in the previously generated fragment -- liveness
    only, feeding the shrink floor and the retired/resurrected report sections."""
    if not models:
        raise ValueError(
            "catalog produced 0 column models; refusing to write an empty module"
        )
    prior_leaves = sum(
        1 for i in prior_ids if LEAF_BAND[0] <= ms_num(i) <= LEAF_BAND[1]
    )
    if not prior_leaves:
        print(
            "no previously generated fragment: the "
            f"{MIN_RETAIN_FRACTION:.0%} shrink floor is not enforced on this run"
        )
    if (
        prior_leaves
        and len(models) < prior_leaves * MIN_RETAIN_FRACTION
        and not allow_shrink
    ):
        raise ValueError(
            f"catalog shrank from {prior_leaves} to {len(models)} models "
            f"(<{MIN_RETAIN_FRACTION:.0%} retained); aborting as a likely truncated "
            "download. Re-run with --allow-shrink if the drop is intentional (no id "
            "moves: the vanished models keep their ledger rows)."
        )

    # An empty ledger (a --reset-ids baseline) has nothing to reconcile against: every
    # model would look like "a new key carrying an id the ledger never minted" and abort
    # the very run the flag exists for.
    ledger = dict(ledger)
    ledger, renames = apply_mirror(models, ledger) if ledger else (ledger, [])

    colliding = colliding_names(models)
    vendors = sorted({vendor for vendor, _ in models})
    vendor_assign = assign_ids([(v, "") for v in vendors], ledger, VENDOR_BAND)
    vendor_id = {v: vendor_assign[(v, "")] for v in vendors}

    labels = {(v, p): leaf_label(p, v, colliding) for v, p in models}
    # Each emitted leaf needs a unique label. leaf_label only disambiguates names
    # shared ACROSS vendors, so guard against two products of one vendor reducing to
    # the same label (e.g. an upstream whitespace variant), which would otherwise emit
    # duplicate OBO terms. Fail loudly to fix upstream. (Labels are display-only:
    # identity and ids key on (company, column), so a label change never moves an id.)
    dupes = sorted(lbl for lbl, n in Counter(labels.values()).items() if n > 1)
    if dupes:
        raise ValueError(
            f"non-unique leaf labels (fix in the upstream catalog): {dupes}"
        )
    leaf_ids = assign_ids(sorted(models), ledger, LEAF_BAND)

    new_ledger = {**ledger, **vendor_assign, **leaf_ids}
    # Defence in depth: read_ledger and assign_ids keep ids unique by construction,
    # but refuse to emit a duplicate-id module rather than ship one in an auto-PR.
    dup_ids = sorted(i for i, n in Counter(new_ledger.values()).items() if n > 1)
    if dup_ids:
        raise ValueError(f"duplicate ids generated (corrupt id ledger?): {dup_ids}")

    current = set(vendor_assign) | set(leaf_ids)
    report = {
        "deviations": [],
        "renames": renames,
        "minted": sorted((k, new_ledger[k]) for k in current if k not in ledger),
        # retired/resurrected need prior liveness: a ledger row is newly retired when
        # its term was in the last fragment but its key has no catalog model now, and
        # resurrected when the reverse holds. Without a prior fragment both are empty.
        "retired": sorted(
            (k, i) for k, i in ledger.items() if k not in current and i in prior_ids
        ),
        "resurrected": sorted(
            (k, ledger[k])
            for k in current
            if k in ledger and prior_ids and ledger[k] not in prior_ids
        ),
    }

    stanzas = []
    for vendor in vendors:
        vid = vendor_id[vendor]
        stanzas.append((ms_num(vid), vendor_stanza(vendor, vid)))

    for (vendor, product), entry in models.items():
        mode, usp_literals, deviations = resolve_model(entry)
        lid = leaf_ids[(vendor, product)]
        stanzas.append(
            (
                ms_num(lid),
                leaf_stanza(
                    lid,
                    vendor,
                    vendor_id[vendor],
                    labels[(vendor, product)],
                    mode,
                    usp_literals,
                ),
            )
        )
        if (
            deviations
        ):  # rows of this model disagree on usp/mode — flag for upstream fix
            # Keyed by (vendor, product), not the product name: two vendors selling the
            # same model name would otherwise produce identical, unresolvable lines.
            report["deviations"].append(((vendor, product), deviations))

    stanzas.sort(key=lambda pair: pair[0])
    body_block = "\n\n".join(text for _, text in stanzas) + "\n"
    return body_block, render_ledger(new_ledger), report


def report_markdown(models, report):
    """Markdown sync summary, printed to the Actions log and pasted into the PR body:
    every id-ledger change (minted / renames / retired / resurrected), the within-model
    data-quality deviations, and load_models' input-quality notes. One renderer so log
    and PR cannot drift."""

    def key_str(key):
        company, column = key
        return f"{company} / {column}" if column else f"{company} (vendor)"

    lines = [
        f"- vendors: {len({v for v, _ in models})}",
        f"- models: {len(models)}",
        "",
    ]
    if report["minted"]:
        lines.append(f"### New ids minted — {len(report['minted'])}")
        lines += [f"- `{key_str(k)}` → {i}" for k, i in report["minted"]]
        lines.append("")
    if report["renames"]:
        lines.append(
            f"### Renames (id transferred, proven by the psi_ms_id mirror) — {len(report['renames'])}"
        )
        lines += [
            f"- `{key_str(old)}` → `{key_str(new)}` (keeps {i})"
            for old, new, i in report["renames"]
        ]
        lines.append("")
    if report["retired"]:
        lines.append(
            f"### Retired (left the catalog; ledger row and id preserved) — {len(report['retired'])}"
        )
        lines.append(
            "_Policy: columns are annotation targets in perpetuity and should not "
            "leave repo-rt except error additions — before merging, check whether "
            "these upstream deletions should instead be restored in repo-rt._"
        )
        lines += [f"- `{key_str(k)}` ({i})" for k, i in report["retired"]]
        lines.append("")
    if report["resurrected"]:
        lines.append(
            f"### Resurrected (returned to the catalog; original id restored) — {len(report['resurrected'])}"
        )
        lines += [f"- `{key_str(k)}` ({i})" for k, i in report["resurrected"]]
        lines.append("")
    if report["deviations"]:
        lines.append(
            f"### Within-model value deviations (fix upstream) — {len(report['deviations'])}"
        )
        for key, dev in report["deviations"]:
            for field, counts in dev.items():
                lines.append(f"- `{key_str(key)}` — {field}={counts}")
        lines.append("")
    if report.get("unmapped_modes"):
        lines.append(
            f"### Unrecognised `mode` values (fix upstream) — {len(report['unmapped_modes'])}"
        )
        lines.append(
            "_Not in the generator's mode vocabulary, so every term built from these "
            "rows loses its `has_separation_mode` and its definition adjective. A whole "
            "vocabulary drifting (e.g. a casing change) shows up here as one value with "
            "a large count._"
        )
        lines += [
            f"- `{value}` — {n} row(s)"
            for value, n in sorted(report["unmapped_modes"].items())
        ]
        lines.append("")
    if report.get("rejected_usp"):
        lines.append(
            f"### Unrecognised `usp` values (fix upstream) — {len(report['rejected_usp'])}"
        )
        lines.append(
            "_Not USP packing codes, so they are dropped rather than published as "
            "`usp_designation` annotations._"
        )
        lines += [
            f"- `{value}` — {n} row(s)"
            for value, n in sorted(report["rejected_usp"].items())
        ]
        lines.append("")
    if report.get("dropped_rows"):
        lines.append(
            f"### Rows dropped for a blank company/column — {report['dropped_rows']}"
        )
        lines.append("")
    if not any(report.values()):
        lines.append("No id changes, input problems or within-model deviations.")
    return "\n".join(lines).rstrip() + "\n"


def write_atomic(path, text):
    """Write through a sibling temp file and os.replace, so a failed or killed run leaves
    the previous file intact instead of a truncated one."""
    tmp = f"{path}.tmp"
    Path(tmp).write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default=INPUT_DEFAULT, help="repo-rt column TSV")
    parser.add_argument("--output", default=OUTPUT_DEFAULT, help="OBO module to write")
    parser.add_argument(
        "--mapping",
        default=MAPPING_DEFAULT,
        help="the id ledger: company/column -> psi_ms_id TSV, read before "
        "minting and rewritten (also the repo-rt back-prop contract)",
    )
    parser.add_argument(
        "--reset-ids",
        action="store_true",
        help="ignore the committed id ledger and assign clean sequential ids",
    )
    parser.add_argument(
        "--allow-shrink",
        action="store_true",
        help="accept a large drop in model count (no id is moved or reused)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="run every check and print the report, but write neither the fragment "
        "nor the id ledger",
    )
    parser.add_argument(
        "--report", help="write a Markdown data-quality summary to this path"
    )
    parser.add_argument(
        "--core",
        default=CORE_DEFAULT,
        help="psi-ms-core.obo, checked for the terms this fragment references",
    )
    parser.add_argument(
        "--check-core-refs",
        action="store_true",
        help="only verify --core provides REQUIRED_CORE_TERMS, then exit",
    )
    args = parser.parse_args()

    if args.check_core_refs:
        n = check_core_refs(args.core)
        print(f"{args.core}: all {n} referenced terms and typedefs present, live, "
              "and named as expected")
        return

    check_core_refs(args.core)
    models, notes = load_models(args.input)
    ledger = (
        {} if args.reset_ids else read_ledger(args.mapping)
    )  # read before we overwrite it
    prior_ids = read_fragment_ids(
        args.output
    )  # liveness only; identity is the ledger's
    obo_text, ledger_text, report = build_columns_obo(
        models, ledger, prior_ids, allow_shrink=args.allow_shrink
    )

    if args.dry_run:
        print(f"dry run: {args.mapping} and {args.output} left untouched")
    else:
        if os.path.dirname(args.mapping):
            os.makedirs(os.path.dirname(args.mapping), exist_ok=True)
        # The ledger lands FIRST. It is the identity authority, so a run that dies
        # between the two writes must leave ids recorded-but-unpublished (harmless: the
        # next run reuses them) rather than published-but-unrecorded, which would let
        # the next run rebind published ids to different terms.
        write_atomic(args.mapping, ledger_text)
        print(f"wrote {args.mapping}")
        write_atomic(args.output, obo_text)
        print(f"wrote {args.output}")

    text = report_markdown(models, {**report, **notes})
    if args.report:
        write_atomic(args.report, text)
        print(f"wrote {args.report}")
    print(text, end="")


if __name__ == "__main__":
    # These are upstream-data and cross-file problems, not bugs: report the message and
    # exit 1 rather than dumping a traceback into the sync job's Actions log.
    try:
        main()
    except (ValueError, RuntimeError, FileNotFoundError) as exc:
        sys.exit(f"error: {exc}")
