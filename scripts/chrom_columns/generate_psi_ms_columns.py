#!/usr/bin/env python3
"""Generate psi-ms-columns.obo: model-level chromatographic column terms.

Reads the repo-rt column catalog (a TSV) and writes a self-contained OBO module
holding the whole column-model branch in the MS:5000000 namespace:

    MS:5000000  chromatographic column model                  (branch parent)
      MS:5000001+  <vendor> chromatographic column model      (one per vendor)
        MS:5001000+  <product>                                (one per model)
          is_a <vendor> chromatographic column model
          is_a MS:1003921 ! liquid chromatographic column
          relationship: has_separation_mode ...               (when known)
          property_value: usp_designation: "..." xsd:string   (per USP code)

The catalog is expected to be already clean and enriched: valid UTF-8 with product
names and USP codes corrected (.jeh-local/fix_column_database.py) and the "mode"
column filled from USP codes (.jeh-local/fill_separation_mode.py), both intended to
land in repo-rt itself. This generator does not correct or infer data — it only
verifies the input is valid UTF-8 and well-formed (correct field counts) and aborts
otherwise. Separation mode is read from the "mode" column and USP designation from
the "usp" column; each should be identical on every row of a model, so any
within-model disagreement is reported for upstream fixing (the clear majority is
emitted meanwhile; a tie emits nothing for that field).

References to MS:1000857, MS:1003920, MS:1003921 and the MS:1002271 technique
terms are external to this module and resolve against psi-ms.obo, with which it is
merged (`robot merge`) in the update-owl.yaml build to produce the published OWL.

IDs are stable across runs: existing terms keep their id (read back from the
output file), and only genuinely new vendors/models get the next free id. This
keeps the auto-generated PRs minimal when repo-rt changes. (A model that is
renamed upstream, or that newly collides with another vendor's product and so
gains a disambiguating suffix, counts as a new term and is reassigned.)

The committed OBO is the sole authority for id assignment; repo-rt mirrors each
assigned id in a "psi_ms_id" catalog column. This generator also writes that
mapping to .github/repo-rt/psi-ms-column-ids.tsv (the contract repo-rt joins on to
back-propagate the ids) and, when the catalog carries a "psi_ms_id" column, cross-
checks it: a blank cell is a new model, a stable term whose mirror disagrees aborts
the run, and a new label carrying a stale id is reported as a likely rename.
--reset-ids ignores the existing OBO and assigns clean sequential ids (used once to
mint the initial baseline).

The module's data-version is bumped one patch level only when the regenerated term
body differs from the committed module, so an unchanged catalog reproduces the file
byte-for-byte (and opens no PR).

Usage:
    python scripts/chrom_columns/generate_psi_ms_columns.py --input column_database.tsv
"""

import argparse
import csv
import io
import os
import re
from collections import Counter, defaultdict

import pandas as pd

OUTPUT_DEFAULT = "psi-ms-columns.obo"
INPUT_DEFAULT = ".jeh-local/column_database_fixed.tsv"
MAPPING_DEFAULT = ".github/repo-rt/psi-ms-column-ids.tsv"

# ID bands within the MS:5000000 namespace (kept separate so the file stays
# grouped scaffold-then-leaves even as new terms are appended over time).
PARENT_ID = "MS:5000000"
VENDOR_BAND = (5000001, 5000999)
LEAF_BAND = (5001000, 5999999)

# A regenerated catalog retaining fewer than this fraction of the prior model count
# is treated as a truncated/corrupt download and aborts (guarded in build_columns_obo).
MIN_RETAIN_FRACTION = 0.5

# Cross-file targets, defined in psi-ms.obo.
RUN_ATTRIBUTE = "MS:1000857"
CHROM_COLUMN = "MS:1003920"
LIQUID_COLUMN = "MS:1003921"

# Base/reset data-version; build_columns_obo bumps the patch component whenever the
# regenerated term body differs from the committed module (see read_prior_module).
DATA_VERSION = "4.1.255"


