import re
import sys


id_pattern = re.compile(r"^id:\s+(?P<vocabulary>[A-Za-z0-9]+):(?P<accession>\d+)\s*$")


def collect_gaps(stream, min_value=1000300):
    last_seen = dict()
    gaps = []

    try:
        for i, line in enumerate(stream):
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
                if diff < 1:
                    sys.stderr.write(f"CV is not sorted! {cv}:{acc} found after {cv}:{last_in_cv}\n")
                if diff > 1 and acc > min_value:
                    for i in range(1, diff):
                        gaps.append((cv, last_in_cv + i))
                    sys.stderr.write(f"Found gap of size {diff-1}: {gaps[-diff + 1]} to {gaps[-1]}\n")
                last_seen[cv] = acc
        return gaps, last_seen
    except UnicodeDecodeError:
        print(f"Failed to decode line {i}")
        raise


if __name__ == "__main__":
    path = sys.argv[1]
    with open(path, 'rt', encoding='utf8') as stream:
        gaps, last_seen = collect_gaps(stream)

