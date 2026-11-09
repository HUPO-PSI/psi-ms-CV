<!--
Edit psi-ms-core.obo, not psi-ms.obo or psi-ms.owl. Those two are generated release
artefacts: psi-ms.obo is rebuilt from psi-ms-core.obo and psi-ms-columns.obo-fragment
after merge, and CI fails any hand edit to it. The chromatographic column terms
(MS:5000000-MS:5999999) in psi-ms-columns.obo-fragment are derived from RepoRT
(https://github.com/michaelwitting/RepoRT); request column changes there rather than
editing the fragment.
-->

## Summary

## Checklist

- [ ] Changes are in `psi-ms-core.obo` (not `psi-ms.obo` or `psi-ms.owl`)
- [ ] `data-version` and `date` in `psi-ms-core.obo` are bumped, and `saved-by` names you
- [ ] Every new term has a `subset:`
- [ ] New ids are unused (`scripts/find_next_available_number.py` lists free ones)
