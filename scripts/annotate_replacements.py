#!/usr/bin/env python3
"""Add OBO replacement annotations inferred from obsolete-term comments."""

import argparse
from pathlib import Path
import re
import sys


STANZA = re.compile(r"(?=^\[(?:Term|Typedef|Instance)\]$)", re.MULTILINE)
REPLACEMENT = re.compile(r"\breplaced\s+by\b", re.IGNORECASE)
TARGET = re.compile(r"\b(?:MS|PEFF|UO|PATO):[0-9]+\b")
QUALIFIED = re.compile(r"\b(?:branch|terms under|with (?:the )?value)\b", re.IGNORECASE)

# The historical MS:1000102 comment omits a zero in the SIM accession.
CORRECTIONS = {("MS:1000102", "MS:100205"): "MS:1000205"}

# These historical targets were also pruned and have no recorded successor.
PRUNED = {("MS:1000327", "MS:1000244"), ("MS:1000364", "MS:1000342")}


def values(block, tag):
    return re.findall(rf"^{re.escape(tag)}: (.+)$", block, re.MULTILINE)


def is_obsolete(block):
    return any(value.split(" !", 1)[0] == "true" for value in values(block, "is_obsolete"))


def convert(text):
    """Return minimally edited OBO text, added links, notices and unresolved comments.

    Only explicit accessions after 'replaced by' in obsolete Term comments
    qualify. Every target must exist, be active and differ from the source.
    Branch/value-qualified suggestions use consider, not replaced_by.
    """
    blocks = STANZA.split(text)
    terms = {}
    for block in blocks:
        if not block.startswith("[Term]\n"):
            continue
        ids = values(block, "id")
        if len(ids) != 1 or ids[0] in terms:
            raise ValueError("each Term must have exactly one unique id")
        terms[ids[0]] = block

    additions, notices, unresolved = [], [], []
    for index, block in enumerate(blocks):
        if not block.startswith("[Term]\n"):
            continue
        source = values(block, "id")[0]
        planned = []
        for comment in values(block, "comment"):
            match = REPLACEMENT.search(comment)
            if not match:
                continue
            if not is_obsolete(block):
                unresolved.append((source, "replacement comment on an active term", comment))
                continue
            replacement = comment[match.end():]
            targets = list(dict.fromkeys(TARGET.findall(replacement)))
            if not targets:
                unresolved.append((source, "no explicit replacement accession", comment))
                continue
            tag = "consider" if QUALIFIED.search(replacement) else "replaced_by"
            resolved = []
            errors = []
            for target in targets:
                if (source, target) in PRUNED and target in terms and is_obsolete(terms[target]):
                    notices.append((source, f"skipped pruned target {target}; no current replacement"))
                    continue
                corrected = CORRECTIONS.get((source, target), target)
                if corrected != target:
                    notices.append((source, f"corrected {target} to {corrected}"))
                if corrected not in terms:
                    errors.append(f"unknown target {corrected}")
                elif corrected == source:
                    errors.append(f"self replacement {corrected}")
                elif is_obsolete(terms[corrected]):
                    errors.append(f"obsolete target {corrected}")
                else:
                    resolved.append((tag, corrected))
            if errors:
                unresolved.append((source, "; ".join(errors), comment))
                continue
            planned.extend(resolved)

        existing = {
            (tag, value.split()[0])
            for tag in ("replaced_by", "consider")
            for value in values(block, tag)
        }
        new = list(dict.fromkeys(link for link in planned if link not in existing))
        if new:
            # Insert before the stanza's trailing blank lines without reserializing it.
            body = block.rstrip("\n")
            ending = block[len(body):]
            blocks[index] = body + "\n" + "\n".join(
                f"{tag}: {target}" for tag, target in new
            ) + ending
            if not ending:
                blocks[index] += "\n"
            additions.extend((source, tag, target) for tag, target in new)
    return "".join(blocks), additions, notices, unresolved


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, default=Path("psi-ms-core.obo"))
    parser.add_argument(
        "--write", action="store_true",
        help="update the input file; without this flag only report proposed changes",
    )
    args = parser.parse_args()
    try:
        with args.input.open(encoding="utf-8", newline="") as handle:
            text = handle.read()
        if "\r" in text:
            raise ValueError("expected LF line endings")
        updated, additions, notices, unresolved = convert(text)
        for source, tag, target in additions:
            print(f"{source}: {tag}: {target}")
        for source, notice in notices:
            print(f"NOTICE {source}: {notice}")
        for source, reason, comment in unresolved:
            print(f"UNRESOLVED {source}: {reason}: {comment}", file=sys.stderr)
        print(f"{len(additions)} annotations to add; {len(unresolved)} unresolved comments")
        if unresolved:
            print("No file written: resolve reported comments first.", file=sys.stderr)
            return 1
        if args.write and updated != text:
            args.input.write_text(updated, encoding="utf-8")
            print(f"Wrote {args.input}")
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
