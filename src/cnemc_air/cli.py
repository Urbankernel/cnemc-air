"""命令行入口。

    cnemc-air run                                  # 默认读取 configs/config.yaml 抓取城市
    cnemc-air run --city 北京,上海,广州            # 一次抓取多个城市
    cnemc-air run --city-code 110000,310000        # 按编码多城市
    cnemc-air run --cities-file cities.txt         # 从清单文件读取城市
    cnemc-air run --resume runs/20261117_xxx       # 续跑：跳过已完成城市
    cnemc-air cities                               # 列出全部城市（编码/名称/经纬度）
    cnemc-air cities --filter 北京
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .client import CnemcClient
from .config import ConfigError, load_config
from .log import attach_file_handler, setup_logging
from .normalize import to_float, to_text
from .pipeline import fetch, resolve_city_by_list
from .store import RunStore

logger = logging.getLogger("cnemc_air.cli")

DEFAULT_CONFIG = "configs/config.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cnemc-air",
        description="中国环境监测总站空气质量数据获取工具：城市级/点位级实时与历史数据，"
                    "输出 CSV / JSON / GeoPackage / Shapefile / 天地图底图交互 HTML",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="抓取一个或多个城市的城市级/点位级实时与历史数据")
    run_p.add_argument("-c", "--config", default=DEFAULT_CONFIG,
                       help=f"YAML 配置文件路径（默认 {DEFAULT_CONFIG}）")
    run_p.add_argument("--city", action="append",
                       help="城市名，可逗号分隔或多次传入（覆盖配置中的城市）")
    run_p.add_argument("--city-code", action="append",
                       help="城市编码，可逗号分隔或多次传入")
    run_p.add_argument("--cities-file", help="城市清单文件（每行一个城市名/编码，或 YAML 列表）")
    run_p.add_argument("--output-dir", help="run 目录根（覆盖配置 outputs.dir）")
    run_p.add_argument("--resume", help="续跑：指定已存在的 run 目录，跳过已完成的城市")

    cities_p = sub.add_parser("cities", help="列出全部城市（编码/名称/经纬度/AQI）")
    cities_p.add_argument("--filter", help="按城市名关键字过滤")

    return parser


def _make_client(cfg) -> CnemcClient:
    return CnemcClient(
        qps=cfg.request.qps,
        max_retries=cfg.request.max_retries,
        retry_base=cfg.request.retry_base_seconds,
        timeout=cfg.request.timeout,
        verify=cfg.request.verify,
    )


def _masked_snapshot(cfg) -> dict:
    """配置快照：tk / carto_key 脱敏后写入（不泄漏凭证）。"""
    snapshot = dict(cfg.raw)
    viz = dict(snapshot.get("viz") or {})
    for cred in ("tianditu_tk", "carto_key"):
        if viz.get(cred):
            viz[cred] = "***"
    if viz:
        snapshot["viz"] = viz
    snapshot.pop("key_file", None)
    return snapshot


def _read_cities_file(path: str) -> list[dict]:
    """从清单文件读取城市目标：YAML 列表 或 每行一个城市名/编码（纯数字视为编码）。"""
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"城市清单文件不存在: {path}")
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        import yaml
        data = yaml.safe_load(text) or {}
        items = data.get("cities", data) if isinstance(data, dict) else data
        if not isinstance(items, list):
            raise ConfigError(f"城市清单文件需为列表: {path}")
        return items
    targets: list[dict] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        s = s.split("#", 1)[0].strip()
        if not s:
            continue
        if s.isdigit():
            targets.append({"code": s})
        else:
            targets.append({"name": s})
    return targets


def _parse_city_targets(args) -> list[dict] | None:
    """从 CLI 参数解析城市目标：--city / --city-code 支持逗号分隔与多次传入。

    返回 None 表示未通过 CLI 指定城市（沿用配置文件）。
    """
    name_list: list[str] = []
    for n in args.city or []:
        name_list += [x for x in (y.strip() for y in n.split(",")) if x]
    code_list: list[str] = []
    for c in args.city_code or []:
        code_list += [x for x in (y.strip() for y in c.split(",")) if x]

    file_targets: list[dict] = []
    if args.cities_file:
        file_targets = _read_cities_file(args.cities_file)

    if not name_list and not code_list and not file_targets:
        return None

    targets: list[dict] = list(file_targets)
    for i in range(max(len(name_list), len(code_list))):
        name = name_list[i] if i < len(name_list) else None
        code = code_list[i] if i < len(code_list) else None
        if name or code:
            targets.append({"name": name, "code": code})
    return targets


def _print_city_summary(meta: dict, result: dict) -> None:
    rt = result.get("city_realtime")
    aqi = rt.get("aqi") if rt else None
    quality = rt.get("quality") if rt else None
    print(f"  {meta.get('city_name')}（{meta.get('city_code')}）: "
          f"AQI {aqi}（{quality}） | 24h {len(result.get('city_hour', []))} | "
          f"日报 {len(result.get('city_day', []))} | 点位 {len(result.get('stations', []))} | "
          f"点位24h {len(result.get('station_hour', []))}")


def cmd_run(args: argparse.Namespace) -> int:
    if args.config == DEFAULT_CONFIG and not Path(args.config).exists():
        print(
            f"未找到默认配置文件 {DEFAULT_CONFIG}。请先复制模板并填写参数：\n"
            "  cp configs/example.yaml configs/config.yaml        # Linux / macOS\n"
            "  copy configs\\example.yaml configs\\config.yaml     # Windows\n"
            "或使用 -c 指定其它配置文件路径。",
            file=sys.stderr,
        )
        return 1

    cli_cities = _parse_city_targets(args)
    cfg = load_config(args.config, {
        "cities": cli_cities, "output_dir": args.output_dir,
    })
    setup_logging()
    client = _make_client(cfg)

    # 拉取一次全国城市列表，供多个城市本地匹配复用
    all_cities = client.get_all_cities()
    if not isinstance(all_cities, list) or not all_cities:
        print("城市列表接口返回为空或结构异常，接口可能已变化", file=sys.stderr)
        return 1

    # 解析所有目标城市（单个失败不中断）
    metas: list[dict] = []
    resolve_errors: list[tuple[str, str]] = []
    for t in cfg.cities:
        label = t.name or t.code or "?"
        try:
            metas.append(resolve_city_by_list(all_cities, name=t.name, code=t.code))
        except Exception as e:
            resolve_errors.append((label, str(e)))
            logger.error("城市解析失败: %s", e)
    if not metas:
        print("没有可采集的城市（全部解析失败），请检查城市名/编码", file=sys.stderr)
        return 1

    # 创建或打开 run 目录
    if args.resume:
        resume_path = Path(args.resume)
        if not resume_path.exists():
            print(f"续跑目录不存在: {args.resume}", file=sys.stderr)
            return 1
        store = RunStore.open(resume_path)
        logger.info("续跑模式：沿用 run 目录 %s", store.run_dir)
    else:
        tag = metas[0]["city_name"] if len(metas) == 1 else f"multi_{len(metas)}"
        store = RunStore.create(cfg.outputs.dir, tag, _masked_snapshot(cfg))
    attach_file_handler(store.run_dir)

    progress = store.load_progress()

    from . import export
    from .viz import build_map, build_map_multi

    city_results: list[dict] = []
    for meta in metas:
        city_name = meta.get("city_name") or "unknown"
        if progress.get(city_name) == "done":
            logger.info("跳过已完成城市: %s", city_name)
            continue
        city_store = store.child(city_name)
        try:
            result = fetch(client, cfg, meta=meta)
            if cfg.outputs.raw:
                city_store.save_raw_all(result["raw"])
            export.export_table(result, city_store, cfg.outputs)
            export.export_vector(result, city_store, cfg.outputs)
            if cfg.outputs.html:
                build_map(
                    city_meta=meta,
                    city_realtime=result["city_realtime"],
                    stations=result["stations"],
                    out_path=city_store.outputs_dir / "map.html",
                    basemap=cfg.viz.basemap,
                    tk=cfg.viz.tianditu_tk or None,
                    carto_key=cfg.viz.carto_key or None,
                )
            progress[city_name] = "done"
            city_results.append({"meta": meta, "result": result})
            _print_city_summary(meta, result)
        except Exception as e:
            progress[city_name] = "failed"
            logger.error("城市 %s 采集失败: %s", city_name, e)
        store.save_progress(progress)

    # 多城市汇总地图
    if cfg.outputs.html and len(city_results) > 1:
        try:
            build_map_multi(
                city_results,
                out_path=store.outputs_dir / "map.html",
                basemap=cfg.viz.basemap,
                tk=cfg.viz.tianditu_tk or None,
                carto_key=cfg.viz.carto_key or None,
            )
        except Exception as e:
            logger.error("汇总地图生成失败: %s", e)

    # 多城市汇总：表格 / 矢量（schema 与单城市一致，写到根 outputs/）
    if len(city_results) > 1:
        try:
            merged = export.merge_results([r["result"] for r in city_results])
            export.export_table(merged, store, cfg.outputs)
            export.export_vector(merged, store, cfg.outputs)
        except Exception as e:
            logger.error("汇总 CSV/JSON/GPKG/SHP 生成失败: %s", e)

    # 小结
    done = [k for k, v in progress.items() if v == "done"]
    failed = [k for k, v in progress.items() if v == "failed"]
    print("=" * 56)
    print(f"完成 {len(done)} 个城市" +
          (f"，失败 {len(failed)} 个: {', '.join(failed)}" if failed else ""))
    if resolve_errors:
        print("解析失败:", "; ".join(f"{n}: {e}" for n, e in resolve_errors))
    print(f"实际请求: {client.request_count} 次")
    print(f"run 目录: {store.run_dir}")
    return 0 if done else 2


def cmd_cities(args: argparse.Namespace) -> int:
    setup_logging()
    client = CnemcClient(qps=1.0, max_retries=2, timeout=30.0)
    cities = client.get_all_cities()
    if not isinstance(cities, list):
        print("城市列表接口返回异常", file=sys.stderr)
        return 1
    kw = (args.filter or "").strip()
    rows = []
    for c in cities:
        area = to_text(c.get("Area")) or ""
        if kw and kw not in area:
            continue
        lon = to_float(c.get("Longitude"))
        lat = to_float(c.get("Latitude"))
        rows.append((to_text(c.get("CityCode")) or "", area,
                     f"{lon:.6f}" if lon is not None else "",
                     f"{lat:.6f}" if lat is not None else "",
                     c.get("AQI"), to_text(c.get("Quality")) or ""))
    print(f"共 {len(rows)} 个城市" + (f"（匹配 {kw!r}）" if kw else ""))
    print(f"{'城市编码':<10}{'城市':<12}{'经度':>12}{'纬度':>12}{'AQI':>8}  等级")
    for code, area, lon, lat, aqi, quality in rows:
        print(f"{code:<10}{area:<12}{str(lon):>12}{str(lat):>12}{str(aqi):>8}  {quality}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
            return cmd_run(args)
        return cmd_cities(args)
    except ConfigError as e:
        print(f"配置错误: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已中断。已获取的数据已落盘。", file=sys.stderr)
        return 130
    except Exception as e:  # 网络/接口错误统一兜底，给用户可读信息
        print(f"运行失败: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
