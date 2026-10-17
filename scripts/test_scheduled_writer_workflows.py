import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


class ScheduledWriterWorkflowSafetyTest(unittest.TestCase):
    def test_live_score_schedule_avoids_busy_boundary_and_has_watchdog(self):
        pulse = (WORKFLOWS / "live-score-pulse.yml").read_text()
        audit = (WORKFLOWS / "data-freshness-audit.yml").read_text()
        self.assertIn('cron: "2-57/5 * * * *"', pulse)
        self.assertIn("repository_dispatch:", pulse)
        self.assertIn("types: [live-score-pulse]", pulse)
        self.assertIn("actions: write", audit)
        self.assertIn("Recover stale CFB production inputs", audit)
        self.assertIn("gh workflow run live-score-pulse.yml --ref main", audit)
        self.assertIn("gh workflow run refresh-projections-no-cfbd.yml --ref main", audit)
        self.assertIn("gh workflow run refresh-availability-reports.yml --ref main", audit)
        self.assertIn("Preserve failing audit status", audit)

    def test_projection_board_has_in_season_freshness_schedule(self):
        source = (WORKFLOWS / "refresh-projections-no-cfbd.yml").read_text()
        self.assertIn('cron: "11 0,6,12,18 * 8-12 *"', source)

    def test_scheduled_writers_are_serialized_and_checkout_current_main(self):
        dedicated_groups = {
            "live-score-pulse.yml": "thi-live-score-pulse",
            "refresh-availability-reports.yml": "thi-availability-writer",
        }
        audited = []
        problems = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            source = path.read_text()
            if not all(token in source for token in ("schedule:", "contents: write", "git push")):
                continue
            audited.append(path.name)
            group = re.search(r"concurrency:\s*\n\s*group:\s*([^\n]+)", source)
            expected_group = dedicated_groups.get(path.name, "thi-data-writer")
            if not group or group.group(1).strip() != expected_group:
                problems.append(f"{path.name}: concurrency group is not {expected_group}")

            lines = source.splitlines()
            checkout_indexes = [
                index for index, line in enumerate(lines)
                if "uses: actions/checkout@" in line
            ]
            if not checkout_indexes:
                problems.append(f"{path.name}: no checkout action")
            for index in checkout_indexes:
                block = lines[index + 1:index + 12]
                if not any(re.match(r"\s*ref:\s*main\s*$", line) for line in block):
                    problems.append(f"{path.name}: checkout does not explicitly use main")

        self.assertGreaterEqual(len(audited), 20)
        self.assertEqual(problems, [], "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
