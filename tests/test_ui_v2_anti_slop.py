"""Anti-AI-slop and V2 Obsidian Kanban UI contract verification for pulseflow-collab."""

from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestPulseFlowUiV2Contracts(unittest.TestCase):
    def test_obsidian_identity_and_safe_dom(self) -> None:
        html = (REPO_ROOT / "ui" / "index.html").read_text(encoding="utf-8")
        self.assertIn("PulseFlow", html)
        self.assertIn("Sora", html)
        self.assertIn("Manrope", html)
        self.assertIn("#090D16", html.upper())
        self.assertIn("#10B981", html.upper())
        self.assertNotIn("#F7F6F3", html.upper())
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "eval("):
            self.assertNotIn(sink, html)
        self.assertTrue((REPO_ROOT / "PRODUCT.md").is_file())
        self.assertTrue((REPO_ROOT / "DESIGN.md").is_file())


if __name__ == "__main__":
    unittest.main()
