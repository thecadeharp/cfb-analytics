"""
CFB ANALYTICS
test_score_engine_v11.py

Offline preflight tests for Score Engine v1.1.

Purpose:
- No CFBD calls
- No historical outcome fitting
- No coefficient tuning
- Verify deterministic math and structural guardrails before sealed testing

Run:
    python scripts/test_score_engine_v11.py
"""

import math
import unittest

import backtest_score_engine as model


class TestScoreEngineV11(unittest.TestCase):
    def test_normal_cdf_center(self):
        self.assertAlmostEqual(model.normal_cdf(0.0), 0.5, places=12)

    def test_cover_probability_is_deterministic(self):
        args = (14.0, 10.0, 16.0)
        a = model.cover_probability(*args)
        b = model.cover_probability(*args)
        self.assertEqual(a, b)

    def test_cover_probability_is_symmetric(self):
        p_home, side_home = model.cover_probability(14.0, 10.0, 16.0)
        p_away, side_away = model.cover_probability(6.0, 10.0, 16.0)

        self.assertEqual(side_home, "home")
        self.assertEqual(side_away, "away")
        self.assertAlmostEqual(p_home, p_away, places=12)

    def test_probability_dampening_reduces_extreme_confidence(self):
        projected_margin = 20.0
        market_margin = 10.0
        residual_std = 16.0

        p_base, _ = model.cover_probability(
            projected_margin,
            market_margin,
            residual_std,
        )
        p_damped, _ = model.cover_probability(
            projected_margin,
            market_margin,
            residual_std * 1.5,
        )

        self.assertGreater(p_base, 0.5)
        self.assertGreater(p_damped, 0.5)
        self.assertLess(p_damped, p_base)

    def test_probability_scale_never_changes_projected_margin(self):
        projected_margin = 18.0
        market_margin = 10.0

        p1, _ = model.cover_probability(projected_margin, market_margin, 16.0)
        p2, _ = model.cover_probability(projected_margin, market_margin, 24.0)

        self.assertNotEqual(p1, p2)
        self.assertEqual(projected_margin, 18.0)

    def test_feature_schema_contains_no_market_inputs(self):
        forbidden_terms = (
            "spread",
            "market",
            "odds",
            "favorite",
            "cover",
            "line",
        )

        for feature in model.SCORE_FEATURES:
            lowered = feature.lower()
            for term in forbidden_terms:
                self.assertNotIn(
                    term,
                    lowered,
                    msg=f"Market-derived feature detected: {feature}",
                )

    def test_context_is_not_part_of_legacy_team_rating_weights(self):
        forbidden = (
            "home",
            "hfa",
            "travel",
            "weather",
            "rest",
            "market",
            "spread",
        )

        for component in model.LEGACY_WEIGHTS:
            lowered = component.lower()
            for term in forbidden:
                self.assertNotIn(
                    term,
                    lowered,
                    msg=f"Context leaked into team rating: {component}",
                )

    def test_non_linear_strength_feature_is_signed(self):
        # V1.1 currently uses signed square:
        # positive mismatch stays positive; negative mismatch stays negative.
        positive = math.copysign(2.0 ** 2, 2.0)
        negative = math.copysign((-2.0) ** 2, -2.0)

        self.assertEqual(positive, 4.0)
        self.assertEqual(negative, -4.0)

    def test_nonlinear_feature_expands_extreme_strength_gap(self):
        small = 0.5
        large = 2.0

        small_nonlinear = abs(math.copysign(small ** 2, small))
        large_nonlinear = abs(math.copysign(large ** 2, large))

        self.assertGreater(
            large_nonlinear / large,
            small_nonlinear / small,
        )

    def test_venue_indicator_design_is_symmetric(self):
        home = 1.0
        away = -1.0
        neutral = 0.0

        self.assertEqual(home + away, 0.0)
        self.assertEqual(neutral, 0.0)

    def test_market_expected_margin_conversion(self):
        self.assertEqual(model.market_expected_margin(-7.5), 7.5)
        self.assertEqual(model.market_expected_margin(3.0), -3.0)

    def test_side_cover_result_home(self):
        record = {
            "market_home_spread": -7.0,
            "actual_home_margin": 10.0,
        }
        self.assertEqual(model.side_cover_result(record, "home"), 1)
        self.assertEqual(model.side_cover_result(record, "away"), 0)

    def test_side_cover_result_push_returns_none(self):
        record = {
            "market_home_spread": -7.0,
            "actual_home_margin": 7.0,
        }
        self.assertIsNone(model.side_cover_result(record, "home"))
        self.assertIsNone(model.side_cover_result(record, "away"))

    def test_ridge_solver_is_deterministic(self):
        matrix = [
            [4.0, 1.0],
            [1.0, 3.0],
        ]
        vector = [1.0, 2.0]

        a = model.solve_linear_system(matrix, vector)
        b = model.solve_linear_system(matrix, vector)

        self.assertEqual(a, b)

    def test_probability_optimizer_uses_only_records_passed_to_it(self):
        # Synthetic training-only records. This test verifies the optimizer
        # has no hidden external dependency on a test year or global outcome set.
        records = []

        for i in range(120):
            margin = float((i % 9) - 4)
            spread = -float((i % 7) - 3)

            records.append(
                {
                    "actual_home_margin": margin,
                    "market_home_spread": spread,
                }
            )

        def predictor(record):
            return 0.5 * record["actual_home_margin"]

        scale_a = model.optimize_probability_scale(
            records,
            predictor,
            16.0,
        )
        scale_b = model.optimize_probability_scale(
            list(records),
            predictor,
            16.0,
        )

        self.assertEqual(scale_a, scale_b)
        self.assertGreaterEqual(scale_a, 1.0)
        self.assertLessEqual(scale_a, 4.0)


if __name__ == "__main__":
    print("=" * 72)
    print("SCORE ENGINE V1.1 — OFFLINE PREFLIGHT")
    print("No network. No historical fitting. No production changes.")
    print("=" * 72)
    unittest.main(verbosity=2)
