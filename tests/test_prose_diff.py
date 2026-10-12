import unittest

from prose_diff import compare


class ProseDiffTests(unittest.TestCase):
    def test_rephrased_paragraph_keeps_correspondence(self):
        left = "# Chapter One\n\nThe blue door opened quietly.\n\nShe left.\n"
        right = "# Chapter One\n\nThe green door opened quietly.\n\nA bell rang.\n\nShe left.\n"
        result = compare(left, right)
        self.assertIn((2, 2), result.alignments)
        self.assertTrue(any(span.kind == "replace" and left[span.start:span.end] == "blue"
                            for span in result.left_spans))
        self.assertTrue(any(change.kind == "insert" for change in result.changes))

    def test_markdown_filter_retains_proofreading_punctuation(self):
        self.assertEqual(compare("*italics*", "_italics_").edit_count, 0)
        self.assertGreater(compare("*italics*", "_italics_", strict_markdown=True).edit_count, 0)
        result = compare('"Wait -- now"', '”Wait — now”')
        self.assertGreater(result.edit_count, 0)
        self.assertTrue(any(span.kind == "replace" for span in result.right_spans))

    def test_whitespace_and_paragraph_spacing_option(self):
        left = "One  two.\n\nThree.\n"
        right = "One two.\nThree.\n"
        self.assertGreater(compare(left, right).edit_count, 0)
        self.assertEqual(compare(left, right, ignore_whitespace=True).edit_count, 0)

    def test_inserted_sentence_is_localized(self):
        left = "She opened the door. Then she sat down."
        right = "She opened the door. A bell rang. Then she sat down."
        result = compare(left, right)
        self.assertEqual(result.edit_count, 1)
        inserted = [right[span.start:span.end].strip() for span in result.right_spans]
        self.assertEqual(inserted, ["A bell rang."])

    def test_sentence_boundary_edit_keeps_shared_words(self):
        left = "The cat slept. The dog ran. The bird flew."
        right = "The cat slept, the dog ran. The bird flew."
        result = compare(left, right)
        self.assertEqual([left[span.start:span.end] for span in result.left_spans], [".", "The"])
        self.assertEqual([right[span.start:span.end] for span in result.right_spans], [",", "the"])

    def test_paragraph_boundary_edit_keeps_shared_words(self):
        left = "Alpha beta gamma.\n\nDelta epsilon zeta."
        right = "Alpha beta gamma. Delta epsilon zeta."
        result = compare(left, right)
        self.assertEqual([left[span.start:span.end] for span in result.left_spans], ["\n\n"])
        self.assertEqual([right[span.start:span.end] for span in result.right_spans], [" "])
        self.assertEqual(result.edit_count, 1)

    def test_many_joined_paragraphs_only_change_spacing(self):
        paragraphs = [f"Paragraph {i} has words that should remain matched." for i in range(30)]
        left = "\n\n".join(paragraphs)
        right = " ".join(paragraphs)
        result = compare(left, right)
        self.assertEqual(result.edit_count, 29)
        self.assertTrue(all(left[span.start:span.end] == "\n\n" for span in result.left_spans))
        self.assertTrue(all(right[span.start:span.end] == " " for span in result.right_spans))

    def test_repeated_paragraphs_still_have_precise_spacing_edits(self):
        paragraph = "The same words repeat in every paragraph."
        left = "\n\n".join([paragraph] * 30)
        right = " ".join([paragraph] * 30)
        result = compare(left, right)
        self.assertEqual(result.edit_count, 29)
        self.assertTrue(all(left[span.start:span.end] == "\n\n" for span in result.left_spans))
        self.assertTrue(all(right[span.start:span.end] == " " for span in result.right_spans))

    def test_reflow_and_word_edit_stay_separate(self):
        paragraph = "The same words repeat in every paragraph."
        left = "\n\n".join([paragraph] * 30)
        revised = [paragraph] * 30
        revised[15] = "The same words differ in every paragraph."
        right = " ".join(revised)
        result = compare(left, right)
        self.assertEqual(result.edit_count, 30)
        self.assertEqual([left[span.start:span.end] for span in result.left_spans
                          if left[span.start:span.end] != "\n\n"], ["repeat"])
        self.assertEqual([right[span.start:span.end] for span in result.right_spans
                          if right[span.start:span.end] != " "], ["differ"])


if __name__ == "__main__":
    unittest.main()
