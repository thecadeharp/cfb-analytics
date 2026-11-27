import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PostseasonNavigationTests(unittest.TestCase):
    def test_frontend_uses_named_postseason_periods(self):
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        for label in (
            "CFP First Round",
            "CFP Quarterfinals",
            "CFP Semifinals",
            "CFP National Championship",
            "Bowl Games",
        ):
            self.assertIn(label, source)
        self.assertIn("gameMatchesProjectionPeriod(game, currentWeek)", source)

    def test_postseason_registry_starts_valid_and_empty(self):
        registry = json.loads(
            (ROOT / "data" / "postseason_game_registry.json").read_text(encoding="utf-8")
        )
        self.assertEqual(registry["meta"]["season"], 2026)
        self.assertEqual(registry["games"], {})

    def test_bowl_availability_ui_is_strictly_phase_gated(self):
        source = (ROOT / "app.js").read_text(encoding="utf-8")
        self.assertIn('game?.schedule_phase !== "bowl"', source)
        self.assertIn('game?.schedule_phase === "bowl"', source)
        self.assertIn("Bowl research only · not tracked", source)
        self.assertIn("Comparison held — roster unstable", source)


if __name__ == "__main__":
    unittest.main()
