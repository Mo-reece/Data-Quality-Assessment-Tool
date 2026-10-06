// Runs the data_quality Python package inside Pyodide, off the main thread.
// Files are read in the browser and never leave the visitor's machine.

import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs";

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";
const MODULES = [
  "__init__.py", "checks.py", "config.py", "engine.py", "io.py", "report.py", "suggest.py",
];

let py = null;

async function boot() {
  py = await loadPyodide({ indexURL: PYODIDE });
  await py.loadPackage(["pandas", "micropip"]);
  py.FS.mkdirTree("/app/data_quality");
  await Promise.all(MODULES.map(async (name) => {
    const res = await fetch(`py/data_quality/${name}`);
    if (!res.ok) throw new Error(`Could not load ${name} (${res.status})`);
    py.FS.writeFile(`/app/data_quality/${name}`, await res.text());
  }));
  py.runPython(`
import sys, json
sys.path.insert(0, "/app")
import pandas as pd
from data_quality import QualityConfig, DataQualityEngine, load_table, suggest_config, __version__
from data_quality.engine import profile_columns, to_jsonable
from data_quality.report import generate_html_report

TABLES = {}

def _load(key, name, data):
    df = load_table(bytes(data), filename=name)
    TABLES[key] = df
    return json.dumps(to_jsonable({
        "rows": len(df),
        "columns": [str(c) for c in df.columns],
        "dtypes": {str(c): str(df[c].dtype) for c in df.columns},
    }))

def _suggest():
    return suggest_config(TABLES["main"]).to_json()

def _run(config_json, name, ref_keys):
    config = QualityConfig.from_json(config_json)
    refs = {k: TABLES["ref:" + k] for k in ref_keys if "ref:" + k in TABLES}
    a = DataQualityEngine(config).run(TABLES["main"], name=name, reference_dfs=refs)
    return json.dumps({"assessment": a.to_dict(), "html": generate_html_report(a)})
`);
  return py.globals.get("__version__");
}

async function ensurePackagesFor(name) {
  const ext = name.toLowerCase().split(".").pop();
  if (ext === "xlsx" || ext === "xls") {
    const micropip = py.pyimport("micropip");
    await micropip.install("openpyxl");
  } else if (ext === "parquet") {
    await py.loadPackage("pyarrow");
  }
}

function pyError(err) {
  // Show the last line of a Python traceback ("ConfigError: ...") not the whole stack.
  const text = String(err && err.message ? err.message : err);
  const lines = text.trim().split("\n").filter(Boolean);
  return lines[lines.length - 1] || text;
}

const ready = boot();
ready.catch(() => {}); // reported to the page via the "init" request

self.onmessage = async ({ data }) => {
  const { id, type, payload } = data;
  try {
    let result;
    if (type === "init") {
      result = await ready;
    } else {
      await ready;
      if (type === "load") {
        await ensurePackagesFor(payload.name);
        result = JSON.parse(py.globals.get("_load")(payload.key, payload.name, payload.bytes));
      } else if (type === "suggest") {
        result = JSON.parse(py.globals.get("_suggest")());
      } else if (type === "run") {
        const refs = py.toPy(payload.refs);
        result = JSON.parse(py.globals.get("_run")(payload.config, payload.name, refs));
        refs.destroy();
      } else {
        throw new Error(`Unknown request ${type}`);
      }
    }
    self.postMessage({ id, ok: true, result });
  } catch (err) {
    self.postMessage({ id, ok: false, error: pyError(err) });
  }
};
