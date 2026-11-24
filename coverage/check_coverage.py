"""Coverage proof: checks the command and DXF-type tables against the code and the
last full test run, then writes coverage/REPORT.md.

    .venv/bin/python -m pytest -q          # full run writes coverage/ops_tested.json
    .venv/bin/python coverage/check_coverage.py

Exit code 1 if anything does not hold (unknown operation, untested operation, failed tests)."""

from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from cad_mcp import server  # noqa: E402,F401  (registers every tool)
from cad_mcp.core import OPS  # noqa: E402

STATUSES = {"yes": "kész", "partial": "részben", "missing": "hiányzik", "live": "élő AutoCAD kell",
            "na": "nem értelmezhető"}


def load(name: str) -> list[dict]:
    with open(HERE / name, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=";"))


def main() -> int:
    errors: list[str] = []
    all_ops = {f"{t}.{o}" for t, ops in OPS.items() for o in ops} | {"batch"}
    proof_file = HERE / "ops_tested.json"
    if not proof_file.is_file():
        print("Run the full test suite first: .venv/bin/python -m pytest -q")
        return 1
    proof = json.loads(proof_file.read_text(encoding="utf-8"))
    tested = set(proof["tested"]) | {"batch"}  # batch is tested directly in test_ops/test_mcp_stdio
    if not proof["tests_passed"]:
        errors.append("The last full test run had failures")
    if proof["untested"]:
        errors.append(f"Operations without a test: {proof['untested']}")

    tables = {"commands.csv": load("commands.csv"), "dxf_types.csv": load("dxf_types.csv")}
    referenced: set[str] = set()
    for fname, rows in tables.items():
        for r in rows:
            key = r.get("command") or r.get("type")
            st = r["status"]
            if st not in STATUSES:
                errors.append(f"{fname}: {key}: unknown status {st}")
            ops = r["mcp"].split()
            if st in ("yes", "partial") and not ops:
                errors.append(f"{fname}: {key}: status {st} but no MCP operation")
            for o in ops:
                referenced.add(o)
                if o not in all_ops:
                    errors.append(f"{fname}: {key}: unknown operation {o}")
                elif st in ("yes", "partial") and o not in tested:
                    errors.append(f"{fname}: {key}: operation {o} has no passing test")

    cmd = tables["commands.csv"]
    dxf = tables["dxf_types.csv"]
    lines = [f"# Lefedettségi jelentés ({date.today().isoformat()})", "",
             "Automatikusan készül: `coverage/check_coverage.py`. Minden „kész” vagy „részben” sor mögött "
             "létező MCP-művelet áll, amelyet a legutóbbi teljes tesztfutás le is futtatott.", ""]

    def summary(rows, title):
        c = Counter(r["status"] for r in rows)
        relevant = c["yes"] + c["partial"] + c["missing"]
        lines.append(f"## {title}")
        lines.append("")
        lines.append(f"Összesen {len(rows)} tétel.")
        lines.append("")
        lines.append("| Státusz | Darab |")
        lines.append("|---|---|")
        for k, v in STATUSES.items():
            lines.append(f"| {v} | {c[k]} |")
        if relevant:
            lines.append("")
            lines.append(f"**Fájlszinten értelmezhető tételek ({relevant} db) közül: "
                         f"{c['yes']} kész ({c['yes'] / relevant:.0%}), {c['partial']} részben "
                         f"({c['partial'] / relevant:.0%}), {c['missing']} hiányzik ({c['missing'] / relevant:.0%}).**")
        lines.append("")
        return c

    c_cmd = summary(cmd, "AutoCAD-parancsok")
    by_cat = defaultdict(Counter)
    for r in cmd:
        by_cat[r["category"]][r["status"]] += 1
    lines += ["### Kategóriánként", "", "| Kategória | kész | részben | hiányzik | élő AutoCAD | n/a |", "|---|---|---|---|---|---|"]
    for cat, c in by_cat.items():
        lines.append(f"| {cat} | {c['yes']} | {c['partial']} | {c['missing']} | {c['live']} | {c['na']} |")
    lines.append("")
    summary(dxf, "DXF elem- és objektumtípusok (Autodesk DXF-referencia, AutoCAD for Mac 2026)")

    for st, title in (("missing", "Hiányzik (fájlszinten megoldható, még nincs kész)"),
                      ("partial", "Részben kész"), ("live", "Csak élő AutoCAD-del (ObjectARX híd)")):
        lines += [f"## {title}", ""]
        for r in cmd:
            if r["status"] == st:
                lines.append(f"- **{r['command']}** ({r['category']}){': ' + r['note'] if r['note'] else ''}")
        for r in dxf:
            if r["status"] == st:
                lines.append(f"- DXF **{r['type']}**{': ' + r['note'] if r['note'] else ''}")
        lines.append("")

    extra = sorted(all_ops - referenced)
    lines += ["## Tesztelési bizonyíték", "",
              f"- MCP-műveletek száma: {proof['operations']}, ebből teszttel lefuttatva: {len(proof['tested'])}.",
              f"- Teszt nélküli művelet: {len(proof['untested'])}.",
              f"- Legutóbbi teljes tesztfutás: {'sikeres' if proof['tests_passed'] else 'HIBÁS'}.",
              f"- Táblázatban nem szereplő extra műveletek: {', '.join(extra) if extra else 'nincs'}.", ""]
    if errors:
        lines += ["## HIBÁK", ""] + [f"- {e}" for e in errors] + [""]
    (HERE / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")

    relevant = c_cmd["yes"] + c_cmd["partial"] + c_cmd["missing"]
    print(f"Commands: {len(cmd)} | yes {c_cmd['yes']}, partial {c_cmd['partial']}, missing {c_cmd['missing']}, "
          f"live {c_cmd['live']}, n/a {c_cmd['na']} | file-level done {c_cmd['yes'] / relevant:.0%}")
    print(f"Operations: {proof['operations']}, tested {len(proof['tested'])}, untested {len(proof['untested'])}")
    if errors:
        print("ERRORS:")
        for e in errors:
            print(" -", e)
        return 1
    print("OK: every listed operation exists and is exercised by a passing test. Report: coverage/REPORT.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
