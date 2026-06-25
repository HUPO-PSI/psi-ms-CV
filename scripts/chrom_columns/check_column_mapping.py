#!/usr/bin/env python3
"""Validate .github/repo-rt/psi-ms-column-ids.tsv and cross-check it against the module.

The mapping is the cross-repo contract repo-rt joins on to back-propagate ids, but it is
otherwise unvalidated. This checks: an exact 3-column header; every data row has three
tab-separated fields; each psi_ms_id is an in-band MS:5xxxxxx leaf id; ids are unique;
and the mapping's id set matches the leaf-term ids in psi-ms-columns.obo exactly (so no
model is missing an id and no leaf is missing from the mapping).

Usage:
    python scripts/chrom_columns/check_column_mapping.py <mapping.tsv> <module.obo>
"""
import re
import sys
from collections import Counter

HEADER = "company\tColumn name\tpsi_ms_id"
LEAF_LO, LEAF_HI = 5001000, 5999999
ID_RE = re.compile(r"^MS:(\d{7})$")


def leaf_ids_in_obo(obo_path):
    ids = set()
    for line in open(obo_path, encoding="utf-8"):
        if line.startswith("id: MS:"):
            n = int(line[len("id: MS:"):].strip())
            if LEAF_LO <= n <= LEAF_HI:
                ids.add(f"MS:{n}")
    return ids


def validate(mapping_path, obo_path):
    errors = []
    lines = open(mapping_path, encoding="utf-8").read().split("\n")
    if not lines or lines[0] != HEADER:
        got = lines[0] if lines else None
        errors.append(f"header must be {HEADER!r}, got {got!r}")
    ids = []
    for n, line in enumerate(lines[1:], start=2):
        if line == "":
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            errors.append(f"line {n}: expected 3 tab-separated fields, got {len(fields)}")
            continue
        ms_id = fields[2]
        m = ID_RE.match(ms_id)
        if not m or not (LEAF_LO <= int(m.group(1)) <= LEAF_HI):
            errors.append(f"line {n}: psi_ms_id {ms_id!r} is not an in-band MS:5xxxxxx leaf id")
        else:
            ids.append(ms_id)
    dupes = sorted(i for i, c in Counter(ids).items() if c > 1)
    if dupes:
        errors.append(f"duplicate psi_ms_id values: {dupes}")

    mapping_set, obo_leaves = set(ids), leaf_ids_in_obo(obo_path)
    missing = sorted(mapping_set - obo_leaves)
    extra = sorted(obo_leaves - mapping_set)
    if missing:
        errors.append(f"mapping ids absent from {obo_path}: {missing[:10]}"
                      f"{' ...' if len(missing) > 10 else ''}")
    if extra:
        errors.append(f"leaf ids in {obo_path} absent from the mapping: {extra[:10]}"
                      f"{' ...' if len(extra) > 10 else ''}")
    return errors, len(ids)


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
    print(f"{argv[1]}: {count} rows, all valid and consistent with {argv[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
