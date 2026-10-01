"""Offline scope regressions: no bot import, credentials, network, or Notion writes."""

import json
from pathlib import Path
import unittest

from test_peptide_keywords import FILTER


class ScopeFilterTests(unittest.TestCase):
    def test_audited_paper_scope(self):
        """Replay 79 audited papers against the narrowed AI drug-design scope."""
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

    def test_ai_drug_design_and_experimental_validation_remain_in_scope(self):
        cases = [
            ("Diffusion-based therapeutic peptide design", "Candidates were validated in mice."),
            ("Boltz-2 co-folding benchmark for protein-ligand binding poses", ""),
            ("Chai-1 protein-ligand structure prediction", ""),
            ("AI antibody design", "Candidates were experimentally validated."),
        ]
        for title, abstract in cases:
            with self.subTest(title=title):
                self.assertTrue(FILTER["match_core_keywords"](title, abstract))

    def test_adjacent_methods_and_materials_are_now_excluded(self):
        cases = [
            ("Protein electron density reconstruction framework", "A neural network reconstructs cryo-EM density maps for drug discovery."),
            ("Protein ensemble refinement by integer programming", "We optimize protein conformers fitted to electron density."),
            ("AI protein design for battery-powered biosensors", "We generate proteins with a neural network."),
            ("Machine learning designs molecular materials", "We generate inhibitors for batteries using a neural network."),
            ("Computer-aided drug design for diabetes", "We use docking and molecular dynamics to screen inhibitors."),
            ("Force field training for drug-like molecules", "We develop a neural network force field."),
            ("Generative design of self-assembling therapeutic peptide hydrogels", "We develop a diffusion model for biomaterials."),
            ("Protein language models for structure prediction", "Drug discovery may benefit from these models."),
        ]
        for title, abstract in cases:
            with self.subTest(title=title):
                self.assertEqual(FILTER["match_core_keywords"](title, abstract), [])

    def test_background_ai_does_not_admit_experimental_work(self):
        cases = [
            ("Drug discovery by biochemical screening", "Machine learning is widely used in drug discovery. Here we develop an experimental assay for inhibitors."),
            ("Drug discovery by docking", "AI drug design is promising. We use molecular dynamics to select compounds."),
            ("Mechanism of a therapeutic peptide", "We use AlphaFold to predict the peptide structure and measure activity."),
            ("Online molecular docking tool", "We use ChatGPT for workflow guidance and explain docking results."),
        ]
        for title, abstract in cases:
            with self.subTest(title=title):
                self.assertEqual(FILTER["match_core_keywords"](title, abstract), [])

    def test_background_drug_mentions_do_not_admit_unrelated_ai(self):
        self.assertEqual(FILTER["match_core_keywords"](
            "Protein mechanism study",
            "Drug design is a potential application. We develop a neural network to reconstruct electron density."), [])

    def test_drug_design_evidence_can_be_in_the_abstract(self):
        self.assertTrue(FILTER["match_core_keywords"](
            "A new approach to scaffold optimization",
            "Here we develop a diffusion model for molecular generation of drug-like inhibitors."))

    def test_generic_design_requires_drug_context(self):
        for title in ("AI protein design", "Generative molecular design", "AI peptide design"):
            with self.subTest(title=title):
                self.assertEqual(FILTER["match_core_keywords"](title, ""), [])

    def test_weak_recall_terms_have_been_removed(self):
        removed = {"molecular dynamics", "binding site", "cryo-EM", "electron density",
                   "electron cloud", "density map", "X-ray crystallography", "force field",
                   "CADD", "SBDD", "FEP", "SE(3)", "E(3)", "BFN", "Chai", "Boltz"}
        self.assertTrue(removed.isdisjoint(FILTER["CORE_KEYWORDS"]))

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
