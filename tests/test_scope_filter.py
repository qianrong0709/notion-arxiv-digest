"""Offline scope regressions: no bot import, credentials, network, or Notion writes."""

import json
from pathlib import Path
import unittest

from test_peptide_keywords import FILTER


class ScopeFilterTests(unittest.TestCase):
    def test_audited_paper_scope(self):
        """Protect 37 recent false positives and 42 relevant/adjacent papers."""
        fixtures = Path(__file__).with_name("scope_regression_cases.json")
        for case in json.loads(fixtures.read_text(encoding="utf-8")):
            with self.subTest(doi=case["doi"], title=case["title"]):
                admitted = (
                    not FILTER["should_skip_title"](case["title"])
                    and bool(FILTER["match_core_keywords"](case["title"], case["abstract"]))
                )
                self.assertEqual(admitted, case["keep"])

    def test_boundaries_and_model_versions(self):
        negatives = (
            ("supply chains", "Chai"),
            ("archaic lineage", "Chai"),
            ("chair-shaped scaffold", "Chai"),
            ("Boltzmann distribution", "Boltz"),
            ("intramolecular dynamics", "molecular dynamics"),
            ("current-density mapping", "density map"),
            ("BFN2", "BFN"),
            ("mesmerizing", "ESM"),
        )
        for text, keyword in negatives:
            with self.subTest(text=text, keyword=keyword):
                self.assertFalse(FILTER["keyword_hit"](text, keyword))
        positives = (
            ("Chai-1", "Chai"), ("Boltz-2", "Boltz"), ("AlphaFold3", "AlphaFold"),
            ("ESM-2", "ESM"), ("ESMFold", "ESM"), ("RFdiffusion3", "RFdiffusion"),
            ("protein–ligand", "protein-ligand"), ("density maps", "density map"),
        )
        for text, keyword in positives:
            with self.subTest(text=text, keyword=keyword):
                self.assertTrue(FILTER["keyword_hit"](text, keyword))

    def test_ai_does_not_replace_domain_or_task_evidence(self):
        cases = [
            ("Machine-learning molecular dynamics of battery electrolytes", ""),
            ("Cryo-EM structures of a ribosome", ""),
            ("Electron density in perovskites", "Deep learning predicts materials properties."),
            ("Drug discovery through a new experimental assay", "This work measures binding affinity."),
            ("Peptide probes for nanopore translocation", "We design probes and use a machine-learning classifier for clinical diagnosis."),
        ]
        for title, abstract in cases:
            with self.subTest(title=title):
                self.assertEqual(FILTER["match_core_keywords"](title, abstract), [])

    def test_validated_design_and_structural_methods_remain_in_scope(self):
        cases = [
            ("Diffusion-based peptide design", "Candidates were validated in mice."),
            ("Boltz-2 co-folding benchmark for protein-ligand binding poses", ""),
            ("Chai-1 protein-ligand structure prediction", ""),
            ("Protein electron density reconstruction framework", "A neural network reconstructs cryo-EM density maps."),
            ("Protein ensemble refinement by integer programming", "We optimize protein conformers fitted to electron density."),
            ("AI protein design for battery-powered biosensors", "We generate proteins with a neural network."),
        ]
        for title, abstract in cases:
            with self.subTest(title=title):
                self.assertTrue(FILTER["match_core_keywords"](title, abstract))

    def test_corrections_are_excluded(self):
        for title in (
            "Correction to Molecular Generation for Drug Design",
            "Correction: Protein design with RFdiffusion",
            "Erratum: AI peptide design",
        ):
            with self.subTest(title=title):
                self.assertTrue(FILTER["should_skip_title"](title))


if __name__ == "__main__":
    unittest.main()
