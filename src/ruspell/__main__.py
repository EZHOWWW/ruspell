"""Точка входа ``python -m ruspell`` — то же, что консольный ``ruspell-weights``."""

from __future__ import annotations

import sys

from ruspell.weights import main

if __name__ == "__main__":
    sys.exit(main())
