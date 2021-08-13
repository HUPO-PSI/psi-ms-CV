import re
import sys


id_pattern = re.compile(r"^id:\s+(?P<vocabulary>[A-Za-z0-9]+):(?P<accession>\d+)\s*$")


def collect_gaps(stream, min_value=1000300):
    last_seen = dict()
    gaps = []

    for line in stream:
        line = line.strip()
        is_id = id_pattern.match(line)
        if is_id:
            cv, acc = is_id.groups()
            acc = int(acc)
            try:
                last_in_cv: int = last_seen[cv]
            except KeyError:
                last_seen[cv] = acc
                continue
            diff = acc - last_in_cv
            if diff > 1 and acc > min_value:
                for i in range(1, diff):
                    gaps.append((cv, last_in_cv + i))
                print(f"Found gap {gaps[-diff + 1]} to {gaps[-1]}")
            last_seen[cv] = acc
    return gaps, last_seen


if __name__ == "__main__":
    path = sys.argv[1]
    with open(path, 'rt') as stream:
        gaps, last_seen = collect_gaps(stream)
