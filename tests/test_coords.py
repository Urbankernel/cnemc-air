"""坐标转换测试。"""

from cnemc_air.coords import (
    bd09_to_wgs84,
    gcj02_to_wgs84,
    wgs84_to_bd09,
    wgs84_to_gcj02,
)

# 北京天安门附近（WGS-84）
LON, LAT = 116.404, 39.915


def test_wgs84_gcj02_round_trip():
    gcj = wgs84_to_gcj02(LON, LAT)
    back = gcj02_to_wgs84(*gcj)
    assert abs(back[0] - LON) < 1e-4
    assert abs(back[1] - LAT) < 1e-4


def test_gcj02_has_offset():
    gcj = wgs84_to_gcj02(LON, LAT)
    assert (gcj[0], gcj[1]) != (LON, LAT)  # 境内有火星偏移


def test_wgs84_bd09_round_trip():
    bd = wgs84_to_bd09(LON, LAT)
    back = bd09_to_wgs84(*bd)
    assert abs(back[0] - LON) < 1e-4
    assert abs(back[1] - LAT) < 1e-4


def test_out_of_china_unchanged():
    # 经度 140° 在境外（中国境外无火星偏移）
    assert wgs84_to_gcj02(140.0, 40.0) == (140.0, 40.0)
    assert gcj02_to_wgs84(140.0, 40.0) == (140.0, 40.0)
