import unittest

from annotate_replacements import convert


def term(accession, comment=None, obsolete=False, annotations=""):
    text = f"[Term]\nid: {accession}\nname: test\n"
    if comment:
        text += f"comment: {comment}\n"
    if obsolete:
        text += "is_obsolete: true\n"
    return text + annotations + "\n"


class ReplacementTests(unittest.TestCase):
    def test_direct_and_idempotent(self):
        source = term("MS:1000001", "Replaced by example (MS:1000002).", True)
        text = "format-version: 1.2\n\n" + source + term("MS:1000002")
        updated, added, _, unresolved = convert(text)
        self.assertEqual(added, [("MS:1000001", "replaced_by", "MS:1000002")])
        self.assertEqual(unresolved, [])
        self.assertEqual(
            updated.replace("replaced_by: MS:1000002\n", ""), text
        )
        self.assertEqual(convert(updated)[0], updated)
        self.assertEqual(convert(updated)[1], [])

    def test_multiple_targets_and_duplicate_mentions(self):
        text = term(
            "MS:1000001",
            "Replaced by MS:1000002 and MS:1000003, also MS:1000002.", True,
        ) + term("MS:1000002") + term("MS:1000003")
        _, added, _, unresolved = convert(text)
        self.assertEqual(added, [
            ("MS:1000001", "replaced_by", "MS:1000002"),
            ("MS:1000001", "replaced_by", "MS:1000003"),
        ])
        self.assertEqual(unresolved, [])

    def test_qualified_replacements(self):
        for comment in (
            "Replaced by the terms under the 'example' (MS:1000002) branch.",
            "Should be replaced by MS:1000002 with value H2O.",
        ):
            with self.subTest(comment=comment):
                text = term("MS:1000001", comment, True) + term("MS:1000002")
                _, added, _, unresolved = convert(text)
                self.assertEqual(added, [("MS:1000001", "consider", "MS:1000002")])
                self.assertEqual(unresolved, [])

    def test_existing_annotation_with_label(self):
        text = term(
            "MS:1000001", "Replaced by MS:1000002.", True,
            "replaced_by: MS:1000002 ! example\n",
        ) + term("MS:1000002")
        self.assertEqual(convert(text)[0], text)
        self.assertEqual(convert(text)[1], [])

    def test_invalid_targets_do_not_partially_annotate(self):
        for invalid in ("MS:1000001", "MS:1000003", "MS:9999999"):
            with self.subTest(target=invalid):
                text = term(
                    "MS:1000001", f"Replaced by MS:1000002 and {invalid}.", True,
                ) + term("MS:1000002") + term("MS:1000003", obsolete=True)
                updated, added, _, unresolved = convert(text)
                self.assertEqual(updated, text)
                self.assertEqual(added, [])
                self.assertEqual(len(unresolved), 1)

    def test_no_accession_or_active_source_reported(self):
        for comment, obsolete in (
            ("Replaced by another term.", True),
            ("Replaced by MS:1000002.", False),
        ):
            with self.subTest(comment=comment):
                text = term("MS:1000001", comment, obsolete) + term("MS:1000002")
                self.assertEqual(len(convert(text)[3]), 1)

    def test_only_replacement_comments_and_term_stanzas(self):
        text = term("MS:1000001")
        text += 'def: "Intensities are replaced by their ranks." []\n\n'
        text += "[Typedef]\nid: example\ncomment: replaced by MS:1000001\n\n"
        self.assertEqual(convert(text), (text, [], [], []))

    def test_ids_before_replacement_phrase_are_not_targets(self):
        text = term(
            "MS:1000001", "MS:9999999 was replaced by MS:1000002.", True,
        ) + term("MS:1000002")
        self.assertEqual(convert(text)[1], [("MS:1000001", "replaced_by", "MS:1000002")])

    def test_historical_sim_typo_is_reported(self):
        text = term(
            "MS:1000102", "Replaced by single ion monitoring (MS:100205).", True,
        ) + term("MS:1000205")
        _, added, notices, unresolved = convert(text)
        self.assertEqual(added, [("MS:1000102", "replaced_by", "MS:1000205")])
        self.assertEqual(notices, [("MS:1000102", "corrected MS:100205 to MS:1000205")])
        self.assertEqual(unresolved, [])

    def test_duplicate_ids_rejected(self):
        with self.assertRaises(ValueError):
            convert(term("MS:1000001") + term("MS:1000001"))

    def test_pruned_historical_targets_remain_obsolete_without_links(self):
        for source, target in (
            ("MS:1000327", "MS:1000244"),
            ("MS:1000364", "MS:1000342"),
        ):
            with self.subTest(source=source):
                text = term(source, f"Replaced by {target}.", True)
                text += term(target, obsolete=True)
                updated, added, notices, unresolved = convert(text)
                self.assertEqual(updated, text)
                self.assertEqual(added, [])
                self.assertEqual(notices, [
                    (source, f"skipped pruned target {target}; no current replacement")
                ])
                self.assertEqual(unresolved, [])

    def test_final_stanza_without_newline(self):
        text = term("MS:1000002") + term(
            "MS:1000001", "Replaced by MS:1000002.", True,
        ).rstrip("\n")
        updated = convert(text)[0]
        self.assertTrue(updated.endswith("\nreplaced_by: MS:1000002\n"))


if __name__ == "__main__":
    unittest.main()
