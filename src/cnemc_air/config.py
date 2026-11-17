"""YAML 配置加载 + CLI 覆盖 + 校验。

目标城市两种写法：
- 单城市（兼容旧写法）：city.name（如 北京市）或 city.code（如 110000）；
- 多城市（新）：cities 列表，每项 {name: ...} 或 {code: ...} 或纯字符串城市名。

天地图 tk / CartoDB key 三来源（优先级从高到低）：配置 viz.tianditu_tk / viz.carto_key
> key_file 的 tk= / carto= 行 > 环境变量 TIANDITU_TK / CARTO_KEY。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """配置错误（城市未指定、数值越界等）。"""


@dataclass
class FetchConfig:
    city: bool = True            # 城市级实时/24h/14d
    stations: bool = True        # 点位级实时
    station_history: bool = True  # 逐点位近 24 小时（首次/补缺，耗时随点位数增长）


@dataclass
class RequestConfig:
    qps: float = 1.0              # 每秒请求数上限
    max_retries: int = 5          # 单请求网络异常/限流最大重试次数
    retry_base_seconds: float = 1.0  # 指数退避基数
    timeout: float = 30.0         # 单次请求超时（秒）
    sleep_between_stations: float = 1.0  # 逐点位历史采集间隔（秒）
    verify: bool = True           # TLS 证书校验；极少数网络环境证书链不完整时置 false


@dataclass
class OutputsConfig:
    dir: str = "runs"
    csv: bool = True
    json: bool = True
    gpkg: bool = True   # 需 geopandas
    shp: bool = False   # 需 geopandas，老软件兼容时开启
    html: bool = True
    raw: bool = True    # 保存原始接口响应（审计/字段漂移追溯）


@dataclass
class VizConfig:
    basemap: str = "tianditu"   # tianditu | cartodb
    tianditu_tk: str = ""       # 天地图 tk；留空回退 key_file 的 tk= 行 / 环境变量 TIANDITU_TK
    carto_key: str = ""         # CartoDB 底图 key；留空则 CartoDB 瓦片带 "API key required" 水印


@dataclass
class CityTarget:
    """一个目标城市（name / code 至少填一个，code 匹配优先）。"""
    name: str | None = None
    code: str | None = None


@dataclass
class Config:
    cities: list[CityTarget]
    fetch: FetchConfig
    request: RequestConfig
    outputs: OutputsConfig
    viz: VizConfig
    raw: dict[str, Any] = field(default_factory=dict)  # 合并覆盖后的原始配置（快照用）

    # 兼容旧用法：city_name / city_code 指向首个城市
    @property
    def city_name(self) -> str | None:
        return self.cities[0].name if self.cities else None

    @property
    def city_code(self) -> str | None:
        return self.cities[0].code if self.cities else None


def _resolve_key_file(raw: dict[str, Any], config_dir: Path) -> Path | None:
    """解析 key_file：相对路径相对于配置文件所在目录解析（绝对路径原样使用）。"""
    key_file = raw.get("key_file")
    if not key_file:
        return None
    p = Path(str(key_file)).expanduser()
    if not p.is_absolute():
        p = config_dir / p
    return p if p.exists() else None


def _load_tianditu_tk(raw: dict[str, Any], config_dir: Path) -> str:
    """天地图 tk 三级来源：配置 viz.tianditu_tk > key_file 的 tk= 行 > 环境变量 TIANDITU_TK。"""
    cfg_tk = str((raw.get("viz") or {}).get("tianditu_tk") or "").strip()
    if cfg_tk:
        return cfg_tk
    p = _resolve_key_file(raw, config_dir)
    if p:
        with open(p, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.lower().startswith("tk="):
                    tk = s.split("=", 1)[1].strip()
                    if tk:
                        return tk
    return os.environ.get("TIANDITU_TK", "").strip()


def _load_carto_key(raw: dict[str, Any], config_dir: Path) -> str:
    """CartoDB 底图 key 三级来源：配置 viz.carto_key > key_file 的 carto= 行 > 环境变量 CARTO_KEY。"""
    cfg_key = str((raw.get("viz") or {}).get("carto_key") or "").strip()
    if cfg_key:
        return cfg_key
    p = _resolve_key_file(raw, config_dir)
    if p:
        with open(p, encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if s.lower().startswith("carto="):
                    k = s.split("=", 1)[1].strip()
                    if k:
                        return k
    return os.environ.get("CARTO_KEY", "").strip()


def _parse_target(item: Any) -> CityTarget | None:
    """单个城市目标：dict({name}/{code}) 或纯字符串城市名。"""
    if isinstance(item, str):
        name = item.strip() or None
        return CityTarget(name=name) if name else None
    if isinstance(item, dict):
        name = str(item.get("name") or "").strip() or None
        code = str(item.get("code") or "").strip() or None
        if not name and not code:
            return None
        return CityTarget(name=name, code=code)
    return None


def _validate_cities(raw: dict[str, Any]) -> list[CityTarget]:
    """解析目标城市列表：cities 列表优先，其次兼容旧 city 单值。"""
    raw_cities = raw.get("cities")
    if raw_cities:
        targets = [t for t in (_parse_target(x) for x in raw_cities) if t is not None]
        if targets:
            return targets
    city = raw.get("city") or {}
    name = str(city.get("name") or "").strip() or None
    code = str(city.get("code") or "").strip() or None
    if not name and not code:
        raise ConfigError(
            "未指定城市：请在配置 city.name/city.code（单城市）或 cities 列表（多城市）中填写")
    return [CityTarget(name=name, code=code)]


def load_config(path: str | Path, overrides: dict[str, Any] | None = None) -> Config:
    """加载 YAML 配置并应用 CLI 覆盖，返回校验后的 Config。"""
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}")
    config_dir = path.resolve().parent
    with open(path, encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    # ---- CLI 覆盖 ----
    ov = overrides or {}
    if ov.get("cities"):
        # CLI 传入的目标城市列表（CityTarget 或 dict），覆盖配置中的 cities/city
        raw["cities"] = [
            {"name": t.name, "code": t.code} if isinstance(t, CityTarget) else t
            for t in ov["cities"]
        ]
    if ov.get("output_dir"):
        raw.setdefault("outputs", {})["dir"] = ov["output_dir"]

    # ---- 组装与校验 ----
    cities = _validate_cities(raw)

    fc = raw.get("fetch") or {}
    fetch = FetchConfig(
        city=bool(fc.get("city", True)),
        stations=bool(fc.get("stations", True)),
        station_history=bool(fc.get("station_history", True)),
    )
    if not fetch.city and not fetch.stations:
        raise ConfigError("fetch.city 与 fetch.stations 至少开启一个")

    r = raw.get("request") or {}
    request = RequestConfig(
        qps=float(r.get("qps", 1.0)),
        max_retries=int(r.get("max_retries", 5)),
        retry_base_seconds=float(r.get("retry_base_seconds", 1.0)),
        timeout=float(r.get("timeout", 30.0)),
        sleep_between_stations=float(r.get("sleep_between_stations", 1.0)),
        verify=bool(r.get("verify", True)),
    )
    if request.qps <= 0:
        raise ConfigError("request.qps 必须为正数")
    if request.max_retries < 0:
        raise ConfigError("request.max_retries 不能为负数")

    o = raw.get("outputs") or {}
    outputs = OutputsConfig(
        dir=str(o.get("dir", "runs")),
        csv=bool(o.get("csv", True)),
        json=bool(o.get("json", True)),
        gpkg=bool(o.get("gpkg", True)),
        shp=bool(o.get("shp", False)),
        html=bool(o.get("html", True)),
        raw=bool(o.get("raw", True)),
    )

    v = raw.get("viz") or {}
    viz = VizConfig(
        basemap=str(v.get("basemap", "tianditu")),
        tianditu_tk=_load_tianditu_tk(raw, config_dir),
        carto_key=_load_carto_key(raw, config_dir),
    )
    if viz.basemap not in ("tianditu", "cartodb"):
        raise ConfigError(f"viz.basemap 仅支持 tianditu/cartodb，当前: {viz.basemap!r}")

    return Config(
        cities=cities,
        fetch=fetch, request=request, outputs=outputs, viz=viz, raw=raw,
    )
