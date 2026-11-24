"""Switchable modules: which tools/operations are listed, switching at runtime, start-up choice."""
import json
import os
import sys
from pathlib import Path

import anyio
import pytest

from cad_mcp import modules as mods
from cad_mcp import server
from cad_mcp.core import OPS, DocumentManager

SRC = str(Path(__file__).resolve().parents[1] / "src")


def _tools(srv):
    return {t.name: t for t in anyio.run(srv.list_tools)}


def _size(tools):
    return sum(len(t.description or "") + len(json.dumps(t.input_schema)) for t in tools.values())


def test_every_operation_belongs_to_one_module():
    owned = {(t, o): mods.module_of(t, o) for t in OPS for o in OPS[t]}
    assert set(owned.values()) <= set(mods.MODULES)
    assert sum(len(mods.ops_of(m)) for m in mods.MODULES) == len(owned)
    assert mods.module_of("road", "kresz_sign") == "forgalomtechnika" and mods.module_of("road", "ditch") == "vizelvezetes"
    assert mods.module_of("road", "alignment") == "ut" and mods.module_of("edit", "move") == "alap"
    assert mods.module_of("draw", "revcloud") == "halado" and mods.module_of("survey", "traverse") == "geodezia"
    assert mods.expand("kek") == {"alap", "ut", "forgalomtechnika", "vizelvezetes", "terep", "geo"}
    assert mods.expand("geodezia,kozmu") == {"alap", "geodezia", "kozmu"} and mods.expand("") == {"alap"}
    assert mods.expand("vztel") == {"alap", "kozmu", "ut", "terep", "geo"} and not set(mods.PROFILES) & set(mods.MODULES)
    assert mods.expand(["all"]) == set(mods.MODULES)
    with pytest.raises(ValueError, match="Unknown module"):
        mods.expand("autocad")


def test_profiles_list_fewer_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "dm", DocumentManager(workdir=tmp_path))
    full = _tools(server.build_server(mods.expand("mind")))
    ut = _tools(server.build_server(mods.expand("kek")))
    minimal = _tools(server.build_server(mods.expand("minimal")))
    assert {"road", "survey", "utility", "draw3d", "modules", "batch"} <= set(full)
    assert "road" in ut and not {"survey", "utility", "draw3d"} & set(ut)
    assert not {"road", "terrain", "geo"} & set(minimal) and {"draw", "edit", "modules", "batch"} <= set(minimal)
    assert _size(minimal) < 0.45 * _size(full) and _size(ut) < 0.65 * _size(full)
    # operation level: advanced 2D commands are hidden, with a pointer to the modules tool
    enum = ut["draw"].input_schema["properties"]["operation"]["enum"]
    assert "line" in enum and "revcloud" not in enum and "halado" in ut["draw"].description
    only_ut = _tools(server.build_server({"alap", "ut"}))
    road_ops = only_ut["road"].input_schema["properties"]["operation"]["enum"]
    assert "alignment" in road_ops and "kresz_sign" not in road_ops and "ditch" not in road_ops
    assert "forgalomtechnika" in only_ut["road"].description


def test_runtime_switching_describe_and_run(monkeypatch, tmp_path, cad):
    monkeypatch.setattr(server, "dm", DocumentManager(workdir=tmp_path))
    srv = server.build_server(mods.expand("minimal"))
    assert "survey" not in _tools(srv)
    lst, changed = server.modules_op(srv, "list", {})
    assert not changed and lst["enabled"] == ["alap"] and {r["module"] for r in lst["modules"]} >= {"ut", "kozmu"}
    res, changed = server.modules_op(srv, "enable", {"modules": ["geodezia"]})
    assert changed and "survey" in res["tools"] and "survey" in _tools(srv)
    assert json.loads(Path(res["saved"]).read_text(encoding="utf-8"))["modules"] == ["alap", "geodezia"]
    res, changed = server.modules_op(srv, "set", {"profile": "kek", "persist": False})
    assert "road" in _tools(srv) and "survey" not in _tools(srv) and res["saved"] is None
    res, changed = server.modules_op(srv, "disable", {"modules": ["forgalomtechnika", "alap"], "persist": False})
    assert "alap" in res["enabled"] and "forgalomtechnika" not in res["enabled"]
    assert "kresz_list" not in _tools(srv)["road"].input_schema["properties"]["operation"]["enum"]
    d, _ = server.modules_op(srv, "describe", {"module": "kozmu"})
    assert not d["enabled"] and {x["operation"] for x in d["operations"]} >= {"sewer", "water_network"}
    # run an operation of a disabled module without enabling it
    server.execute("drawing", "new", {}, None)
    out, changed = server.modules_op(srv, "run", {"tool": "survey", "operation": "inverse",
                                                  "args": {"a": [0, 0], "b": [3, 4]}})
    assert out["distance"] == 5 and not changed
    with pytest.raises(Exception, match="run needs"):
        server.modules_op(srv, "run", {"tool": "survey", "operation": "nincs"})


def test_start_up_choice(monkeypatch, tmp_path):
    monkeypatch.delenv("CAD_MCP_MODULES", raising=False)
    assert mods.initial(tmp_path) == (set(mods.MODULES), "alapértelmezés (minden modul)")
    monkeypatch.setenv("CAD_MCP_MODULES", "geodezia")
    enabled, source = mods.initial(tmp_path)
    assert source == "CAD_MCP_MODULES" and enabled == {"alap", "geodezia"}
    mods.save(tmp_path, {"alap", "kozmu"})  # a choice saved by the modules tool wins over the starting setting
    assert mods.initial(tmp_path) == ({"alap", "kozmu"}, str(mods.settings_file(tmp_path)))


async def _stdio(tmp: Path):
    from mcp import ClientSession, StdioServerParameters, stdio_client

    env = dict(os.environ, PYTHONPATH=SRC, CAD_MCP_WORKDIR=str(tmp), CAD_MCP_MODULES="minimal")
    env.pop("CAD_MCP_ALLOW_PYTHON", None)
    seen = []

    async def handler(msg):
        seen.append(type(getattr(msg, "root", msg)).__name__)

    params = StdioServerParameters(command=sys.executable, args=["-m", "cad_mcp"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, message_handler=handler) as session:
            init = await session.initialize()
            before = {t.name for t in (await session.list_tools()).tools}
            res = await session.call_tool("modules", {"operation": "enable", "args": {"modules": ["ut"]}})
            after = {t.name for t in (await session.list_tools()).tools}
            ran = await session.call_tool("modules", {"operation": "run", "args": {
                "tool": "survey", "operation": "inverse", "args": {"a": [0, 0], "b": [6, 8]}}})
            await anyio.sleep(0.2)
            return init, before, json.loads(res.content[0].text), after, json.loads(ran.content[0].text), seen


def test_stdio_modules(tmp_path):
    init, before, res, after, ran, seen = anyio.run(_stdio, tmp_path)
    assert init.capabilities.tools is not None and init.capabilities.tools.list_changed
    assert "road" not in before and "python" not in before and {"draw", "modules", "batch"} <= before
    assert "road" in res["tools"] and "road" in after and "terrain" not in after
    assert ran["distance"] == 10
    assert any("ToolListChanged" in s for s in seen)
