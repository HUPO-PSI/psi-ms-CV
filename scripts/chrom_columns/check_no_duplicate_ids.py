#!/usr/bin/env python3
"""Fail if an OBO file contains duplicate term ids.

fastobo.load and check_sorted.py both accept duplicate ids (load does not enforce
uniqueness; check_sorted only flags strictly-decreasing ids), and the duplicate-aware
fastobo-validator is not installed on the bare-runner sync job. This stdlib-only check
closes that gap for the auto-generated psi-ms-columns.obo before it is opened in a PR.

Usage:
    python scripts/chrom_columns/check_no_duplicate_ids.py [obo_file]
"""
import sys
from collections import Counter


def duplicate_ids(path):
    ids = [line[len("id: "):].strip() for line in open(path, encoding="utf-8")
           if line.startswith("id: ")]
    return sorted(i for i, n in Counter(ids).items() if n > 1), len(ids)


def main(argv):
    path = argv[1] if len(argv) > 1 else "psi-ms-columns.obo"
    dupes, total = duplicate_ids(path)
    if dupes:
        print(f"ERROR: duplicate ids in {path}: {dupes}", file=sys.stderr)
        return 1
    print(f"{path}: {total} ids, no duplicates")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
