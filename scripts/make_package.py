"""Build the distributable zip: dist/cad-mcp-<version>.zip, without the virtual environment, caches,
personal configuration (mcp-config.json), editor settings and generated test drawings. Refuses to
build if a file contains the strings given with --forbid (e.g. your user name or e-mail).

    python scripts/make_package.py --forbid "$USER"
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = ["src", "assets", "scripts", "tests", "examples", "coverage", "README.md", "ATVETEL.md", "CLAUDE.md", "TELEPITES.md", "TESZTLISTA.md",
           "pyproject.toml", "install.sh", "mcp-config.example.json", ".gitignore"]
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".venv", ".claude", "teszt_csomag", "dist"}
SKIP_SUFFIX = {".pyc", ".pyo"}
TEXT_SUFFIX = {".py", ".md", ".json", ".toml", ".sh", ".csv", ".txt", ".svg", ".dxf"}


def files():
    for name in INCLUDE:
        p = ROOT / name
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and not (set(f.relative_to(ROOT).parts) & SKIP_DIRS) and f.suffix not in SKIP_SUFFIX \
                        and not f.name.endswith(".egg-info"):
                    yield f


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--forbid", action="append", default=[], help="text that must not appear in any file")
    a = ap.parse_args()
    version = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    out = ROOT / "dist" / f"cad-mcp-{version}.zip"
    out.parent.mkdir(exist_ok=True)
    found = []
    allf = list(files())
    for f in allf:
        if a.forbid and f.suffix in TEXT_SUFFIX:
            txt = f.read_text(encoding="utf-8", errors="ignore")
            found += [f"{f.relative_to(ROOT)}: {w}" for w in a.forbid if w and w in txt]
    if found:
        print("Személyes adat a fájlokban, a csomag nem készült el:\n  " + "\n  ".join(found))
        return 1
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in allf:
            arc = Path(f"cad-mcp-{version}") / f.relative_to(ROOT)
            info = zipfile.ZipInfo.from_file(f, str(arc))
            mode = 0o755 if f.suffix == ".sh" else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, f.read_bytes())
    print(f"{out} ({len(allf)} fájl, {out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
