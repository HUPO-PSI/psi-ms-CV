#!/usr/bin/env python3
"""Splice psi-ms-columns.obo-fragment into psi-ms-core.obo to build psi-ms.obo.

Usage:
    python scripts/build_release_obo.py [--core psi-ms-core.obo]
        [--fragment psi-ms-columns.obo-fragment] [--output psi-ms.obo]
"""

import argparse
import re
import sys

CORE_DEFAULT = "psi-ms-core.obo"
FRAGMENT_DEFAULT = "psi-ms-columns.obo-fragment"
OUTPUT_DEFAULT = "psi-ms.obo"

MS_ID_LINE = re.compile(r"^id: MS:\S+$", re.M)


def check_fragment(fragment_text, fragment_path):
    """The fragment must be stanzas only. A header clause here would land mid-file and
    every OBO parser would reject the result ('expected EOI, Comment, or TermClause')."""
    blocks = [b for b in fragment_text.split("\n\n") if b.strip()]
    if not blocks:
        raise ValueError(f"{fragment_path} is empty")
    for block in blocks:
        if not block.lstrip("\n").startswith("["):
            first = block.lstrip("\n").splitlines()[0]
            raise ValueError(
                f"{fragment_path} must contain stanzas only, found a header clause: {first!r}"
            )
    return len(blocks)


def splice(core_text, fragment_text):
    """Insert the fragment after the last stanza of core's MS: block."""
    last = None
    for last in MS_ID_LINE.finditer(core_text):
        pass
    if last is None:
        raise ValueError("no 'id: MS:...' stanza found in core; cannot locate the seam")

    body = fragment_text.strip("\n")
    end = core_text.find("\n\n", last.end())
    if end == -1:                                   # MS block runs to end of file
        return core_text.rstrip("\n") + "\n\n" + body + "\n"
    return core_text[:end + 1] + "\n" + body + "\n" + core_text[end + 1:]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--core", default=CORE_DEFAULT)
    parser.add_argument("--fragment", default=FRAGMENT_DEFAULT)
    parser.add_argument("--output", default=OUTPUT_DEFAULT)
    args = parser.parse_args()

    core_text = open(args.core, encoding="utf-8").read()
    fragment_text = open(args.fragment, encoding="utf-8").read()

    n_stanzas = check_fragment(fragment_text, args.fragment)
    merged = splice(core_text, fragment_text)
    open(args.output, "w", encoding="utf-8").write(merged)

    print(f"wrote {args.output}: {args.core} + {n_stanzas} stanzas from {args.fragment} "
          f"({merged.count('[Term]')} terms)")


if __name__ == "__main__":
    sys.exit(main())