def build_header(data_version):
    return f"""\
format-version: 1.2
data-version: {data_version}
saved-by: Jonathan Hunter
default-namespace: MS
ontology: ms-columns
remark: Model-level chromatographic column terms (MS:5000000 namespace), generated from the repo-rt column database.
remark: Merged with psi-ms.obo (via robot merge in update-owl.yaml) to build the published OWL; its is_a / part_of / has_separation_mode targets (MS:1000857, MS:1003920, MS:1003921, and the MS:1002271 separation-technique terms) are defined in psi-ms.obo.
remark: coverage of namespace-id: MS:$sequence(7,5000000,5999999)$: Chromatographic column models

[Typedef]
id: has_separation_mode
name: has_separation_mode

[Typedef]
id: usp_designation
name: usp_designation
"""

# Separation-mode key -> (technique term id, label, definition adjective).
MODE_INFO = {
    "RP": ("MS:1003582", "reversed phase chromatography", "reversed-phase"),
    "NP": ("MS:1003583", "normal phase chromatography", "normal-phase"),
    "HILIC": ("MS:1003584", "hydrophilic interaction liquid chromatography", "HILIC"),
    "IEX": ("MS:1003579", "ion-exchange chromatography", "ion-exchange"),
    "SEC": ("MS:1003580", "size-exclusion chromatography", "size-exclusion"),
    "mixed": ("MS:1003586", "mixed mode chromatography", "mixed-mode"),
}

# repo-rt "mode" column value -> separation-mode key. The IEX/SEC/NP tokens are
# populated upstream by .jeh-local/fill_separation_mode.py (inferred from USP
# codes); "other", "NA" and blank stay unmapped (no has_separation_mode emitted).
TSV_MODE = {
    "RP": "RP",
    "NP": "NP",
    "HILIC": "HILIC",
    "IEX": "IEX",
    "SEC": "SEC",
    "mixed-Mode": "mixed",
}

# --- reading the catalog ----------------------------------------------------

REQUIRED_COLUMNS = ("company", "Column name", "mode", "usp")


