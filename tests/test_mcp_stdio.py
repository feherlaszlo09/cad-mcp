"""End-to-end: start the real server over stdio and call it like Claude does."""

import json
import os
import sys
from pathlib import Path

import anyio

from mcp import ClientSession, StdioServerParameters, stdio_client

SRC = str(Path(__file__).resolve().parents[1] / "src")


async def _run(tmp: Path):
    env = dict(os.environ, PYTHONPATH=SRC, CAD_MCP_WORKDIR=str(tmp), CAD_MCP_ALLOW_PYTHON="1")
    params = StdioServerParameters(command=sys.executable, args=["-m", "cad_mcp"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = {t.name: t for t in (await session.list_tools()).tools}
            res = await session.call_tool("batch", {"steps": [
                {"tool": "layer", "operation": "create", "args": {"name": "WALL", "color": "red"}},
                {"tool": "draw", "operation": "rectangle", "args": {"corner1": [0, 0], "corner2": [4000, 3000], "layer": "WALL"}},
                {"tool": "edit", "operation": "offset", "args": {"handle": "$1.handles[0]", "distance": 250, "side_point": [2000, 1500]}},
            ]})
            batch = json.loads(res.content[0].text)
            img = await session.call_tool("view", {"operation": "png", "args": {"width": 400, "height": 300}})
            bad = await session.call_tool("draw", {"operation": "circle", "args": {"center": [0, 0]}})
            saved = await session.call_tool("drawing", {"operation": "save", "args": {"path": "e2e.dxf"}})
            return init, tools, batch, img, bad, json.loads(saved.content[0].text)


def test_stdio_roundtrip(tmp_path):
    init, tools, batch, img, bad, saved = anyio.run(_run, tmp_path)
    assert "CAD MCP" in (init.instructions or "")
    assert {"drawing", "draw", "edit", "query", "view", "batch", "python"} <= set(tools)
    assert "offset(" in tools["edit"].description
    assert batch["steps"] == 3 and batch["results"][2]["created"]
    assert img.content[0].type == "image" and img.content[0].mime_type == "image/png"
    assert bad.is_error and "Signature" in bad.content[0].text
    assert Path(saved["saved"]).is_file()
