from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

_CONFIGURED = False


def configure_pyside6_runtime() -> None:
    """Prefer PySide6's bundled Qt libraries over system Qt on Linux."""
    global _CONFIGURED
    if _CONFIGURED or not sys.platform.startswith("linux"):
        return

    try:
        import PySide6
    except ImportError:
        return

    package_dir = Path(PySide6.__file__).resolve().parent
    qt_root = package_dir / "Qt"
    qt_lib_dir = qt_root / "lib"
    if not qt_lib_dir.is_dir():
        return

    # Some container/desktop environments prepend system Qt to
    # LD_LIBRARY_PATH, which breaks PySide6 wheels that bundle a newer Qt.
    current = os.environ.get("LD_LIBRARY_PATH", "")
    parts = [str(qt_lib_dir), *[p for p in current.split(":") if p and p != str(qt_lib_dir)]]
    os.environ["LD_LIBRARY_PATH"] = ":".join(parts)

    plugin_dir = qt_root / "plugins"
    qml_dir = qt_root / "qml"
    os.environ.setdefault("QT_PLUGIN_PATH", str(plugin_dir))
    os.environ.setdefault("QML2_IMPORT_PATH", str(qml_dir))

    rtld_global = getattr(ctypes, "RTLD_GLOBAL", 0)
    for name in (
        "libQt6Core.so.6",
        "libQt6DBus.so.6",
        "libQt6Network.so.6",
        "libQt6Gui.so.6",
        "libQt6Widgets.so.6",
        "libQt6OpenGL.so.6",
        "libQt6XcbQpa.so.6",
    ):
        path = qt_lib_dir / name
        if path.exists():
            ctypes.CDLL(str(path), mode=rtld_global)

    _CONFIGURED = True