def clean(text):
    """Drop control characters that would break an OBO name/def line."""
    return "".join(ch for ch in text if ch >= " ")


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
    stray double-quote from merging rows and matches the raw tab-count check above."""
    try:
        text = open(tsv_path, "rb").read().decode("utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(
            f"{tsv_path} is not valid UTF-8 ({e}); the catalog must be pre-cleaned "
            "(see .jeh-local/fix_column_database.py)"
        )
    lines = text.split("\n")
    ncols = len(lines[0].split("\t")) if lines and lines[0] else 0
    overlong = [i for i, ln in enumerate(lines[1:], start=2)
                if ln != "" and len(ln.split("\t")) > ncols]
    if overlong:
        raise ValueError(
            f"{tsv_path} has over-length row(s) at line(s) "
            f"{overlong[:10]}{' ...' if len(overlong) > 10 else ''} "
            f"(more than {ncols} tab-separated fields); fix the field count upstream "
            "rather than letting the row be dropped or shifted"
        )
    df = pd.read_csv(
        io.StringIO(text), sep="\t", dtype=str, na_filter=False,
        index_col=False, quoting=csv.QUOTE_NONE,
    ).fillna("")
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"catalog is missing required columns: {missing}")
    return df


def load_models(tsv_path):
    """Return {(vendor, product): {"modes": Counter, "usps": Counter, "ms_ids": Counter}}.

    A catalog has many rows per model (one per physical size); grouping by
    (vendor, product) lets resolve_model vote over those rows. USP cells are
    normalized before counting so representational variants ("L1/L11" vs "L11/L1")
    aggregate instead of tying.
    """
    df = read_catalog(tsv_path)
    # psi_ms_id is an optional mirror column (absent on the first catalog); default
    # to "" so the cross-check simply sees no ids rather than raising on a KeyError.
    ms_id = df["psi_ms_id"].map(lambda s: s.strip()) if "psi_ms_id" in df.columns else ""
    df = df.assign(
        vendor=df["company"].map(lambda s: clean(s.strip())),
        product=df["Column name"].map(lambda s: clean(s.strip())),
        # "" (not None) for unknown modes / no codes so the columns stay all-string
        # (a None would become a truthy NaN and slip past the `if` filters below).
        mode_key=df["mode"].map(lambda m: TSV_MODE.get(m.strip(), "")),
        usp_canon=df["usp"].map(lambda u: "/".join(sorted(split_usp_codes(u), key=usp_sort_key))),
        ms_id=ms_id,
    )
    df = df[(df["vendor"] != "") & (df["product"] != "")]

    models = {}
    for (vendor, product), group in df.groupby(["vendor", "product"], sort=False):
        models[(vendor, product)] = {
            "modes": Counter(m for m in group["mode_key"] if m),
            "usps": Counter(u for u in group["usp_canon"] if u),
            "ms_ids": Counter(i for i in group["ms_id"] if i),
        }
    return models


# --- resolving a model's separation mode and USP designation ----------------

def split_usp_codes(cell):
    """Split a raw USP cell into atomic codes, e.g. 'L1/L11' or 'L20, L33'."""
    codes = [c.strip() for c in re.split(r"[/,]", cell)]
    return [c for c in codes if c and c != "NA"]


def usp_sort_key(code):
    # Numeric order so L9 sorts before L114 (plain string sort would invert them).
    digits = re.sub(r"\D", "", code)
    return int(digits) if digits else 0


def resolve_usp(usp_counter):
    """Resolve a model's USP designation from its per-row cells.

    A column model should carry the same USP code (or combined cell) on every row, so
    this returns (codes, deviated): codes is the value to emit and deviated flags any
    within-model disagreement for the report, so it is fixed upstream rather than
    silently outvoted. When rows disagree but one value is the clear majority that
    value is still emitted (a best guess pending the fix); a top tie (e.g. an Excel
    drag-down series L1, L2, L3 ... one row each) has no trustworthy value and emits
    nothing.
    """
    if not usp_counter:
        return [], False
    ranked = usp_counter.most_common()
    deviated = len(ranked) > 1
    if deviated and ranked[0][1] == ranked[1][1]:
        return [], True
    return sorted(split_usp_codes(ranked[0][0]), key=usp_sort_key), deviated


def resolve_mode(mode_counter):
    """Resolve a model's separation mode from its per-row cells, like resolve_usp.

    Returns (mode_key or None, deviated): a clear majority is emitted as a best guess,
    a top tie emits nothing rather than asserting an arbitrary winner, and any
    disagreement sets deviated for the report."""
    if not mode_counter:
        return None, False
    ranked = mode_counter.most_common()
    deviated = len(ranked) > 1
    if deviated and ranked[0][1] == ranked[1][1]:
        return None, True
    return ranked[0][0], deviated


def resolve_model(entry):
    """Resolve a model to (mode, usp_literals, deviations).

    mode          separation-mode key for has_separation_mode, or None.
    usp_literals  USP codes to emit as usp_designation (empty when unresolved).
    deviations    {field: {value: count}} for every field (usp, mode) whose rows do
                  not agree, surfaced in the report so the inconsistency is fixed
                  upstream. A field with a clear majority still emits that majority as
                  a best guess; a tie emits nothing for that field.
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

def bare_name(vendor, product):
    """Product name with the leading vendor string removed. The vendor is always a
    prefix in the repo-rt catalog; fail loudly if a future row breaks that rather than
    blindly slicing len(vendor) chars off the wrong string and minting a garbled
    label (and thus a wrong id / mapping key)."""
    if not product.startswith(vendor):
        raise ValueError(
            f"product {product!r} does not start with vendor {vendor!r} "
            "(fix in the upstream catalog)"
        )
    return product[len(vendor):].strip()


def colliding_bare_names(models):
    """Bare names shared by more than one vendor (need vendor disambiguation)."""
    vendors_by_bare = defaultdict(set)
    for vendor, product in models:
        vendors_by_bare[bare_name(vendor, product)].add(vendor)
    return {name for name, vendors in vendors_by_bare.items() if len(vendors) > 1}


def leaf_label(vendor, product, colliding):
    name = bare_name(vendor, product)
    return f"{name} ({vendor})" if name in colliding else name


def with_period(sentence):
    """End a sentence with a period unless it already does (vendors ending 'Inc.')."""
    return sentence if sentence.endswith(".") else sentence + "."


def escape_def(text):
    """Escape a value for an OBO quoted def: string (upstream names may contain " or \\)."""
    return text.replace("\\", "\\\\").replace('"', '\\"')


def escape_tag(text):
    """Escape a value for an unquoted OBO tag line (name:). Backslash is the OBO escape
    character, so it must be doubled; clean() already removes the newlines/tabs that
    would otherwise need escaping in an unquoted value. Without this a trailing
    backslash folds the next line into the name and a mid-string one deletes a char."""
    return text.replace("\\", "\\\\")


