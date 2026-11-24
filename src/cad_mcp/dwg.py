"""DWG support through the free ODA File Converter (ezdxf.addons.odafc)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import ezdxf
from ezdxf.document import Drawing

from .core import CadError

CANDIDATES = [
    "/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter",
    str(Path.home() / "Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter"),
    "/usr/bin/ODAFileConverter",
    "/usr/local/bin/ODAFileConverter",
]

DWG_VERSIONS = ["R12", "R2000", "R2004", "R2007", "R2010", "R2013", "R2018"]

INSTALL_HINT = (
    "DWG needs the free ODA File Converter. Install it from "
    "https://www.opendesign.com/guestfiles/oda_file_converter (macOS .dmg, drag to Applications), "
    "or set CAD_MCP_ODA_PATH to its executable. "
    "Until then use DXF: AutoCAD opens and saves DXF without loss for normal drawings."
)


def oda_path() -> str | None:
    env = os.environ.get("CAD_MCP_ODA_PATH")
    if env and Path(env).is_file():
        return env
    for c in CANDIDATES:
        if Path(c).is_file():
            return c
    return shutil.which("ODAFileConverter")


def _configure() -> None:
    path = oda_path()
    if not path:
        raise CadError(INSTALL_HINT)
    ezdxf.options.set("odafc-addon", "unix_exec_path", path)


NO_SCREEN = (
    "ODA File Converter is a desktop app and needs a logged-in desktop session; it cannot run "
    "in a sandbox or over plain SSH. Save as .dxf instead, or run the server in your session."
)


def _explain(exc: Exception) -> str:
    msg = str(exc)
    if "no screens available" in msg:
        return NO_SCREEN
    return msg[:1500]


def read_dwg(path: Path) -> Drawing:
    _configure()
    from ezdxf.addons import odafc

    try:
        return odafc.readfile(str(path))
    except Exception as exc:  # pragma: no cover - depends on external tool
        raise CadError(f"ODA File Converter could not read {path}: {_explain(exc)}") from exc


def write_dwg(doc: Drawing, path: Path, version: str = "R2018") -> None:
    if version not in DWG_VERSIONS:
        raise CadError(f"DWG version must be one of {DWG_VERSIONS}")
    _configure()
    from ezdxf.addons import odafc

    try:
        odafc.export_dwg(doc, str(path), version=version, replace=True)
    except Exception as exc:  # pragma: no cover - depends on external tool
        raise CadError(f"ODA File Converter could not write {path}: {_explain(exc)}") from exc
