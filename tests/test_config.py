"""配置加载测试。"""

import pytest

from cnemc_air.config import ConfigError, load_config


def _write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_requires_city(tmp_path):
    p = _write(tmp_path, "outputs: {}\n")
    with pytest.raises(ConfigError):
        load_config(p)


def test_city_name(tmp_path):
    p = _write(tmp_path, "city: {name: 北京市}\noutputs: {dir: runs}\n")
    cfg = load_config(p)
    assert cfg.city_name == "北京市"
    assert cfg.city_code is None


def test_city_code(tmp_path):
    p = _write(tmp_path, "city: {code: '110000'}\n")
    cfg = load_config(p)
    assert cfg.city_code == "110000"


def test_defaults(tmp_path):
    p = _write(tmp_path, "city: {name: 北京市}\n")
    cfg = load_config(p)
    assert cfg.outputs.gpkg is True
    assert cfg.outputs.shp is False
    assert cfg.outputs.csv is True
    assert cfg.viz.basemap == "tianditu"
    assert cfg.request.qps == 1.0


def test_cli_override(tmp_path):
    p = _write(tmp_path, "city: {name: 北京市}\n")
    cfg = load_config(p, {"cities": [{"name": "上海市"}], "output_dir": "out2"})
    assert cfg.city_name == "上海市"
    assert cfg.outputs.dir == "out2"


def test_cities_list(tmp_path):
    p = _write(tmp_path, "cities: [{name: 北京市}, {name: 上海市}, {code: '440100'}]\n")
    cfg = load_config(p)
    assert len(cfg.cities) == 3
    assert cfg.cities[0].name == "北京市"
    assert cfg.cities[1].name == "上海市"
    assert cfg.cities[2].code == "440100"
    assert cfg.city_name == "北京市"  # 兼容属性指向首个城市


def test_cities_string_items(tmp_path):
    p = _write(tmp_path, "cities: ['北京市', '上海市']\n")
    cfg = load_config(p)
    assert [c.name for c in cfg.cities] == ["北京市", "上海市"]


def test_cities_prefer_over_city(tmp_path):
    p = _write(tmp_path, "city: {name: 北京市}\ncities: [{name: 上海市}]\n")
    cfg = load_config(p)
    assert cfg.city_name == "上海市"


def test_invalid_basemap(tmp_path):
    p = _write(tmp_path, "city: {name: 北京市}\nviz: {basemap: foo}\n")
    with pytest.raises(ConfigError):
        load_config(p)


def test_fetch_requires_one(tmp_path):
    p = _write(tmp_path, "city: {name: 北京市}\nfetch: {city: false, stations: false}\n")
    with pytest.raises(ConfigError):
        load_config(p)