def leaf_definition(vendor, mode):
    if not mode:
        return with_period(f"A liquid chromatographic column model manufactured by {vendor}")
    adjective = MODE_INFO[mode][2]
    article = "An" if adjective[0].lower() in "aeiou" else "A"
    return with_period(
        f"{article} {adjective} liquid chromatographic column model manufactured by {vendor}"
    )


# --- stanza builders (return text, no trailing blank line) ------------------

def parent_stanza():
    return (
        f"[Term]\nid: {PARENT_ID}\n"
        "name: chromatographic column model\n"
        'def: "A specific chromatographic column product, identified by its '
        'manufacturer and product name." [PSI:MS]\n'
        f"is_a: {RUN_ATTRIBUTE} ! run attribute\n"
        f"relationship: part_of {CHROM_COLUMN} ! chromatographic column"
    )


def vendor_stanza(vendor, vendor_id):
    definition = with_period(f"Chromatographic column models manufactured by {vendor}")
    return (
        f"[Term]\nid: {vendor_id}\n"
        f"name: {escape_tag(vendor)} chromatographic column model\n"
        f'def: "{escape_def(definition)}" [PSI:MS]\n'
        f"is_a: {PARENT_ID} ! chromatographic column model"
    )


def leaf_stanza(leaf_id, vendor, vendor_id, label, mode, usp_literals):
    lines = [
        "[Term]",
        f"id: {leaf_id}",
        f"name: {escape_tag(label)}",
        f'def: "{escape_def(leaf_definition(vendor, mode))}" [PSI:MS]',
        f"is_a: {vendor_id} ! {vendor} chromatographic column model",
        f"is_a: {LIQUID_COLUMN} ! liquid chromatographic column",
    ]
    if mode:
        mode_id, mode_label, _ = MODE_INFO[mode]
        lines.append(f"relationship: has_separation_mode {mode_id} ! {mode_label}")
    for code in usp_literals:
        lines.append(f'property_value: usp_designation: "{escape_def(code)}" xsd:string')
    return "\n".join(lines)


# --- stable id assignment ----------------------------------------------------

def read_existing_ids(path):
    """Map term name -> existing MS id from a prior generation (for stable ids)."""
    ids = {}
    if not os.path.exists(path):
        return ids
    current = None
    for line in open(path, encoding="utf-8"):
        if line.startswith("id: MS:"):
            current = line[len("id: "):].strip()
        elif line.startswith("name: ") and current:
            ids[line[len("name: "):].strip()] = current
            current = None
    return ids


def bump_patch(version):
    """Increment the trailing numeric component of a dotted version (4.1.255 -> 4.1.256)."""
    parts = version.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def read_prior_module(path):
    """Return (data_version, body) of a prior module, for the version-bump decision.

    body is the stanza text from the first [Term] to EOF (the header, which carries
    the version, is excluded); (None, None) when there is no prior module."""
    if not os.path.exists(path):
        return None, None
    text = open(path, encoding="utf-8").read()
    m = re.search(r"^data-version:\s*(.+)$", text, re.M)
    idx = text.find("[Term]")
    return (m.group(1).strip() if m else None), (text[idx:] if idx != -1 else None)


def assign_ids(names, existing, band):
    """Assign ids in [lo, hi]: reuse an existing id by name, else the next free id
    above the highest already used in the band (so existing ids never move)."""
    lo, hi = band
    used = [int(i.split(":")[1]) for i in existing.values()]
    used = [n for n in used if lo <= n <= hi]
    nxt = max(used) + 1 if used else lo
    result = {}
    for name in names:
        if name in existing:
            reused = int(existing[name].split(":")[1])
            if not (lo <= reused <= hi):  # e.g. a leaf label that equals a vendor name
                raise RuntimeError(
                    f"existing id {existing[name]} for {name!r} is outside band {band}"
                )
            result[name] = existing[name]
        else:
            if nxt > hi:  # fail loudly rather than mint a colliding out-of-band id
                raise RuntimeError(f"id band {band} exhausted; widen it")
            result[name] = f"MS:{nxt}"
            nxt += 1
    return result


# --- writing -----------------------------------------------------------------

