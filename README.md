# LegadoPy

Python tools for working with Legado-style book sources.

## Layout

- `legado_engine/`: core parsing and fetching engine
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
```
