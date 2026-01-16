import sys

import fastobo

cv = fastobo.load(sys.argv[1])

terms = list(cv)
in_order = True
last = None
conflicts = []
for i, t in enumerate(terms):
    if isinstance(t, fastobo.term.TermFrame):
        if t.id.prefix == 'NCIT':
            continue
        if last is None:
            last = t.id
        elif t.id.prefix != last.prefix:
            last = t.id
        else:
            if int(t.id.local) < int(last.local):
                conflicts.append((t.id, last, i))
                print(f"{t.id} is lower than {last}")
                in_order = False
            last = t.id

if in_order:
    print("All MS terms in order")
    sys.exit(0)
else:
    print(conflicts)
    sys.exit(1)
