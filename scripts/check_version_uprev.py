import re
import hashlib
import sys

try:
    from urllib2 import urlopen, Request
except ImportError:
    from urllib.request import urlopen, Request

# Third Party Dependencies
from packaging import version

version_pattern = re.compile(r"^data-version: (\S+)")

REFERENCE_URL = "https://raw.githubusercontent.com/HUPO-PSI/psi-ms-CV/master/psi-ms.obo"


def get_checksum_and_version(stream):
    checksum = hashlib.md5()
    data_version = None

    for line in stream:
        # Remove line ending whitespace to prevent platform line endings mattering.
        checksum.update(line.decode('utf8').rstrip().encode('utf8'))
        if data_version is None:
            match = version_pattern.search(line.decode('utf8'))
            if match:
                data_version = version.parse(match.group(1))
    return checksum.hexdigest(), data_version


def main(inpath, ref_url=REFERENCE_URL):
    with open(inpath, 'rb') as fh:
        in_checksum, in_version = get_checksum_and_version(fh)
    print("Input Version: %s" % (in_version, ))
    print("Input Checksum: %s" % (in_checksum, ))

    rq = Request(ref_url, headers={
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like'
                       ' Gecko) Chrome/68.0.3440.106 Safari/537.36')
    })
    f = urlopen(rq)
    ref_checksum, ref_version = get_checksum_and_version(f)
    print("Input Version: %s" % (ref_version, ))
    print("Input Checksum: %s" % (ref_checksum, ))

    if ref_checksum != in_checksum:
        print("Checksum Mismatch, New File Updated w.r.t. Main Branch")
        if ref_version >= in_version:
            print("Ref %s >= New %s, New Version Not Greater Than Main Branch" % (ref_version, in_version))
            sys.exit(1)
        else:
            print("New Version Is Greater. Good.")
    else:
        print("No Change To psi-ms.obo w.r.t. Main Branch")
    print("All Clear")
    sys.exit(0)


if __name__ == "__main__":
    inpath = sys.argv[1]
    try:
        ref_url = sys.argv[2]
    except IndexError:
        ref_url = REFERENCE_URL
    main(inpath, ref_url)


