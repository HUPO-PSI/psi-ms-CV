<!--
Edit psi-ms-core.obo, not psi-ms.obo or psi-ms.owl. Those two are generated release
artefacts: psi-ms.obo is rebuilt from psi-ms-core.obo and psi-ms-columns.obo-fragment
after merge, and CI fails any hand edit to it. The chromatographic column terms
(MS:5000000-MS:5999999) come from RepoRT via the weekly sync; change them upstream in
RepoRT rather than in psi-ms-columns.obo-fragment.
-->

## Summary

## Checklist

- [ ] Changes are in `psi-ms-core.obo` (not `psi-ms.obo` or `psi-ms.owl`)
- [ ] `data-version` in `psi-ms-core.obo` is bumped
- [ ] Every new term has a `subset:`
- [ ] New ids are unused (`scripts/find_next_available_number.py` lists free ones)
