# CAD MCP – instructions for Claude Code

MCP server (Python, MCP SDK v2, ezdxf) that creates, edits, checks and exports AutoCAD drawings
(DXF; DWG via ODA File Converter) on macOS, mainly for Hungarian road design (KÉ-K). macOS only.
Start with `ATVETEL.md` (handover, priorities) and `TELEPITES.md` (install, live-bridge plan).

## Commands

- Tests: `PYTHONPATH=src .venv/bin/python -m pytest -q tests/` — run the full suite after every change.
- Test drawings for real AutoCAD: `.venv/bin/python scripts/make_test_pack.py --dwg` (checklist: `TESZTLISTA.md`).
- Package: `.venv/bin/python scripts/make_package.py --forbid "$USER"`.

## Architecture

- Every call goes through `src/cad_mcp/server.py` → `execute(tool, operation, args, drawing)`.
- Operations are registered with `@op("tool", "name", mutates=...)` (`src/cad_mcp/core.py`, `OPS`);
  the open drawing is an ezdxf `Drawing` in `Ctx.doc`. Modules/profiles: `src/cad_mcp/modules.py`.
- Live AutoCAD bridge (planned): new `@op("live", ...)` operations; see `TELEPITES.md`.

## Rules

- Never invent standard values (e-UT, KRESZ, MSZ). Limits come only from an official source with a
  page reference (`assets/eut`); otherwise the designer supplies them as parameters.
- No personal data (names, e-mails, machine names) in the code or package; the KRESZ fetch contact
  is read only from the `KRESZ_CONTACT` environment variable.
- Write a failing test for a reported AutoCAD bug before fixing it.
- ODA File Converter needs a desktop session: it fails inside a sandbox or over SSH; use DXF there.
- User-facing docs (README, TELEPITES, TESZTLISTA, ATVETEL) are in Hungarian.
