# 输出字段说明

所有成果（CSV / JSON / GPKG / SHP）均使用统一规范化字段。坐标：`lon/lat` 为 WGS-84，同时作为矢量（GPKG/SHP）的几何和属性表字段（属性表中也保留经纬度列）。
单位：PM2.5、PM10、SO₂、NO₂、O₃ 为 `μg/m³`，CO 为 `mg/m³`，AQI 无量纲。

## 城市级（city_realtime / city_hour）

| 字段 | 含义 | 类型 |
|---|---|---|
| `city_code` | 城市编码（如 `110000`） | 文本 |
| `city_name` | 城市名 | 文本 |
| `time_point` | 数据小时 `YYYY-MM-DD HH:MM:SS`（东八区） | 文本 |
| `time_point_str` | 接口原始时间串（仅 city_hour） | 文本 |
| `aqi` | 空气质量指数 | 数值 |
| `quality` | 空气质量等级（优/良/轻度污染…） | 文本 |
| `primary_pollutant` | 首要污染物 | 文本 |
| `measure` | 健康指引 | 文本 |
| `unhealthful` | 不健康提示 | 文本 |
| `pm25` / `pm10` / `so2` / `no2` / `co` / `o3` | 六项浓度 | 数值 |
| `co_level` / `no2_level` / `o3_level` / `pm10_level` / `pm2_5_level` / `so2_level` | 各污染物 IAQI 分指数等级（0–5，对应优/良/轻度/中度/重度/严重） | 数值 |
| `lon` / `lat` | 城市坐标（WGS-84，为该市所有监测点位坐标的平均值/中心点） | 数值 |

## 城市级日报（city_day）

| 字段 | 含义 | 类型 |
|---|---|---|
| `day` | 日期 `YYYY-MM-DD` | 文本 |
| `day_str` | 接口原始时间串 | 文本 |
| `pm25_24h` / `pm10_24h` / `so2_24h` / `no2_24h` / `co_24h` | 日均/24 小时浓度 | 数值 |
| `o3_8h_24h` | O₃ 日最大 8 小时平均 | 数值 |

其余字段同城市级。

## 点位级（station_realtime / station_hour）

| 字段 | 含义 | 类型 |
|---|---|---|
| `station_code` | 点位编码（主键，如 `1001A`） | 文本 |
| `station_name` | 点位名称 | 文本 |
| `city_code` / `city_name` | 所属城市 | 文本 |
| `time_point` / `time_point_str` | 数据小时（同城市级） | 文本 |
| `aqi` / `quality` / `primary_pollutant` / `measure` / `unhealthful` | 同城市级 | — |
| `pm25` / `pm10` / `so2` / `no2` / `co` / `o3` / `o3_8h` | 六项浓度 + O₃ 8 小时 | 数值 |
| `pm25_24h` / `pm10_24h` / `so2_24h` / `no2_24h` / `co_24h` / `o3_24h` / `o3_8h_24h` | 24 小时滑动/均值浓度（接口随报文发布，非日历日日报） | 数值 |
| `co_level` / `no2_level` / `o3_level` / `o3_8h_level` / `pm10_level` / `pm2_5_level` / `so2_level` | 各污染物 IAQI 分指数等级（0–5） | 数值 |
| `no` / `no_24h` / `nox` / `nox_24h` | 一氧化氮 NO 与氮氧化物 NOx 浓度（仅点位实时接口返回，点位 24h 记录此四列为空） | 数值 |
| `lon` / `lat` | 点位坐标（WGS-84） | 数值 |

## 缺失值约定

- CSV：缺失值写空字符串。
- JSON：缺失值保留 `null`。
- GPKG：数值字段空值写 `NULL`，文本字段空值写空串（SQLite 原生支持 NULL）。
- SHP：受 DBF 格式限制，数值字段不支持 NULL，无数据会被写成 0；文本字段空值写空串。**SHP 数值列无数据以 0 表示（格式限制），精确缺失语义请用 GPKG / CSV / JSON。**

## Shapefile 字段名映射

SHP 受 DBF 字段名 ≤10 字符限制，仅以下字段改名（GPKG/CSV/JSON 保持原名）：

| 原名 | SHP 名 |
|---|---|
| `station_code` | `stn_code` |
| `station_name` | `stn_name` |
| `time_point_str` | `time_pts` |
| `primary_pollutant` | `prim_poll` |
| `unhealthful` | `unhealth` |
| `o3_8h_level` | `o3_8h_lv` |
| `pm2_5_level` | `pm25_lv` |

## 多城市目录结构

多城市运行时，每个城市在 run 目录下各占一个子目录，子目录内的字段与文件命名和单城市完全一致；run 根目录 `outputs/` 另放**全量汇总层**：`city_realtime` / `city_hour` / `city_day` / `station_realtime` / `station_hour` 的 CSV+JSON、`city.gpkg`（3 图层）与 `station.gpkg`（2 图层）、以及多城市汇总地图 `map.html`（`outputs.shp: true` 时亦汇总 Shapefile）。汇总文件字段 schema 与单城市**完全一致**，跨城市靠 `city_code` / `city_name` 列区分归属。此外根目录还有 `progress.json`（各城市 done/failed 状态，续跑用）。详见 README「输出」。
