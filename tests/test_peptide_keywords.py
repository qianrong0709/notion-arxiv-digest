"""Offline filter tests; do not import the bot or initialize external clients."""

import ast
import html
from pathlib import Path
import re
import unittest


def load_filter():
    source = Path(__file__).resolve().parents[1] / "daily_paper.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = {
        "CORE_KEYWORDS", "COMPOUND_KEYWORD_PATTERNS", "STRICT_KEYWORDS",
        "STRICT_KEYWORDS_LOWER", "normalize_search_text", "keyword_hit",
        "match_core_keywords", "normalize_filter_text", "EXCLUDED_TITLE_PREFIXES", "should_skip_title",
        "aidd_task_label", "AI_METHOD_PATTERN", "DRUG_CONTEXT_PATTERN",
        "OUT_OF_SCOPE_TITLE_PATTERN", "CONTRIBUTION_PATTERN",
        "ADJACENT_TITLE_PATTERN",
    }
    nodes = [
        node for node in tree.body
        if (
            isinstance(node, ast.FunctionDef) and node.name in names
        ) or (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id in names
                    for target in node.targets)
        )
    ]
    namespace = {"html": html, "re": re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


FILTER = load_filter()
PEPTIDE_KEYWORD = "AI peptide design"


class PeptideKeywordTests(unittest.TestCase):
    def test_ai_peptide_design_variants(self):
        cases = [
            "AI-guided peptide design",
            "Artificial intelligence for the design of peptides",
            "Machine learning for antimicrobial peptide design",
            "Deep-learning-driven generation of cyclic peptides",
            "Generative design of cyclic peptides",
            "Generative peptide optimization",
            "Diffusion models for macrocyclic peptide generation",
            "Diffusion-based peptide design",
            "Neural-network-guided peptide design",
            "Language models optimize therapeutic peptides",
            "Large language models for peptide optimisation",
            "Reinforcement learning designs peptides with improved selectivity",
            "Neural networks generate peptides",
            "Transformer-based optimisation of peptides",
            "Flow matching for the generation of cyclic peptides",
            "AI-generated peptides",
            "Peptides designed using machine–learning",
            "DEEP LEARNING FOR PEPTIDE DESIGN",
        ]
        for title in cases:
            with self.subTest(title=title):
                self.assertIn(PEPTIDE_KEYWORD, FILTER["match_core_keywords"](
                    title, "The designed peptides are therapeutic candidates."))

    def test_title_and_abstract_are_combined(self):
        self.assertEqual(
            FILTER["match_core_keywords"](
                "Optimization of cyclic peptides",
                "A deep learning model proposes improved therapeutic sequences.",
            ),
            [PEPTIDE_KEYWORD],
        )

    def test_ordinary_peptide_biology_and_non_ai_design_are_excluded(self):
        cases = [
            "Peptide hormones regulate glucose metabolism",
            "Cyclic peptides from marine bacteria",
            "Antimicrobial peptides in innate immunity",
            "Rational design of cyclic peptides using solid-phase synthesis",
            "Optimization of peptide synthesis conditions",
            "Generation of peptides by proteolytic cleavage",
            "Peptide generation during cellular stress",
            "Design of a peptide-based hydrogel",
            "Peptide design for tissue repair",
        ]
        for title in cases:
            with self.subTest(title=title):
                self.assertEqual(FILTER["match_core_keywords"](title, ""), [])

    def test_ai_without_peptide_design_is_excluded(self):
        cases = [
            "Machine learning predicts peptide abundance",
            "AI classifies peptide spectra",
            "Deep learning identifies peptide hormones",
            "Neural networks predict peptide toxicity",
            "AI design of small materials",
            "Peptidase design using artificial intelligence",
            "Peptide design for repair of damaged tissue",
        ]
        for title in cases:
            with self.subTest(title=title):
                self.assertNotIn(PEPTIDE_KEYWORD, FILTER["match_core_keywords"](title, ""))

    def test_recall_keywords_match_complete_phrases(self):
        # The recall matcher recognizes complete phrases; admission requires context.
        for keyword in FILTER["CORE_KEYWORDS"]:
            if keyword == PEPTIDE_KEYWORD:
                continue
            with self.subTest(keyword=keyword):
                self.assertTrue(FILTER["keyword_hit"](keyword, keyword))
                # A bare keyword is a recall signal, not an admission decision.

    def test_weak_hits_do_not_admit_without_task_context(self):
        self.assertEqual(
            FILTER["match_core_keywords"]("Peptide binding affinity measurements", ""),
            [],
        )
        self.assertEqual(
            FILTER["match_core_keywords"]("Molecular dynamics of cyclic peptides", ""),
            [],
        )
        self.assertEqual(
            FILTER["match_core_keywords"]("Peptide design in a chair-shaped scaffold", ""),
            [],
        )

    def test_strict_keyword_boundaries_are_unchanged(self):
        self.assertFalse(FILTER["keyword_hit"]("mesmerizing peptides", "ESM"))
        self.assertFalse(FILTER["keyword_hit"]("BFN2", "BFN"))
        self.assertTrue(FILTER["keyword_hit"]("(ESM)", "ESM"))

    def test_compound_keyword_is_not_duplicated(self):
        self.assertEqual(
            FILTER["match_core_keywords"](
                "AI peptide design", "AI peptide design and generative peptide optimization for therapeutics"
            ),
            [PEPTIDE_KEYWORD],
        )


if __name__ == "__main__":
    unittest.main()
