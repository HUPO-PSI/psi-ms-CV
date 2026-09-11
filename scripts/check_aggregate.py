#!/usr/bin/env python3
"""Fail if the spliced release OBO has unresolved references or unnamed terms.

The two source files cannot be checked for reference integrity on their own:
psi-ms-columns.obo-fragment deliberately points at core terms (MS:1004011, MS:1003921
and the separation-mode terms), so a per-file validator sees dangling ids it must
tolerate. Nothing downstream closes the gap either -- the splice is a text insertion
that cannot know a target is missing, and obo2owl then declares an unlabelled class,
so the breakage reaches the release as a term with no name rather than a failed build.

This runs against the spliced psi-ms.obo and asserts what only the merged file can
prove: every MS:/PEFF: id referenced by a term is defined in the file, and every term
carries a name. Ids in other namespaces (UO:, PATO:, NCIT:) are imported and are not
expected to be defined here.

Related but narrower: `generate_psi_ms_columns.py --check-core-refs` checks the same
cross-file targets by id *and name*, so it also catches a rename -- which resolves
fine here, leaving only the `! label` comments silently wrong.

Usage:
    python scripts/check_aggregate.py <merged.obo>
"""
import re
import sys

LOCAL_PREFIXES = ("MS:", "PEFF:")
# Clauses whose value is a bare term id, and relationship/intersection_of clauses
# where the id is the last whitespace-separated token before any trailing comment.
ID_CLAUSE = re.compile(r"^(?:is_a|union_of|disjoint_from): (\S+)")
TYPED_CLAUSE = re.compile(r"^(?:relationship|intersection_of): \S+ (\S+)")


def scan(path):
    """Return (defined ids, named ids, referenced ids) across [Term] stanzas."""
    defined, named, refs = set(), set(), set()
    in_term, current = False, None
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("[") and line.endswith("]"):
            in_term, current = line == "[Term]", None
            continue
        if not in_term:
            continue
        if line.startswith("id: "):
            current = line[4:].strip()
            defined.add(current)
        elif line.startswith("name: ") and current:
            named.add(current)
        else:
            m = ID_CLAUSE.match(line) or TYPED_CLAUSE.match(line)
            if m:
                refs.add(m.group(1))
    return defined, named, refs


def check(path):
    defined, named, refs = scan(path)
    local = {i for i in refs if i.startswith(LOCAL_PREFIXES)}
    errors = []
    unresolved = sorted(local - defined)
    if unresolved:
        errors.append(f"referenced but not defined: {unresolved[:10]}"
                      f"{' ...' if len(unresolved) > 10 else ''}")
    unnamed = sorted(defined - named)
    if unnamed:
        errors.append(f"terms without a name: {unnamed[:10]}"
                      f"{' ...' if len(unnamed) > 10 else ''}")
    return errors, len(defined), len(local)


def self_test():
    import tempfile
    good = "[Term]\nid: MS:1\nname: a\n\n[Term]\nid: MS:2\nname: b\nis_a: MS:1\n"
    bad_ref = good + "\n[Term]\nid: MS:3\nname: c\nrelationship: part_of MS:9\n"
    unnamed = good + "\n[Term]\nid: MS:4\n"
    imported = good + "\n[Term]\nid: MS:5\nname: e\nrelationship: has_units UO:7\n"
    with tempfile.TemporaryDirectory() as d:
        def run(text):
            p = f"{d}/t.obo"
            open(p, "w", encoding="utf-8").write(text)
            return check(p)[0]
        assert run(good) == [], run(good)
        assert "MS:9" in run(bad_ref)[0]
        assert "MS:4" in run(unnamed)[0]
        assert run(imported) == [], "imported UO: ids must not be required locally"
    print("self-test OK")
    return 0


def main(argv):
    if len(argv) > 1 and argv[1] == "--self-test":
        return self_test()
    if len(argv) < 2:
        print("usage: check_aggregate.py <merged.obo>", file=sys.stderr)
        return 2
    errors, terms, refs = check(argv[1])
    if errors:
        print(f"ERROR validating {argv[1]}:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1
    print(f"{argv[1]}: {terms} terms, {refs} local references, all resolved and named")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
