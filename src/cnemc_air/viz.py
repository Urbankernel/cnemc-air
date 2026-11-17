"""folium 交互地图：天地图默认底图，导出自包含 HTML。

图层（均可开关）：
- 底图：CartoDB Positron（缺省/备用）| 天地图矢量 | 天地图影像（有 tk 时）
- 叠加：天地图矢量注记 | 天地图影像注记（有 tk 时）
- 城市中心点（AQI 配色，大圆点）
- 点位（AQI 配色，popup 显示完整指标）

AQI 配色遵循 HJ 633-2012 国标（优/良/轻度/中度/重度/严重污染），为语义色，
不随底图明暗切换；图层均加中性描边保证在浅色/深色底图上均可读。

天地图 tk 属个人凭证：从配置或环境变量 TIANDITU_TK 读取，不进 git。
无 tk 时降级 CartoDB Positron 并告警。folium 延迟导入，核心流水线不依赖本模块。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from .normalize import AQI_LEVELS, aqi_level

logger = logging.getLogger("cnemc_air.viz")

TIANDITU_TEMPLATES = {
    "vec": ("天地图矢量", "https://t{s}.tianditu.gov.cn/DataServer?T=vec_w&x={x}&y={y}&l={z}&tk={tk}"),
    "cva": ("天地图矢量注记", "https://t{s}.tianditu.gov.cn/DataServer?T=cva_w&x={x}&y={y}&l={z}&tk={tk}"),
    "img": ("天地图影像", "https://t{s}.tianditu.gov.cn/DataServer?T=img_w&x={x}&y={y}&l={z}&tk={tk}"),
    "cia": ("天地图影像注记", "https://t{s}.tianditu.gov.cn/DataServer?T=cia_w&x={x}&y={y}&l={z}&tk={tk}"),
}

# 城市 / 点位标记描边（中性深灰，保证浅色/深色底图下 AQI 填充色均可读）
CITY_STYLE = {"color": "#111111", "weight": 2, "opacity": 1.0, "fill_opacity": 0.9, "radius": 12}
STATION_STYLE = {"color": "#333333", "weight": 1, "opacity": 1.0, "fill_opacity": 0.8, "radius": 6}


def _tianditu_tile_urls(tk: str, layer: str = "vec") -> list[tuple[str, str]]:
    """天地图 XYZ 瓦片地址。layer: vec（矢量+矢量注记）| img（影像+影像注记）。"""
    keys = ("vec", "cva") if layer == "vec" else ("img", "cia")
    return [
        (TIANDITU_TEMPLATES[k][0],
         TIANDITU_TEMPLATES[k][1].format(tk=tk, s="{s}", x="{x}", y="{y}", z="{z}"))
        for k in keys
    ]


def _add_basemaps(m, *, basemap: str = "tianditu", tk: str = "", carto_key: str = "") -> None:
    """给 folium 地图添加底图：CartoDB 备用 + 天地图（有 tk 时）。"""
    import folium

    tianditu_ok = basemap == "tianditu" and bool(tk)
    if basemap == "tianditu" and not tk:
        logger.warning("未提供天地图 tk（viz.tianditu_tk 或环境变量 TIANDITU_TK），"
                       "底图降级为 CartoDB Positron")

    carto_url = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"
    if carto_key:
        carto_url += f"?key={carto_key}"
    else:
        logger.warning("未提供 CartoDB key（viz.carto_key / 环境变量 CARTO_KEY），"
                       "CartoDB 底图将带 \"API key required\" 水印；"
                       "可到 https://carto.com/basemaps/apikey/ 免费申请")

    folium.TileLayer(
        tiles=carto_url,
        name="CartoDB Positron",
        attr="© OpenStreetMap contributors © CARTO",
        subdomains="abcd",
        show=not tianditu_ok, overlay=False, control=True,
    ).add_to(m)

    if tianditu_ok:
        # 天地图子域为 t0-t7，必须显式指定 subdomains（folium 默认 abc 会解析失败）
        vec_url, cva_url = _tianditu_tile_urls(tk, layer="vec")
        img_url, cia_url = _tianditu_tile_urls(tk, layer="img")
        folium.TileLayer(tiles=vec_url[1], name=vec_url[0], attr="天地图",
                         subdomains="01234567", show=True, overlay=False, control=True).add_to(m)
        folium.TileLayer(tiles=img_url[1], name=img_url[0], attr="天地图",
                         subdomains="01234567", show=False, overlay=False, control=True).add_to(m)
        folium.TileLayer(tiles=cva_url[1], name=cva_url[0], attr="天地图",
                         subdomains="01234567", show=True, overlay=True, control=True).add_to(m)
        folium.TileLayer(tiles=cia_url[1], name=cia_url[0], attr="天地图",
                         subdomains="01234567", show=False, overlay=True, control=True).add_to(m)


def _fmt_num(v) -> str:
    return "" if v is None else str(v)


def _city_popup(meta: dict, rt: dict | None) -> str:
    rows = [
        f"<b>{meta.get('city_name', '')}</b>（{meta.get('city_code', '')}）",
        "—— 城市实时 ——",
        f"AQI：{_fmt_num((rt or {}).get('aqi'))}　{_fmt_num((rt or {}).get('quality'))}",
        f"PM2.5：{_fmt_num((rt or {}).get('pm25'))}　PM10：{_fmt_num((rt or {}).get('pm10'))}",
        f"SO₂：{_fmt_num((rt or {}).get('so2'))}　NO₂：{_fmt_num((rt or {}).get('no2'))}",
        f"CO：{_fmt_num((rt or {}).get('co'))}　O₃：{_fmt_num((rt or {}).get('o3'))}",
    ]
    if (rt or {}).get("primary_pollutant"):
        rows.append(f"首要污染物：{rt.get('primary_pollutant')}")
    if (rt or {}).get("time_point"):
        rows.append(f"时间：{rt.get('time_point')}")
    return "<br>".join(rows)


def _station_popup(row: dict) -> str:
    rows = [
        f"<b>{row.get('station_name', '')}</b>（{row.get('station_code', '')}）",
        f"AQI：{_fmt_num(row.get('aqi'))}　{_fmt_num(row.get('quality'))}",
        f"PM2.5：{_fmt_num(row.get('pm25'))}　PM10：{_fmt_num(row.get('pm10'))}",
        f"SO₂：{_fmt_num(row.get('so2'))}　NO₂：{_fmt_num(row.get('no2'))}",
        f"CO：{_fmt_num(row.get('co'))}　O₃：{_fmt_num(row.get('o3'))}",
    ]
    if row.get("o3_8h") is not None:
        rows.append(f"O₃-8h：{_fmt_num(row.get('o3_8h'))}")
    if row.get("primary_pollutant"):
        rows.append(f"首要污染物：{row.get('primary_pollutant')}")
    if row.get("time_point"):
        rows.append(f"时间：{row.get('time_point')}")
    return "<br>".join(rows)


def _legend_html() -> str:
    items = []
    ranges = [f"{lo}~{hi}" for lo, hi, _l, _c in AQI_LEVELS]
    ranges[-1] = f">{AQI_LEVELS[-2][1]}"  # 最后一档显示 >300
    for (lo, hi, label, color), rng in zip(AQI_LEVELS, ranges):
        items.append(
            '<label style="display:flex;align-items:center;margin:1px 0;">'
            f'<span style="width:12px;height:12px;background:{color};border:1px solid #999;'
            f'border-radius:2px;margin-right:6px;display:inline-block;"></span>'
            f'<span>{label}（{rng}）</span></label>'
        )
    return (
        '<div style="position:absolute;bottom:24px;left:12px;z-index:9999;'
        'background:rgba(255,255,255,0.92);padding:8px 10px;border-radius:6px;'
        'box-shadow:0 1px 4px rgba(0,0,0,0.3);font-size:12px;line-height:1.6;'
        'font-family:\'Microsoft YaHei\',sans-serif;color:#333;">'
        '<div style="font-weight:bold;margin-bottom:2px;">AQI 等级</div>'
        + "".join(items) + "</div>"
    )


def build_map(
    *,
    city_meta: dict,
    city_realtime: dict | None,
    stations: list[dict],
    out_path: str | Path,
    basemap: str = "tianditu",
    tk: str | None = None,
    carto_key: str | None = None,
) -> Path:
    """生成自包含交互地图 HTML，返回输出路径。"""
    import folium
    from branca.element import Element

    out_path = Path(out_path)
    tk = tk if tk is not None else os.environ.get("TIANDITU_TK", "")
    carto_key = carto_key if carto_key is not None else os.environ.get("CARTO_KEY", "")

    # 中心点：优先城市中心点，否则取首个有坐标的点位
    center_lat = city_meta.get("lat")
    center_lon = city_meta.get("lon")
    if center_lat is None or center_lon is None:
        for s in stations:
            if s.get("lat") is not None and s.get("lon") is not None:
                center_lat, center_lon = s["lat"], s["lon"]
                break
    if center_lat is None or center_lon is None:
        center_lat, center_lon = 35.0, 105.0  # 兜底：中国地理中心附近
    m = folium.Map(location=[center_lat, center_lon], zoom_start=10, tiles=None)

    # ---- 底图（与 Urbankernel 系列工具保持一致）----
    _add_basemaps(m, basemap=basemap, tk=tk, carto_key=carto_key)

    # ---- 城市中心点 ----
    if center_lat is not None and center_lon is not None:
        city_group = folium.FeatureGroup(name="城市", show=True)
        city_color = aqi_level((city_realtime or {}).get("aqi"))[1]
        folium.CircleMarker(
            location=[center_lat, center_lon],
            radius=CITY_STYLE["radius"],
            color=CITY_STYLE["color"], weight=CITY_STYLE["weight"], opacity=CITY_STYLE["opacity"],
            fill=True, fill_color=city_color, fill_opacity=CITY_STYLE["fill_opacity"],
            popup=folium.Popup(_city_popup(city_meta, city_realtime), max_width=280),
            tooltip=city_meta.get("city_name", "城市"),
        ).add_to(city_group)
        city_group.add_to(m)

    # ---- 点位 ----
    station_group = folium.FeatureGroup(name=f"点位（{len(stations)}）", show=True)
    for row in stations:
        lat, lon = row.get("lat"), row.get("lon")
        if lat is None or lon is None:
            continue
        color = aqi_level(row.get("aqi"))[1]
        folium.CircleMarker(
            location=[lat, lon],
            radius=STATION_STYLE["radius"],
            color=STATION_STYLE["color"], weight=STATION_STYLE["weight"],
            opacity=STATION_STYLE["opacity"],
            fill=True, fill_color=color, fill_opacity=STATION_STYLE["fill_opacity"],
            popup=folium.Popup(_station_popup(row), max_width=280),
            tooltip=row.get("station_name", ""),
        ).add_to(station_group)
    station_group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    m.get_root().html.add_child(Element(_legend_html()))

    m.save(str(out_path))
    logger.info("交互地图: %s（城市 1 个，点位 %d 个）", out_path, len(stations))
    return out_path


def build_map_multi(
    city_results: list[dict],
    *,
    out_path: str | Path,
    basemap: str = "tianditu",
    tk: str | None = None,
    carto_key: str | None = None,
) -> Path:
    """多城市汇总地图：多个城市中心点 + 全部点位，自动缩放覆盖所有城市。

    参数:
        city_results: [{"meta": dict, "result": dict}]，来自 pipeline.fetch_all
    """
    import folium
    from branca.element import Element

    out_path = Path(out_path)
    tk = tk if tk is not None else os.environ.get("TIANDITU_TK", "")
    carto_key = carto_key if carto_key is not None else os.environ.get("CARTO_KEY", "")

    # 收集城市中心点与全部点位
    city_points: list[tuple[float, float, dict, dict | None]] = []
    station_rows: list[dict] = []
    for cr in city_results:
        meta = cr.get("meta")
        result = cr.get("result")
        if not meta or not result:
            continue
        lat, lon = meta.get("lat"), meta.get("lon")
        if lat is not None and lon is not None:
            city_points.append((lat, lon, meta, result.get("city_realtime")))
        for s in result.get("stations", []):
            if s.get("lat") is not None and s.get("lon") is not None:
                station_rows.append(s)

    # 中心点：城市中心点均值，其次点位均值，最后兜底
    if city_points:
        center_lat = sum(p[0] for p in city_points) / len(city_points)
        center_lon = sum(p[1] for p in city_points) / len(city_points)
    elif station_rows:
        center_lat = sum(s["lat"] for s in station_rows) / len(station_rows)
        center_lon = sum(s["lon"] for s in station_rows) / len(station_rows)
    else:
        center_lat, center_lon = 35.0, 105.0

    m = folium.Map(location=[center_lat, center_lon], zoom_start=6, tiles=None)

    _add_basemaps(m, basemap=basemap, tk=tk, carto_key=carto_key)

    # ---- 城市中心点 ----
    city_group = folium.FeatureGroup(name=f"城市（{len(city_points)}）", show=True)
    for lat, lon, meta, rt in city_points:
        color = aqi_level((rt or {}).get("aqi"))[1]
        folium.CircleMarker(
            location=[lat, lon],
            radius=CITY_STYLE["radius"],
            color=CITY_STYLE["color"], weight=CITY_STYLE["weight"], opacity=CITY_STYLE["opacity"],
            fill=True, fill_color=color, fill_opacity=CITY_STYLE["fill_opacity"],
            popup=folium.Popup(_city_popup(meta, rt), max_width=280),
            tooltip=meta.get("city_name", "城市"),
        ).add_to(city_group)
    city_group.add_to(m)

    # ---- 点位 ----
    station_group = folium.FeatureGroup(name=f"点位（{len(station_rows)}）", show=True)
    for row in station_rows:
        color = aqi_level(row.get("aqi"))[1]
        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=STATION_STYLE["radius"],
            color=STATION_STYLE["color"], weight=STATION_STYLE["weight"],
            opacity=STATION_STYLE["opacity"],
            fill=True, fill_color=color, fill_opacity=STATION_STYLE["fill_opacity"],
            popup=folium.Popup(_station_popup(row), max_width=280),
            tooltip=row.get("station_name", ""),
        ).add_to(station_group)
    station_group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    m.get_root().html.add_child(Element(_legend_html()))

    m.save(str(out_path))
    logger.info("多城市汇总地图: %s（城市 %d 个，点位 %d 个）",
                out_path, len(city_points), len(station_rows))
    return out_path
