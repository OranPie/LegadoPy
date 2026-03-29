from .controller import ReaderController, load_source_file, load_source_text

__all__ = [
    "LegadoApp",
    "ReaderController",
    "launch_gui",
    "load_source_file",
    "load_source_text",
]


def __getattr__(name: str):
    if name in {"LegadoApp", "launch_gui"}:
        from .app_qt import LegadoApp, launch_gui

        return {"LegadoApp": LegadoApp, "launch_gui": launch_gui}[name]
    # Legacy alias – old tkinter app
    if name == "ReaderDesktopApp":
        from .app import ReaderDesktopApp
        return ReaderDesktopApp
    raise AttributeError(name)
