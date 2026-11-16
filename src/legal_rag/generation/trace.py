"""Lưu trace JSON từ dữ liệu chạy, không nhận đối tượng client hay settings."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def write_trace(record, root="runs/traces") -> Path:
    content = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    digest = hashlib.sha256(record["query"].encode("utf-8")).hexdigest()[:12]
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    # Tạo độc quyền để mỗi lần chạy có file riêng kể cả khi đồng hồ trùng nhau.
    while True:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        path = root / f"{stamp}_{digest}.json"
        try:
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                stream.write(content)
            return path
        except FileExistsError:
            continue
