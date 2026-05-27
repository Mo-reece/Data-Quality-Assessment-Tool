import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DataQualityCliPackageTest(unittest.TestCase):
    def test_cli_can_import_package_and_save_default_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "config.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "data_quality_tool.py"),
                    "--save-config",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            )
            self.assertTrue(output.exists())


if __name__ == "__main__":
    unittest.main()
