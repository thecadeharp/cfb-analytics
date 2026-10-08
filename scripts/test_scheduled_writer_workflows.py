import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


class ScheduledWriterWorkflowSafetyTest(unittest.TestCase):
    def test_scheduled_writers_are_serialized_and_checkout_current_main(self):
        audited = []
        problems = []
        for path in sorted(WORKFLOWS.glob("*.yml")):
            source = path.read_text()
            if not all(token in source for token in ("schedule:", "contents: write", "git push")):
                continue
            audited.append(path.name)
            group = re.search(r"concurrency:\s*\n\s*group:\s*([^\n]+)", source)
            if not group or group.group(1).strip() != "thi-data-writer":
                problems.append(f"{path.name}: concurrency group is not thi-data-writer")

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
