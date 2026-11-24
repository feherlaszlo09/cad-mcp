"""Tool `python`: escape hatch that runs ezdxf Python code against the open
drawing, for anything the other tools do not cover. Enabled only when the
environment variable CAD_MCP_ALLOW_PYTHON=1 is set."""

from __future__ import annotations

import contextlib
import io
import math
import os
import traceback

import ezdxf
from ezdxf.math import Matrix44, Vec2, Vec3

from .core import CadError, Ctx, op

T = "python"


def enabled() -> bool:
    return os.environ.get("CAD_MCP_ALLOW_PYTHON", "0") == "1"


@op(T, "run", mutates=True)
def run(ctx: Ctx, code: str):
    """Run Python with variables doc, msp, ezdxf, Vec2, Vec3, Matrix44, math, ctx. Assign `result` to return a value; print() output is returned too."""
    if not enabled():
        raise CadError("The python tool is disabled. Set CAD_MCP_ALLOW_PYTHON=1 in the server config to enable it.")
    ns = {
        "doc": ctx.doc, "msp": ctx.msp, "ezdxf": ezdxf, "Vec2": Vec2, "Vec3": Vec3,
        "Matrix44": Matrix44, "math": math, "ctx": ctx, "result": None,
    }
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            exec(compile(code, "<cad-python>", "exec"), ns)  # noqa: S102 - opt-in by design
    except Exception:
        raise CadError("Python error:\n" + traceback.format_exc(limit=5) + "\nOutput:\n" + out.getvalue()[-4000:]) from None
    res = ns.get("result")
    try:
        import json

        json.dumps(res, default=str)
    except Exception:
        res = repr(res)
    return {"stdout": out.getvalue()[-8000:], "result": res}
