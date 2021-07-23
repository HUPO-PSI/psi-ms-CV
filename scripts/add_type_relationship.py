'''Copy all `xref: value-type:` lines as `relationship: has_value_type`
lines.
'''

import sys

inpath = sys.argv[1]
outpath = sys.argv[2]

with open(inpath, 'rt') as infh, open(outpath, 'wt') as outfh:
    in_term = False
    has_types = []
    existing_types = []
    term_id = None
    for line in infh:
        if line.startswith("[Term]"):
            in_term = True
            has_types = []
            existing_types = []
        elif line.startswith("id:"):
            term_id = line
        elif line.startswith("relationship: has_value_type"):
            existing_types.append(line.strip())
        elif line.startswith("xref: value-type"):
            has_types.append(line)
        if not line.strip() and in_term:
            in_term = False
            if has_types:
                for val_type in has_types:
                    new = (
                        "relationship: has_value_type %s ! The allowed value-type for this CV term\n" %\
                             val_type.split("value-type:")[1].split(" \"")[0])
                    if new.strip() not in existing_types:
                        outfh.write(new)

            term_id = None
        outfh.write(line)
