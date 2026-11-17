# 数据源接口参考

本工具的数据来自**中国环境监测总站空气质量发布平台** `https://air.cnemc.cn:18007`。
站点为「ASP.NET 页面片段 + jQuery AJAX + JSON 接口」结构，前端脚本（`TDMap*.js`）直接暴露。
以下 JSON 接口，无需登录、Cookie、签名或验证码。以下内容基于 2026-11 的低频实测，接口可能随平台改版而变化，建议以线上页面实际请求为准。

## 通用约定

- 统一根地址：`https://air.cnemc.cn:18007`
- 除 `GetAQIHistoryByConditionHis`（表单 body `date=...`）外，其余 POST 接口均为
  **query 参数 + 空 body**。
- 响应 `Content-Type` 为 `application/json`；HTTP 200 也可能是 HTML 错误页，必须校验。
- 平台发布说明（`/About/Index`）：每小时更新，**整点后约 20 分钟发布**；设备维护/故障时可能无数据。
- 城市编码通常是六位行政区划式编码，应从接口取得，不要自行推算。

## 城市级接口

| 用途 | 方法与路径 | 参数 | 返回 |
|---|---|---|---|
| 全国城市实时 AQI + 城市编码 + 城市坐标 | `GET /CityData/GetAllCityRealTimeAQIModels` | 无 | 城市数组：`Area / CityCode / TimePoint / AQI / Quality / Latitude / Longitude`（不含六项浓度） |
| 全国城市日报 AQI | `GET /CityData/GetAllCityDayAQIModels` | 无 | 城市日报数组 |
| 省份列表 | `GET /CityData/GetProvince` | 无 | `Id / ProvinceCode / ProvinceName` |
| 省内城市列表 | `GET /CityData/GetCitiesByPid` | `pid`（省份记录内部 `Id`，非 `ProvinceCode`） | 城市数组 |
| 指定城市实时六参数 | `POST /CityData/GetAQIDataPublishLiveInfo` | `cityCode=110000` | 单个对象：AQI、PM2_5、PM10、SO2、NO2、CO、O3、Quality、PrimaryPollutant 等 |
| 指定城市近 24 小时 | `POST /HourChangesPublish/GetCityRealTimeAqiHistoryByCondition` | `citycode=110000` | 24 条，含六项浓度 |
| 指定城市近 14 天日报 | `POST /HourChangesPublish/GetCityDayAqiHistoryByCondition` | `citycode=110000` | 14 条，`PM2_5_24h` 等日均字段 |

实测城市编码：北京 `110000`、上海 `310000`、广州 `440100`、深圳 `440300`。

## 点位级接口

| 用途 | 方法与路径 | 参数 | 返回 |
|---|---|---|---|
| 指定城市全部点位实时 | `GET /CityData/GetAQIDataPublishLive` | `cityName=北京市`（平台完整城市名） | 点位数组，含 `StationCode / PositionName / Latitude / Longitude` 及六项浓度 |
| 指定点位近 24 小时 | `POST /HourChangesPublish/GetAqiHistoryByCondition` | `stationCode=1001A` | 24 条，含六项浓度与坐标 |
| 指定点位近 24 小时分指数 | `POST /HourChangesPublish/GetIAqiHistoryByCondition` | `stationCode=1001A` | `ICO / INO2 / IO3 / IO3_8h / IPM10 / IPM2_5 / ISO2` |
| 指定小时全国点位快照 | `POST /HourChangesPublish/GetAQIHistoryByConditionHis` | 表单 `date=2026-11-09 20:00:00` | 该小时全部点位，按 `Area` 过滤城市 |

## 历史数据的时间窗口（重要）

- `GetCityRealTimeAqiHistoryByCondition` 固定返回 **24 条**（近 24 小时）。
- `GetCityDayAqiHistoryByCondition` 固定返回 **14 条**（近 14 天）。
- `GetAQIHistoryByConditionHis` 接收 `date`，但**仅在近 24 小时窗口内有效**；传入更早时间
  可能返回空数组，也可能静默回退到最新小时——入库前必须校验返回时间与请求时间一致。
- 前端**未暴露 `startTime/endTime` 任意范围查询**。超过 24 小时/14 天的数据不能靠这些接口
  回补，应从开始使用时持续归档；更早年份需向总站/地方生态环境部门申请或使用合规数据服务。

## 返回字段解析要点

- 指标值多为**字符串**（如 `"PM2_5":"27"`），应转可空数值；`""、"NA"、"/"、"—"` 及
  “低于检出限…”等描述文本应保存为 `NULL`。
- 单位：PM2.5、PM10、SO₂、NO₂、O₃ 为 `μg/m³`，CO 为 `mg/m³`，AQI/IAQI 无量纲。
- `TimePoint` 有两种形式：ISO 字符串 `"2026-11-09T22:00:00"`，或 .NET 格式
  `"/Date(1794232800000)/"`（UTC 毫秒）。前者按 `Asia/Shanghai` 解释，后者转东八区。
- 日报字段 `O3_8h_24h` 应理解为 O₃ 日最大 8 小时平均，不能当作普通 O₃ 小时值。
- 点位实时接口的 `CityCode` 可能为 0，入库时应以城市列表接口取得的正式编码补充。

## 经纬度

- 点位经纬度：`GetAQIDataPublishLive` 每个点位带 `Latitude / Longitude`（字符串，6 位小数）；
  点位历史 `GetAqiHistoryByCondition` 每条记录同样带坐标。
- 城市坐标：`GetAllCityRealTimeAQIModels` 每个城市带 `Latitude / Longitude`，该坐标是
  **该市所有监测点位坐标的平均值/中心点**（并非政府驻地或行政中心坐标）。
  城市实时详情 `GetAQIDataPublishLiveInfo` **不返回经纬度**字段。
- 本工具将源坐标按 WGS-84 处理（天地图/CGCS2000 米级对齐，直接叠加），不再生成 GCJ-02 派生列。
