"""测试辅助：把 src 目录加入 sys.path，使测试无需安装即可导入包。"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
