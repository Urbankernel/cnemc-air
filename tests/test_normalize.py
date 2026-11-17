"""字段规范化测试。"""

from cnemc_air.normalize import (
    aqi_level,
    build_city_day,
    build_city_meta,
    build_station_realtime,
    fmt_time,
    parse_time,
    to_float,
    to_text,
)


def test_parse_time_iso():
    dt = parse_time("2026-11-09T22:00:00")
    assert fmt_time(dt) == "2026-11-09 22:00:00"


def test_parse_time_space_separated():
    dt = parse_time("2026-11-09 22:00:00")
    assert fmt_time(dt) == "2026-11-09 22:00:00"


def test_parse_time_dotnet():
    # /Date(毫秒时间戳)/：UTC 毫秒 → 东八区
    dt = parse_time("/Date(1794232800000)/")
    assert dt is not None
    assert dt.utcoffset().total_seconds() == 8 * 3600


def test_parse_time_invalid():
    assert parse_time("") is None
    assert parse_time(None) is None
    assert parse_time("not-a-date") is None


def test_to_float_missing():
    for v in ("", "NA", "n/a", "/", "—", "-", "null", "低于检出限(0.5)"):
        assert to_float(v) is None


def test_to_float_number():
    assert to_float("27") == 27.0
    assert to_float(27) == 27.0
    assert to_float("27.5") == 27.5


def test_to_text():
    assert to_text(None) is None
    assert to_text("") is None
    assert to_text("NA") is None
    assert to_text(" 良 ") == "良"


def test_aqi_level():
    assert aqi_level(25)[0] == "优"
    assert aqi_level(100)[0] == "良"
    assert aqi_level(120)[0] == "轻度污染"
    assert aqi_level(180)[0] == "中度污染"
    assert aqi_level(250)[0] == "重度污染"
    assert aqi_level(400)[0] == "严重污染"
    assert aqi_level(None)[0] == "无数据"


def test_build_city_meta_coords():
    meta = build_city_meta({"Area": "北京市", "CityCode": "110000",
                            "Latitude": "39.9042", "Longitude": "116.4074"})
    assert meta["city_code"] == "110000"
    assert meta["lon"] == 116.4074
    assert meta["lat"] == 39.9042
    # 成果只保留 WGS-84，不再生成 GCJ-02 派生列
    assert "lon_gcj02" not in meta
    assert "lat_gcj02" not in meta


def test_build_station_realtime():
    city_meta = build_city_meta({"Area": "北京市", "CityCode": "110000",
                                 "Latitude": "39.9042", "Longitude": "116.4074"})
    row = build_station_realtime({
        "StationCode": "1001A", "PositionName": "万寿西宫",
        "Latitude": "39.8786", "Longitude": "116.3611",
        "AQI": "132", "PM2_5": "27", "Quality": "轻度污染",
        "TimePoint": "2026-11-09T22:00:00",
    }, city_meta)
    assert row["station_code"] == "1001A"
    assert row["station_name"] == "万寿西宫"
    assert row["pm25"] == 27.0
    assert row["city_code"] == "110000"
    assert row["time_point"] == "2026-11-09 22:00:00"


def test_build_station_realtime_full_fields():
    city_meta = build_city_meta({"Area": "上海市", "CityCode": "310000",
                                 "Latitude": "31.2304", "Longitude": "121.4737"})
    row = build_station_realtime({
        "StationCode": "1143A", "PositionName": "虹口",
        "Latitude": "31.3011", "Longitude": "121.4673",
        "AQI": "64", "PM2_5": "42", "PM10": "48", "SO2": "7",
        "NO2": "69", "CO": "0.6", "O3": "1", "O3_8h": "36",
        "PM2_5_24h": "39", "PM10_24h": "43", "SO2_24h": "6",
        "NO2_24h": "53", "CO_24h": "0.5", "O3_24h": "1", "O3_8h_24h": "7",
        "COLevel": 0, "NO2Level": 0, "O3Level": 0, "O3_8hLevel": 0,
        "PM10Level": 0, "PM2_5Level": 0, "SO2Level": 0,
        "NO": "NA", "NO_24h": "NA", "NOx": "NA", "NOx_24h": "NA",
        "TimePoint": "2026-11-13T23:00:00",
    }, city_meta)
    # 小时值
    assert row["pm25"] == 42.0 and row["o3_8h"] == 36.0 and row["co"] == 0.6
    # 24h 值
    assert row["pm25_24h"] == 39.0 and row["o3_24h"] == 1.0 and row["o3_8h_24h"] == 7.0
    # 分指数等级
    assert row["pm2_5_level"] == 0.0 and row["o3_8h_level"] == 0.0
    # NO/NOx 缺失值（"NA" → None）
    assert row["no"] is None and row["nox_24h"] is None


def test_build_station_hour_full_fields():
    from cnemc_air.normalize import build_station_hour

    city_meta = build_city_meta({"Area": "上海市", "CityCode": "310000",
                                 "Latitude": "31.2304", "Longitude": "121.4737"})
    row = build_station_hour({
        "StationCode": "1141A", "PositionName": "普陀",
        "Latitude": "31.2382", "Longitude": "121.401",
        "AQI": "84", "PM2_5": "52", "PM10": "70", "SO2": "6",
        "NO2": "61", "CO": "0.5", "O3": "24",
        "PM2_5_24h": "39", "PM10_24h": "", "SO2_24h": "6",
        "NO2_24h": "53", "CO_24h": "0.3", "O3_24h": "NA", "O3_8h_24h": "NA",
        "COLevel": 1, "NO2Level": 1, "O3Level": 1, "O3_8hLevel": 1,
        "PM10Level": 2, "PM2_5Level": 2, "SO2Level": 1,
        "TimePoint": "/Date(1794502800000)/", "TimePointStr": "13日01时",
    }, city_meta)
    # 点位 24h 接口不含 NO 系列，故为空
    assert row["no"] is None and row["nox"] is None
    assert row["pm25_24h"] == 39.0
    assert row["pm10_24h"] is None  # 空字符串 → 缺失
    assert row["o3_24h"] is None  # "NA" → 缺失
    assert row["pm2_5_level"] == 2.0
    assert row["o3_8h_level"] == 1.0
    # .NET 时间戳解析为东八区
    assert row["time_point"].startswith("2026-11-")


def test_build_city_day_date_only():
    city_meta = build_city_meta({"Area": "北京市", "CityCode": "110000",
                                 "Latitude": "39.9042", "Longitude": "116.4074"})
    row = build_city_day({
        "AQI": "58", "PM2_5_24h": "19", "PM10_24h": "61",
        "TimePoint": "2026-10-30T00:00:00", "TimePointStr": "30日",
    }, city_meta)
    assert row["day"] == "2026-10-30"
    assert row["pm25_24h"] == 19.0
    assert row["pm10_24h"] == 61.0
