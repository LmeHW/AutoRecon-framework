#!/usr/bin/env python3
"""Refresh archived interactive viewers to the current Chinese clinic chrome."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.vis.clinic_viewers import restyle_interactive_html


def iter_viewer_paths(root: Path) -> list[Path]:
    return sorted({path.resolve() for path in root.glob("**/*_interactive.html") if path.is_file()})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()
    paths = iter_viewer_paths(Path(args.root).resolve())
    changed = 0
    skipped = 0
    for path in paths:
        if restyle_interactive_html(path):
            changed += 1
        else:
            skipped += 1
    print(f"Restyled {changed} interactive viewer(s); {skipped} already current or unrecognized.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
