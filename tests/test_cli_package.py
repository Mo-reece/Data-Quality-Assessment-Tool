import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "data_quality", *args], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8", check=False)


class CliTest(unittest.TestCase):
    def test_legacy_script_saves_default_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "config.json"
            r = subprocess.run([sys.executable, str(ROOT / "data_quality_tool.py"), "--save-config", str(out)],
                               cwd=ROOT, capture_output=True, text=True, check=False)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(out.exists())

    def test_full_run_writes_reports_and_gate_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            html, js = Path(tmp) / "r.html", Path(tmp) / "r.json"
            r = run(str(EXAMPLES / "orders.csv"), "-c", str(EXAMPLES / "orders_rules.json"),
                    "--ref", f"customers={EXAMPLES / 'customers.csv'}",
                    "-o", str(html), "--json", str(js), "--fail-under", "0.99", "-q")
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("Quality gate failed", r.stderr)
            data = json.loads(js.read_text(encoding="utf-8"))
            self.assertEqual(data["summary"]["rows"], 1025)
            self.assertFalse(next(x for x in data["results"] if x["name"] == "referential_integrity")["skipped"])
            self.assertIn("<html", html.read_text(encoding="utf-8"))

    def test_json_to_stdout_is_pure_json(self):
        r = run(str(EXAMPLES / "customers.csv"), "--json", "-", "--no-html")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["summary"]["rows"], 200)

    def test_bad_input_gives_clean_error(self):
        r = run("does-not-exist.csv")
        self.assertEqual(r.returncode, 1)
        self.assertIn("Error:", r.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text('{"oops": 1}')
            r = run(str(EXAMPLES / "customers.csv"), "-c", str(bad), "--no-html")
            self.assertEqual(r.returncode, 1)
            self.assertIn("Unknown config key", r.stderr)


class LoaderTest(unittest.TestCase):
    def test_semicolon_csv_and_bytes(self):
        from data_quality import load_table
        df = load_table("a;b\n1;2\n3;4\n".encode("cp1252"), filename="x.csv")
        self.assertEqual(list(df.columns), ["a", "b"])
        with self.assertRaises(ValueError):
            load_table(b"", filename="x.docx")


if __name__ == "__main__":
    unittest.main()
