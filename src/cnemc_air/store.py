"""run 目录管理：配置快照、原始响应、产物目录。

单城市 run 目录结构（每次运行独立子目录）：
    runs/<时间戳>_<城市>/
    ├── config.snapshot.yaml   配置快照（凭证已脱敏）
    ├── run.log                日志（由 log.attach_file_handler 写入）
    ├── raw/                   原始接口响应（审计/字段漂移追溯）
    └── outputs/               规范化 CSV / JSON / GPKG / SHP / map.html

多城市 run 目录结构（每个城市一个子目录 + 根目录汇总）：
    runs/<时间戳>_multi_<N>/
    ├── config.snapshot.yaml
    ├── run.log
    ├── progress.json          各城市状态（done/failed，续跑用）
    ├── outputs/               汇总层（全量）：csv/json/gpkg/shp + map.html
    │   ├── city_realtime.csv/.json … city_hour … city_day …
    │   ├── station_realtime.csv/.json … station_hour …
    │   ├── city.gpkg（3 图层）/ station.gpkg（2 图层）
    │   ├── city_realtime.shp …（outputs.shp: true 时）
    │   └── map.html
    ├── <城市A>/
    │   ├── raw/...
    │   └── outputs/...
    └── <城市B>/...
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("cnemc_air.store")


def sanitize_tag(text: str, max_len: int = 30) -> str:
    """把城市名等转成安全目录名片段。"""
    tag = re.sub(r"[^\w一-鿿-]+", "_", str(text)).strip("_")
    return tag[:max_len] or "run"


class RunStore:
    """单次运行的磁盘状态管理。"""

    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir)
        self.outputs_dir = self.run_dir / "outputs"
        self.raw_dir = self.run_dir / "raw"
        self.snapshot_path = self.run_dir / "config.snapshot.yaml"
        self.progress_path = self.run_dir / "progress.json"

    @classmethod
    def create(cls, root: str | Path, tag: str, config_snapshot: dict[str, Any]) -> "RunStore":
        """创建新 run 目录并写入配置快照。同一秒内重名自动追加序号。"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = Path(root) / f"{ts}_{sanitize_tag(tag)}"
        run_dir, n = base, 1
        while run_dir.exists():
            n += 1
            run_dir = Path(f"{base}_{n}")
        (run_dir / "outputs").mkdir(parents=True)
        (run_dir / "raw").mkdir(parents=True)
        store = cls(run_dir)
        with open(store.snapshot_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config_snapshot, f, allow_unicode=True, sort_keys=False)
        logger.info("run 目录: %s", run_dir)
        return store

    @classmethod
    def open(cls, run_dir: str | Path) -> "RunStore":
        """打开已存在的 run 目录（续跑用），补齐 outputs/raw 子目录。"""
        store = cls(run_dir)
        store.outputs_dir.mkdir(parents=True, exist_ok=True)
        store.raw_dir.mkdir(parents=True, exist_ok=True)
        return store

    def child(self, tag: str) -> "RunStore":
        """返回 run 目录下按城市命名的子目录 store（多城市用）。"""
        sub = RunStore(self.run_dir / sanitize_tag(tag))
        sub.outputs_dir.mkdir(parents=True, exist_ok=True)
        sub.raw_dir.mkdir(parents=True, exist_ok=True)
        return sub

    def load_progress(self) -> dict[str, str]:
        """读取 progress.json（城市名 → done/failed）；不存在返回空 dict。"""
        if self.progress_path.exists():
            with open(self.progress_path, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        return {}

    def save_progress(self, progress: dict[str, str]) -> None:
        """写入 progress.json（城市名 → done/failed）。"""
        with open(self.progress_path, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)

    def save_raw(self, name: str, obj: Any) -> Path:
        """保存一份原始接口响应（JSON，datetime 等不可序列化对象转 str）。"""
        path = self.raw_dir / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, default=str)
        return path

    def save_raw_all(self, raw: dict[str, Any]) -> None:
        for name, obj in raw.items():
            self.save_raw(name, obj)
