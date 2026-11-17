"""WGS-84 ↔ GCJ-02（火星坐标系）↔ BD-09（百度坐标系）转换。

公式移植自 Urbankernel/amap-poi-fetcher 的 coords.py（经验公式 + 对称反向逼近），
并补充 BD-09 双向转换。数值行为与原脚本一致。

纪律（与 Urbankernel 系列工具保持一致）：
- 系统内部与成果文件一律 WGS-84（lon/lat 主列），不再生成 GCJ-02 派生列；
- 本模块的转换函数为可选工具：需叠加高德/腾讯（GCJ-02）或百度（BD-09）底图时手动调用；
- 天地图底图采用 CGCS2000，与 WGS-84 在米级尺度对齐，交互地图直接用 WGS-84 叠加即可。
"""

from __future__ import annotations

import math

PI = 3.1415926535897932384626  # π
A = 6378245.0  # 长半轴
EE = 0.00669342162296594323  # 偏心率平方

# 百度 BD-09 二次加密偏移常量
BD_X_PI = PI * 3000.0 / 180.0


def _out_of_china(lng: float, lat: float) -> bool:
    """是否在中国境外（境外坐标无火星偏移，原样返回）。"""
    return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(lng: float, lat: float) -> float:
    """纬度偏移辅助计算（多项式 + 三角函数经验公式）。"""
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + \
          0.1 * lng * lat + 0.2 * math.sqrt(math.fabs(lng))
    ret += (20.0 * math.sin(6.0 * lng * PI) + 20.0 *
            math.sin(2.0 * lng * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * PI) + 40.0 *
            math.sin(lat / 3.0 * PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * PI) + 320 *
            math.sin(lat * PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng: float, lat: float) -> float:
    """经度偏移辅助计算（多项式 + 三角函数经验公式）。"""
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + \
          0.1 * lng * lat + 0.1 * math.sqrt(math.fabs(lng))
    ret += (20.0 * math.sin(6.0 * lng * PI) + 20.0 *
            math.sin(2.0 * lng * PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * PI) + 40.0 *
            math.sin(lng / 3.0 * PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * PI) + 300.0 *
            math.sin(lng / 30.0 * PI)) * 2.0 / 3.0
    return ret


def gcj02_to_wgs84(lng: float, lat: float) -> tuple[float, float]:
    """GCJ-02 → WGS-84。

    参数:
        lng: 经度（GCJ-02）
        lat: 纬度（GCJ-02）

    返回:
        (经度, 纬度)，WGS-84。境外坐标原样返回。
    """
    if _out_of_china(lng, lat):
        return lng, lat
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * PI
    magic = math.sin(radlat)
    magic = 1 - EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sqrtmagic) * PI)
    dlng = (dlng * 180.0) / (A / sqrtmagic * math.cos(radlat) * PI)
    mglat = lat + dlat
    mglng = lng + dlng
    # 利用对称原理反向逼近 WGS-84
    return lng * 2 - mglng, lat * 2 - mglat


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    """WGS-84 → GCJ-02（正向偏移）。

    与 gcj02_to_wgs84 近似互逆（往返误差 < 1e-4°，即米级）。境外坐标原样返回。
    """
    if _out_of_china(lng, lat):
        return lng, lat
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * PI
    magic = math.sin(radlat)
    magic = 1 - EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((A * (1 - EE)) / (magic * sqrtmagic) * PI)
    dlng = (dlng * 180.0) / (A / sqrtmagic * math.cos(radlat) * PI)
    return lng + dlng, lat + dlat


def bd09_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    """BD-09（百度）→ GCJ-02。"""
    x = lng - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * BD_X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * BD_X_PI)
    return z * math.cos(theta), z * math.sin(theta)


def gcj02_to_bd09(lng: float, lat: float) -> tuple[float, float]:
    """GCJ-02 → BD-09（百度）。"""
    z = math.sqrt(lng * lng + lat * lat) + 0.00002 * math.sin(lat * BD_X_PI)
    theta = math.atan2(lat, lng) + 0.000003 * math.cos(lng * BD_X_PI)
    return z * math.cos(theta) + 0.0065, z * math.sin(theta) + 0.006


def wgs84_to_bd09(lng: float, lat: float) -> tuple[float, float]:
    """WGS-84 → BD-09（百度）。"""
    return gcj02_to_bd09(*wgs84_to_gcj02(lng, lat))


def bd09_to_wgs84(lng: float, lat: float) -> tuple[float, float]:
    """BD-09（百度）→ WGS-84。"""
    return gcj02_to_wgs84(*bd09_to_gcj02(lng, lat))