def cross_check_mirror(models, labels, leaf_ids, existing):
    """Validate the catalog's psi_ms_id mirror against the ids just assigned.

    Returns rename warnings (a new model whose rows still carry a stale id) and
    raises ValueError on genuine drift so the sync aborts before opening a PR:
      - blank cell                -> new model / not yet back-propagated (ignored)
      - id matches assigned       -> mirror agrees (ignored)
      - stable term, id differs   -> drift, abort
      - rows of a model disagree  -> corrupt mirror, abort
      - new label, id differs     -> likely rename, warn (new id back-propagates)
    """
    drift, row_conflicts, renames = [], [], []
    for vp, entry in models.items():
        assigned = leaf_ids[labels[vp]]
        col_ids = set(entry["ms_ids"])
        if not col_ids:
            continue
        if len(col_ids) > 1:
            row_conflicts.append((vp[1], sorted(col_ids)))
            continue
        col_id = col_ids.pop()
        if col_id == assigned:
            continue
        (drift if labels[vp] in existing else renames).append((vp[1], col_id, assigned))
    if drift or row_conflicts:
        lines = ["psi_ms_id mirror disagrees with assigned ids (aborting sync):"]
        lines += [f"  drift: {p!r} column={c} assigned={a}" for p, c, a in drift]
        lines += [f"  conflicting ids within model {p!r}: {ids}" for p, ids in row_conflicts]
        raise ValueError("\n".join(lines))
    return renames


def build_mapping_tsv(models, labels, leaf_ids):
    """Return the (company, Column name, psi_ms_id) mapping text -- the cross-repo
    contract repo-rt joins on. Keys are the cleaned company / Column name; clean()
    drops the C0 control chars (including tab and newline), so no value can contain a
    TSV delimiter and the rows need no quoting."""
    rows = sorted(
        (vendor, product, leaf_ids[labels[(vendor, product)]]) for vendor, product in models
    )
    lines = ["company\tColumn name\tpsi_ms_id"]
    lines += [f"{c}\t{n}\t{i}" for c, n, i in rows]
    return "\n".join(lines) + "\n"


def build_columns_obo(models, existing, prior_version=None, prior_body=None):
    """Return (obo_text, mapping_text, report). Terms are emitted in id order so the
    file stays sorted and stable; report holds the data-quality summary for logs.

    The data-version is the prior module's, bumped one patch level when the term body
    changes (DATA_VERSION when there is no prior module / --reset-ids)."""
    if not models:
        raise ValueError("catalog produced 0 column models; refusing to write an empty module")
    prior_leaves = sum(1 for i in existing.values()
                       if LEAF_BAND[0] <= int(i.split(":")[1]) <= LEAF_BAND[1])
    if prior_leaves and len(models) < prior_leaves * MIN_RETAIN_FRACTION:
        raise ValueError(
            f"catalog shrank from {prior_leaves} to {len(models)} models "
            f"(<{MIN_RETAIN_FRACTION:.0%} retained); aborting as a likely truncated "
            "download. Re-run with --reset-ids if this drop is intentional."
        )

    colliding = colliding_bare_names(models)
    vendors = sorted({vendor for vendor, _ in models})

    vendor_ids = assign_ids(
        [f"{v} chromatographic column model" for v in vendors], existing, VENDOR_BAND
    )
    vendor_id = {v: vendor_ids[f"{v} chromatographic column model"] for v in vendors}

    labels = {(v, p): leaf_label(v, p, colliding) for v, p in models}
    # Each emitted leaf needs a unique label (and thus id). leaf_label only
    # disambiguates names shared ACROSS vendors, so guard against two products of
    # one vendor reducing to the same label (e.g. an upstream whitespace variant),
    # which would otherwise emit duplicate OBO terms. Fail loudly to fix upstream.
    dupes = sorted(lbl for lbl, n in Counter(labels.values()).items() if n > 1)
    if dupes:
        raise ValueError(f"non-unique leaf labels (fix in the upstream catalog): {dupes}")
    leaf_ids = assign_ids(sorted(labels.values()), existing, LEAF_BAND)

    # Defence in depth: assign_ids mints unique ids by construction, but a corrupt
    # committed OBO (two names sharing one id) would be reused faithfully. Refuse to
    # emit a duplicate-id module rather than ship one in an auto-PR.
    id_counts = Counter([PARENT_ID, *vendor_id.values(), *leaf_ids.values()])
    dup_ids = sorted(i for i, n in id_counts.items() if n > 1)
    if dup_ids:
        raise ValueError(f"duplicate ids generated (corrupt existing-id map?): {dup_ids}")

    renames = cross_check_mirror(models, labels, leaf_ids, existing)

    stanzas = [(int(PARENT_ID.split(":")[1]), parent_stanza())]
    for vendor in vendors:
        vid = vendor_id[vendor]
        stanzas.append((int(vid.split(":")[1]), vendor_stanza(vendor, vid)))

    report = {"deviations": [], "renames": renames}
    for (vendor, product), entry in models.items():
        mode, usp_literals, deviations = resolve_model(entry)
        label = labels[(vendor, product)]
        lid = leaf_ids[label]
        stanzas.append(
            (int(lid.split(":")[1]),
             leaf_stanza(lid, vendor, vendor_id[vendor], label, mode, usp_literals))
        )
        if deviations:  # rows of this model disagree on usp/mode — flag for upstream fix
            report["deviations"].append((product, deviations))

    stanzas.sort(key=lambda pair: pair[0])
    body_block = "\n\n".join(text for _, text in stanzas) + "\n"
    if prior_version and prior_body is not None:
        version = bump_patch(prior_version) if body_block != prior_body else prior_version
    else:
        version = DATA_VERSION
    obo_text = build_header(version) + "\n" + body_block
    return obo_text, build_mapping_tsv(models, labels, leaf_ids), report


