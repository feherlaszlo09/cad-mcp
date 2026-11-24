import json
import os
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp())

from cad_mcp import core, server  # noqa: E402
from cad_mcp.core import DocumentManager  # noqa: E402

# Every operation that runs successfully during the test session is recorded, so
# coverage/check_coverage.py can prove that each MCP operation is exercised by tests.
TESTED: set[tuple[str, str]] = set()
_original_call_op = core.call_op


def _recording_call_op(ctx, tool, operation, args):
    result = _original_call_op(ctx, tool, operation, args)
    TESTED.add((tool, operation))
    return result


server.call_op = _recording_call_op
core.call_op = _recording_call_op


def pytest_sessionfinish(session, exitstatus):
    # only a full, unfiltered run produces the proof file
    if session.config.option.keyword or session.config.option.markexpr or session.config.args != ["tests"] and \
            not all(Path(a).resolve() == Path(__file__).parent for a in session.config.args):
        return
    out = Path(__file__).resolve().parents[1] / "coverage" / "ops_tested.json"
    out.parent.mkdir(exist_ok=True)
    allops = sorted(f"{t}.{o}" for t, ops in core.OPS.items() for o in ops)
    tested = sorted(f"{t}.{o}" for t, o in TESTED)
    out.write_text(json.dumps({"tests_passed": exitstatus == 0, "operations": len(allops),
                               "tested": tested, "untested": sorted(set(allops) - set(tested))},
                              indent=1, ensure_ascii=False), encoding="utf-8")


@pytest.fixture()
def cad(tmp_path, monkeypatch):
    """Call operations like cad('draw', 'line', start=[0,0], end=[1,1])."""
    monkeypatch.setattr(server, "dm", DocumentManager(workdir=tmp_path))

    def call(tool, operation, drawing=None, **args):
        return server.execute(tool, operation, args, drawing)

    call.dm = lambda: server.dm
    call.tmp = tmp_path
    call.batch = lambda steps, **kw: json.loads(server.batch(steps, **kw))
    return call
