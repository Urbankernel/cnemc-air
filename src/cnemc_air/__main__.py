"""允许 `python -m cnemc_air` 方式调用（等价于 `cnemc-air` 命令）。"""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
