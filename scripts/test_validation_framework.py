import unittest

from scripts.validation_framework import (
    american_implied,
    exact_binomial_tail,
    holm_bonferroni,
    no_vig_pair,
    poisson_binomial_tail,
    validation_gate,
)


class ValidationFrameworkTests(unittest.TestCase):
    def test_devigged_minus_110_pair_is_even(self):
        self.assertAlmostEqual(american_implied(-110), 110 / 210)
        self.assertEqual(no_vig_pair(-110, -110), (0.5, 0.5))

    def test_poisson_binomial_matches_binomial_when_probabilities_match(self):
        self.assertAlmostEqual(poisson_binomial_tail([0.5] * 10, 8), exact_binomial_tail(10, 8, 0.5))

    def test_holm_preserves_original_order_and_monotonicity(self):
        adjusted = holm_bonferroni([0.04, 0.001, 0.02])
        self.assertEqual(adjusted, [0.04, 0.003, 0.04])

    def test_missing_recorded_prices_cannot_validate(self):
        gate = validation_gate(outcomes=["W"] * 20, no_vig_probabilities=None, adjusted_p=0.01, profits=[1] * 20)
        self.assertFalse(gate["passed"])
        self.assertFalse(gate["checks"]["recorded_no_vig_baseline"])


if __name__ == "__main__":
    unittest.main()