def print_report(models, report):
    print(f"vendors: {len({v for v, _ in models})}   models: {len(models)}")
    if report["renames"]:
        print(f'\npsi_ms_id renames (new id minted, back-propagates next cycle) — {len(report["renames"])}:')
        for product, old, new in report["renames"]:
            print(f"  {product}  column={old} -> assigned={new}")
    if report["deviations"]:
        print(f'\nwithin-model value deviations (fix upstream) — {len(report["deviations"])}:')
        for product, dev in report["deviations"]:
            for field, counts in dev.items():
                print(f"  {product}  {field}={counts}")


def report_markdown(models, report):
    """Markdown data-quality summary for the sync PR body (deviations + renames)."""
    lines = [f"- vendors: {len({v for v, _ in models})}", f"- models: {len(models)}", ""]
    if report["deviations"]:
        lines.append(f'### Within-model value deviations (fix upstream) — {len(report["deviations"])}')
        for product, dev in report["deviations"]:
            for field, counts in dev.items():
                lines.append(f"- `{product}` — {field}={counts}")
        lines.append("")
    if report["renames"]:
        lines.append(f'### psi_ms_id renames (new id minted, back-propagates next cycle) — {len(report["renames"])}')
        for product, old, new in report["renames"]:
            lines.append(f"- `{product}` — column={old} → assigned={new}")
        lines.append("")
    if not report["deviations"] and not report["renames"]:
        lines.append("No within-model deviations or renames.")
    return "\n".join(lines).rstrip() + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", default=INPUT_DEFAULT, help="repo-rt column TSV")
    parser.add_argument("--output", default=OUTPUT_DEFAULT, help="OBO module to write")
    parser.add_argument("--mapping", default=MAPPING_DEFAULT,
                        help="company/Column name -> psi_ms_id TSV (repo-rt back-prop contract)")
    parser.add_argument("--reset-ids", action="store_true",
                        help="ignore existing ids in --output and assign clean sequential ids")
    parser.add_argument("--report", help="write a Markdown data-quality summary to this path")
    args = parser.parse_args()

    models = load_models(args.input)
    if args.reset_ids:
        existing, prior_version, prior_body = {}, None, None
    else:
        existing = read_existing_ids(args.output)  # read before we overwrite it
        prior_version, prior_body = read_prior_module(args.output)
    obo_text, mapping_text, report = build_columns_obo(
        models, existing, prior_version, prior_body
    )
    open(args.output, "w", encoding="utf-8").write(obo_text)
    print(f"wrote {args.output}")

    if os.path.dirname(args.mapping):
        os.makedirs(os.path.dirname(args.mapping), exist_ok=True)
    open(args.mapping, "w", encoding="utf-8").write(mapping_text)
    print(f"wrote {args.mapping}")

    if args.report:
        open(args.report, "w", encoding="utf-8").write(report_markdown(models, report))
        print(f"wrote {args.report}")

    print_report(models, report)


if __name__ == "__main__":
    main()
