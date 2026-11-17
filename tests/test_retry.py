"""指数退避测试。"""

from cnemc_air.retry import backoff_delay


def test_backoff_increasing():
    delays = [backoff_delay(1.0, i, jitter_ratio=0.0) for i in range(4)]
    assert delays == [1.0, 2.0, 4.0, 8.0]
    assert delays == sorted(delays)


def test_backoff_base_scales():
    d = backoff_delay(0.5, 1, jitter_ratio=0.0)
    assert d == 1.0


def test_backoff_jitter_bounds():
    d = backoff_delay(1.0, 0, jitter_ratio=0.3)
    assert 1.0 <= d <= 1.3
