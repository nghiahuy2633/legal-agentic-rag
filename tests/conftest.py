"""Cho phép các file test dùng chung dữ liệu giả của nhau giữa các thư mục con."""

import sys
from pathlib import Path

for folder in sorted(Path(__file__).parent.iterdir()):
    if folder.is_dir() and not folder.name.startswith(("_", ".")) and str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
