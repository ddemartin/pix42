"""Entry point — run with: python -m Luma  OR  python main.py [image_path]"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure package root is importable when run as a plain script
_ROOT = Path(__file__).parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    from app import LumaApp

    argv = sys.argv[:]
    open_path: Path | None = None

    # Accept an optional image path as first positional argument
    if len(argv) > 1 and not argv[1].startswith("-"):
        candidate = Path(argv.pop(1))
        if candidate.exists():
            open_path = candidate

    app = LumaApp(argv)
    return app.run(open_path)


if __name__ == "__main__":
    sys.exit(main())
