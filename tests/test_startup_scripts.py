import pathlib
import re
import subprocess
import unittest


class StartupScriptTests(unittest.TestCase):
    def test_twin_process_pattern_is_valid_for_system_pgrep(self) -> None:
        project = pathlib.Path(__file__).resolve().parents[1]
        script = (project / "scripts" / "start-exhibition").read_text()
        patterns = re.findall(r"pgrep -f '([^']+)'", script)
        self.assertTrue(patterns)
        for pattern in patterns:
            with self.subTest(pattern=pattern):
                result = subprocess.run(
                    ["pgrep", "-f", pattern],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertIn(result.returncode, (0, 1), result.stderr)


if __name__ == "__main__":
    unittest.main()
