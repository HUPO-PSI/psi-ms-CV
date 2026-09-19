#!/usr/bin/env python3
"""Validate .github/repo-rt/psi-ms-column-ids.tsv (the id ledger) against the fragment.

The ledger is the sole authority for id assignment -- generate_psi_ms_columns.py reads
it before minting -- and the cross-repo contract repo-rt joins on to back-propagate
ids. Rows are append-only: a model that leaves the catalog keeps its row and its id is
never reused, so the fragment's terms are a SUBSET of the ledger, not equal to it.
Vendor terms have rows too, with an empty `column` field; vendor and retired rows can
never match a catalog row (every catalog row has a non-empty column), so they are
inert to repo-rt's join.

This checks: an exact 3-column header; every data row has three tab-separated fields;
vendor rows (empty column) carry in-band vendor ids and model rows in-band leaf ids;
ids and (company, column) keys are unique; and every term id in the fragment has a
ledger row -- an unledgered term would mean an id was minted outside the ledger.

Usage:
    python scripts/chrom_columns/check_column_mapping.py <mapping.tsv> <module.obo>
"""
import re
import sys
from collections import Counter

HEADER = "company\tcolumn\tpsi_ms_id"
# Must match generate_psi_ms_columns.py's VENDOR_BAND / LEAF_BAND and LEDGER_HEADER.
# Kept as literals so this checker stays stdlib-only (the generator needs pandas);
# if the bands or header ever change, update both files together.
VENDOR_LO, VENDOR_HI = 5000000, 5000999
LEAF_LO, LEAF_HI = 5001000, 5999999
ID_RE = re.compile(r"^MS:(\d{7})$")


def ids_in_obo(obo_path):
    """(vendor_ids, leaf_ids, errors) from every `id: MS:` line of the fragment.
    A malformed id line is reported through errors rather than crashing the run."""
    vendors, leaves, errors = set(), set(), []
    for n, line in enumerate(open(obo_path, encoding="utf-8"), start=1):
        if not line.startswith("id: MS:"):
            continue
        m = ID_RE.match(line[len("id: "):].strip())
        if not m:
            errors.append(f"{obo_path} line {n}: malformed id line {line.strip()!r}")
        elif VENDOR_LO <= int(m.group(1)) <= VENDOR_HI:
            vendors.add(m.group(0))
        elif LEAF_LO <= int(m.group(1)) <= LEAF_HI:
            leaves.add(m.group(0))
        else:
            errors.append(f"{obo_path} line {n}: id {m.group(0)} outside the vendor/leaf bands")
    return vendors, leaves, errors


def validate(mapping_path, obo_path):
    errors = []
    lines = open(mapping_path, encoding="utf-8").read().split("\n")
    if lines[0] != HEADER:
        errors.append(f"header must be {HEADER!r}, got {lines[0]!r}")
    keys, vendor_ids, leaf_ids = [], [], []
    for n, line in enumerate(lines[1:], start=2):
        if line == "":
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            errors.append(f"line {n}: expected 3 tab-separated fields, got {len(fields)}")
            continue
        company, column, ms_id = fields
        keys.append((company, column))
        lo, hi, kind, bucket = ((VENDOR_LO, VENDOR_HI, "vendor", vendor_ids) if column == ""
                                else (LEAF_LO, LEAF_HI, "leaf", leaf_ids))
        m = ID_RE.match(ms_id)
        if not m or not (lo <= int(m.group(1)) <= hi):
            errors.append(f"line {n}: psi_ms_id {ms_id!r} is not an in-band {kind} id")
        else:
            bucket.append(ms_id)
    for label, values in (("psi_ms_id", vendor_ids + leaf_ids), ("(company, column) key", keys)):
        dupes = sorted(str(v) for v, c in Counter(values).items() if c > 1)
        if dupes:
            errors.append(f"duplicate {label} values: {dupes[:10]}"
                          f"{' ...' if len(dupes) > 10 else ''}")

    obo_vendors, obo_leaves, obo_errors = ids_in_obo(obo_path)
    errors += obo_errors
    for kind, missing in (("vendor", sorted(obo_vendors - set(vendor_ids))),
                          ("leaf", sorted(obo_leaves - set(leaf_ids)))):
        if missing:
            errors.append(f"{kind} ids in {obo_path} absent from the ledger: {missing[:10]}"
                          f"{' ...' if len(missing) > 10 else ''}")
    return errors, len(keys)


def main(argv):
    if len(argv) < 3:
        print("usage: check_column_mapping.py <mapping.tsv> <module.obo>", file=sys.stderr)
        return 2
    errors, count = validate(argv[1], argv[2])
    if errors:
        print(f"ERROR validating {argv[1]}:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1
    print(f"{argv[1]}: {count} ledger rows, all valid; every id in {argv[2]} is ledgered")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
