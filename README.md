## HUPO-PSI mass spectrometry controlled vocabulary (psi-ms)
[![release-on-tag](https://github.com/HUPO-PSI/psi-ms-CV/actions/workflows/make-release-on-tag.yml/badge.svg)](https://github.com/HUPO-PSI/psi-ms-CV/actions/workflows/make-release-on-tag.yml)
[![OBO validation](https://github.com/HUPO-PSI/psi-ms-CV/actions/workflows/validate-obo.yml/badge.svg)](https://github.com/HUPO-PSI/psi-ms-CV/actions/workflows/validate-obo.yml)
[![Update OWL](https://github.com/HUPO-PSI/psi-ms-CV/actions/workflows/update-owl.yaml/badge.svg)](https://github.com/HUPO-PSI/psi-ms-CV/actions/workflows/update-owl.yaml)

The [Human Proteome Organization (HUPO)–Proteomics Standards Initiative (PSI)](https://psidev.info/) extensively uses ontologies and controlled vocabularies (CVs) in their data formats. The PSI-Mass Spectrometry controlled vocabulary (PSI-MS) is the main ontology from PSI that store and control all terms for MS-based proteomics experiments. It encompasses terms for a complete MS analysis pipeline, including sample labeling, digestion enzymes, instrumentation, software for peptide/protein identification and quantification, and parameters for significance determination. This CV's development involved collaboration across PSI working groups, proteomics researchers, instrument manufacturers, and software vendors. This article outlines the CV's structure, development, maintenance, and dependencies on other ontologies.

### OBO and OWL files

The main files of this repository are the OBO and OWL files: 

- **psi-ms.obo**: This file is the main source of the PSI-MS CV terms. All changes should be made in the psi-ms.obo file including addintions, changes, etc.  
- **psi-ms.owl**: This is a read-only file generate from the **psi-ms.obo** file. This file is used by multiple services including OLS, The OBO Foundry, etc. 

> The [robot.jar tool](https://github.com/ontodev/robot/) is used to convert from obo format to owl. 

### Requesting a new term

Anyone can request a new term be added to the controlled vocabulary by opening an issue or a pull
request against this repository. We'd appreciate any help you can contribute when submitting a new
term, from proposing the term name and description to defining its relationships and properties. 

### Submitting a new term 

In order to submit a new term, please `fork` or make a new `branch` of this repository. Then, **you can add your CV term in the psi-ms.obo file**. Please do not modify the owl which will be auto-generate from the obo file. Finally, you can do a Pull Request to the main repo and a member of the HUPO-PSI CV group will review and merge the PR.   

> If you're requesting multiple related terms, you can submit them in a single issue/pull request.

Please keep in mind that when you change the psi-ms.obo file you must increase the version of the file, change the data of update, and add your name to the list of contributors. 

```obo
format-version: 1.2
data-version: 4.1.155
date: 03:06:2024 13:22
saved-by: Eric Deutsch
```

### How to cite

When you use psi-ms.obo, please cite the following publication:

>Mayer G, Montecchi-Palazzi L, Ovelleiro D, Jones AR, Binz PA, Deutsch EW, Chambers M, Kallhardt M, Levander F, Shofstahl J, Orchard S, Vizcaíno JA, Hermjakob H, Stephan C, Meyer HE, Eisenacher M; HUPO-PSI Group. The HUPO proteomics standards initiative- mass spectrometry controlled vocabulary. Database (Oxford). 2013 Mar 12;2013:bat009. doi: 10.1093/database/bat009. Print 2013.  [pdf](http://database.oxfordjournals.org/content/2013/bat009.full.pdf+html)

