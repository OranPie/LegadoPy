# LegadoPy

Python tools for working with Legado-style book sources.

## Layout

- `legado_engine/`: core parsing and fetching engine
- `legado_gui/`: desktop reader GUI package
- `cli.py`: rich CLI entrypoint
- `tui.py`: Textual terminal reader
- `examples/`: small demos
- `tests/`: ad hoc engine and JS experiments
- `scripts/`: one-off inspection helpers
- `reference/legado/`: local upstream reference clone, ignored by git

## Quick Start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python3 cli.py --help
python3 tui.py
python3 -m legado_gui
```

## GUI

`legado_gui` is a controller-first desktop reader package. It provides:

- source JSON loading
- search result browsing
- bookshelf restore and removal
- book info and chapter list visualization
- chapter content rendering with cache-backed reads via `ReaderState`
- persisted reader settings and scroll-aware resume state

The desktop UI uses `tkinter`. Package imports remain safe in headless environments, but launching `python3 -m legado_gui` requires a Python build with `tkinter` available.

On Ubuntu/Debian, install it with:

```bash
apt-get install -y python3-tk
```
