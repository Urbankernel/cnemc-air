"""多格式导出：CSV / JSON / GeoPackage / Shapefile（均为 WGS-84）。

- CSV：utf-8-sig，Excel 直开不乱码；缺失值写空字符串；
- JSON：规范化的记录数组（缺失值保留 null）；
- GPKG（优先）：城市级一个文件 city.gpkg（三图层 city_realtime/city_hour/city_day），
  点位级一个文件 station.gpkg（两图层 station_realtime/station_hour）；
- SHP（兼容）：每图层一个 .shp，字段名受 10 字符限制（SHP_COLUMN_MAP 映射），
  编码 UTF-8（附 .cpg）；
- 矢量属性表保留全部规范化字段（含 lon/lat 经纬度），几何取 WGS-84 的 lon/lat；
- GPKG/SHP 依赖可选包 geopandas（延迟导入），缺包时告警跳过，不影响其他产物。
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("cnemc_air.export")

_CRS_WGS84 = "EPSG:4326"

# 成果 schema（列序固定，保证 CSV/属性表稳定）
CITY_REALTIME_FIELDS = [
    "city_code", "city_name", "time_point",
    "aqi", "quality", "primary_pollutant", "measure", "unhealthful",
    "pm25", "pm10", "so2", "no2", "co", "o3",
    "co_level", "no2_level", "o3_level", "pm10_level", "pm2_5_level", "so2_level",
    "lon", "lat",
]
CITY_HOUR_FIELDS = [
    "city_code", "city_name", "time_point", "time_point_str",
    "aqi", "quality", "primary_pollutant", "measure", "unhealthful",
    "pm25", "pm10", "so2", "no2", "co", "o3",
    "lon", "lat",
]
CITY_DAY_FIELDS = [
    "city_code", "city_name", "day", "day_str",
    "aqi", "quality", "primary_pollutant", "measure", "unhealthful",
    "pm25_24h", "pm10_24h", "so2_24h", "no2_24h", "co_24h", "o3_8h_24h",
    "lon", "lat",
]
STATION_REALTIME_FIELDS = [
    "station_code", "station_name", "city_code", "city_name", "time_point",
    "aqi", "quality", "primary_pollutant", "measure", "unhealthful",
    "pm25", "pm10", "so2", "no2", "co", "o3", "o3_8h",
    "pm25_24h", "pm10_24h", "so2_24h", "no2_24h", "co_24h", "o3_24h", "o3_8h_24h",
    "co_level", "no2_level", "o3_level", "o3_8h_level", "pm10_level", "pm2_5_level", "so2_level",
    "no", "no_24h", "nox", "nox_24h",
    "lon", "lat",
]
STATION_HOUR_FIELDS = [
    "station_code", "station_name", "city_code", "city_name", "time_point", "time_point_str",
    "aqi", "quality", "primary_pollutant", "measure", "unhealthful",
    "pm25", "pm10", "so2", "no2", "co", "o3", "o3_8h",
    "pm25_24h", "pm10_24h", "so2_24h", "no2_24h", "co_24h", "o3_24h", "o3_8h_24h",
    "co_level", "no2_level", "o3_level", "o3_8h_level", "pm10_level", "pm2_5_level", "so2_level",
    "no", "no_24h", "nox", "nox_24h",
    "lon", "lat",
]

# 数值型字段（矢量导出时空值转 NaN，其余转 float）
_NUMERIC_FIELDS = {
    "aqi", "pm25", "pm10", "so2", "no2", "co", "o3", "o3_8h",
    "pm25_24h", "pm10_24h", "so2_24h", "no2_24h", "co_24h", "o3_24h", "o3_8h_24h",
    "co_level", "no2_level", "o3_level", "o3_8h_level",
    "pm10_level", "pm2_5_level", "so2_level",
    "no", "no_24h", "nox", "nox_24h",
}

# SHP 字段名 ≤10 字符：超长字段显式映射（GPKG/CSV/JSON 无此限制，保持原名）
SHP_COLUMN_MAP = {
    "station_code": "stn_code",
    "station_name": "stn_name",
    "time_point_str": "time_pts",
    "primary_pollutant": "prim_poll",
    "unhealthful": "unhealth",
    "o3_8h_level": "o3_8h_lv",
    "pm2_5_level": "pm25_lv",
}

# 数据集定义：(结果键, 字段, 分组)。分组决定 GPKG 归入 city.gpkg 还是 station.gpkg。
_DATASETS: list[tuple[str, list[str], str]] = [
    ("city_realtime", CITY_REALTIME_FIELDS, "city"),
    ("city_hour", CITY_HOUR_FIELDS, "city"),
    ("city_day", CITY_DAY_FIELDS, "city"),
    ("stations", STATION_REALTIME_FIELDS, "station"),
    ("station_hour", STATION_HOUR_FIELDS, "station"),
]
# 结果键 → 输出文件前缀
_NAME_OF = {
    "city_realtime": "city_realtime",
    "city_hour": "city_hour",
    "city_day": "city_day",
    "stations": "station_realtime",
    "station_hour": "station_hour",
}


# --------------------------------------------------------------------------- #
# 表格类
# --------------------------------------------------------------------------- #
def _as_rows(value: Any) -> list[dict]:
    """把单条 dict / list / None 统一成行列表。"""
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    return []


def merge_results(results: list[dict]) -> dict:
    """把多个城市的 result 合并为聚合 result：各数据集行拼接。

    字段 schema 不变（复用 _DATASETS/_NAME_OF），跨城市靠 city_code/city_name
    列区分归属。city_realtime 每城市 1 行，其余数据集直接 extend 拼接。
    返回的 dict 可直接交给 export_table / export_vector 按单城市方式写盘。
    """
    merged: dict[str, list[dict]] = {}
    for key, _fields, _group in _DATASETS:
        rows: list[dict] = []
        for r in results:
            rows.extend(_as_rows(r.get(key)))
        merged[key] = rows
    return merged


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in fields})


def _write_json(path: Path, fields: list[str], rows: list[dict]) -> None:
    # 按字段清单输出，保证 CSV/JSON/GPKG/SHP 四格式字段完全一致
    out = [{k: r.get(k) for k in fields} for r in rows]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


def export_table(result: dict, store, outputs_cfg) -> list[Path]:
    """导出 CSV + JSON，返回产物路径列表。"""
    outputs: list[Path] = []
    for key, fields, _group in _DATASETS:
        name = _NAME_OF[key]
        rows = _as_rows(result.get(key))
        if outputs_cfg.csv:
            p = store.outputs_dir / f"{name}.csv"
            _write_csv(p, fields, rows)
            outputs.append(p)
        if outputs_cfg.json:
            p = store.outputs_dir / f"{name}.json"
            _write_json(p, fields, rows)
            outputs.append(p)
    if outputs:
        logger.info("CSV/JSON 导出: %d 个文件", len(outputs))
    return outputs


# --------------------------------------------------------------------------- #
# 矢量类
# --------------------------------------------------------------------------- #
def _require_geopandas():
    """延迟导入 geopandas；缺包时告警并返回 None（跳过矢量导出，不中断流程）。"""
    try:
        import geopandas as gpd  # noqa: F401
        return gpd
    except ImportError:
        logger.warning("导出 GPKG/SHP 需要可选依赖 geopandas，已跳过："
                       "pip install -r requirements-optional.txt")
        return None


def _to_gdf(gpd, rows: list[dict], fields: list[str]):
    """行列表 → GeoDataFrame（Point, EPSG:4326）。缺失坐标的行跳过。

    属性：全部规范化字段（含 lon/lat 经纬度，与几何一致）；数值字段空值转 NaN，
    文本字段空值转 ''。返回 (gdf, skipped)。
    """
    import numpy as np

    attrs: list[dict] = []
    lons: list[float] = []
    lats: list[float] = []
    skipped = 0
    for r in rows:
        lon, lat = r.get("lon"), r.get("lat")
        if lon is None or lat is None:
            skipped += 1
            continue
        attr = {}
        for k in fields:
            v = r.get(k)
            if k in _NUMERIC_FIELDS or k in ("lon", "lat"):
                attr[k] = float(v) if v is not None else np.nan
            else:
                attr[k] = "" if v is None else str(v)
        attrs.append(attr)
        lons.append(float(lon))
        lats.append(float(lat))
    gdf = gpd.GeoDataFrame(attrs, geometry=gpd.points_from_xy(lons, lats), crs=_CRS_WGS84)
    return gdf, skipped


def _export_group_gpkg(gpd, result: dict, group: str, outputs_dir: Path) -> Path | None:
    """把同一分组的若干数据集写入单个 GPKG（多图层）。"""
    datasets = [(key, fields) for key, fields, g in _DATASETS if g == group]
    out = outputs_dir / f"{group}.gpkg"
    if out.exists():
        out.unlink()
    written = 0
    first = True
    for key, fields in datasets:
        rows = _as_rows(result.get(key))
        gdf, skipped = _to_gdf(gpd, rows, fields)
        if skipped:
            logger.debug("%s: %d 行缺坐标已跳过", key, skipped)
        if len(gdf) == 0:
            continue
        gdf.to_file(out, layer=_NAME_OF[key], driver="GPKG",
                    mode="w" if first else "a")
        first = False
        written += 1
    if written == 0:
        if out.exists():
            out.unlink()
        return None
    logger.info("GPKG 导出: %s（%d 个图层）", out, written)
    return out


def _export_group_shp(gpd, result: dict, group: str, outputs_dir: Path) -> list[Path]:
    """把同一分组的若干数据集各导出一个 SHP（一图层一文件）。"""
    datasets = [(key, fields) for key, fields, g in _DATASETS if g == group]
    paths: list[Path] = []
    for key, fields in datasets:
        rows = _as_rows(result.get(key))
        gdf, skipped = _to_gdf(gpd, rows, fields)
        if skipped:
            logger.debug("%s: %d 行缺坐标已跳过", key, skipped)
        if len(gdf) == 0:
            continue
        gdf = gdf.rename(columns=SHP_COLUMN_MAP)
        p = outputs_dir / f"{_NAME_OF[key]}.shp"
        gdf.to_file(p, driver="ESRI Shapefile", encoding="utf-8")
        paths.append(p)
    if paths:
        logger.info("SHP 导出: %s", ", ".join(p.name for p in paths))
    return paths


def export_vector(result: dict, store, outputs_cfg) -> list[Path]:
    """导出 GPKG + SHP，返回产物路径列表。"""
    gpd = _require_geopandas()
    if gpd is None:
        return []
    outputs: list[Path] = []
    if outputs_cfg.gpkg:
        for group in ("city", "station"):
            p = _export_group_gpkg(gpd, result, group, store.outputs_dir)
            if p is not None:
                outputs.append(p)
    if outputs_cfg.shp:
        for group in ("city", "station"):
            outputs.extend(_export_group_shp(gpd, result, group, store.outputs_dir))
    return outputs
