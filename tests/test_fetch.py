"""阶段②取数与校验的单元测试（纯函数，无网络）。"""
import pytest
from datetime import date, timedelta

from src.workflow.fetch import (
    AsOfError,
    detect_jumps,
    find_gaps,
    load_signal,
    resolve_window,
    sha256_file,
)


# ---- resolve_window -------------------------------------------------------

def d(s):
    return date.fromisoformat(s)


def test_window_takes_intersection():
    w = resolve_window(d("2018-01-02"), d("2026-08-12"),
                       d("2020-01-17"), d("2026-11-06"))
    assert w["window_start"] == d("2020-01-17")   # 上市日晚于信号首日
    assert w["window_end"] == d("2026-08-12")     # 信号末日早于行情末日，裁切
    assert any("裁切" in f for f in w["flags"])


def test_window_no_overlap_raises():
    with pytest.raises(AsOfError):
        resolve_window(d("2018-01-02"), d("2019-12-31"),
                       d("2020-01-17"), d("2026-11-06"))


def test_window_user_asof_truncates():
    w = resolve_window(d("2018-01-02"), d("2026-08-12"),
                       d("2020-01-17"), d("2026-11-06"),
                       user_asof=d("2025-06-30"))
    assert w["window_end"] == d("2025-06-30")
    assert any("as_of" in f for f in w["flags"])


def test_window_user_asof_before_start_raises():
    with pytest.raises(AsOfError):
        resolve_window(d("2018-01-02"), d("2026-08-12"),
                       d("2020-01-17"), d("2026-11-06"),
                       user_asof=d("2019-01-01"))


def test_window_price_lag_flagged():
    w = resolve_window(d("2018-01-02"), d("2026-08-12"),
                       d("2020-01-17"), d("2026-06-30"))
    assert w["window_end"] == d("2026-06-30")
    assert any("滞后" in f for f in w["flags"])


# ---- find_gaps ------------------------------------------------------------

def test_find_gaps_ignores_weekends_and_small_holes():
    # 连续 5 个工作日，无缺口
    dates = [d("2024-01-01") + timedelta(days=i) for i in range(7)]
    dates = [x for x in dates if x.weekday() < 5]
    assert find_gaps(dates) == []


def test_find_gaps_detects_spring_festival():
    # 连续 20 个工作日，模拟春节休市剔除 2024-02-12 ~ 02-16
    dates = [d("2024-02-05") + timedelta(days=i) for i in range(20)]
    dates = [x for x in dates if x.weekday() < 5]
    dates = [x for x in dates if not (d("2024-02-12") <= x <= d("2024-02-16"))]
    gaps = find_gaps(dates)
    assert len(gaps) == 1
    assert gaps[0]["from"] == "2024-02-09"
    assert gaps[0]["to"] == "2024-02-19"
    assert gaps[0]["missing_bdays"] > 3


def test_find_gaps_threshold_respected():
    dates = [d("2024-01-02"), d("2024-01-03"), d("2024-01-08")]  # 隔 2 个工作日
    assert find_gaps(dates) == []
    assert len(find_gaps(dates, max_normal_bday=1)) == 1


# ---- detect_jumps ---------------------------------------------------------

def test_detect_jumps_quiet_series():
    dates = [d("2024-01-01") + timedelta(days=i) for i in range(60)]
    values = [100.0 * (1.001 ** i) for i in range(60)]
    assert detect_jumps(dates, values) == []


def test_detect_jumps_flags_spike():
    dates = [d("2024-01-01") + timedelta(days=i) for i in range(60)]
    values = [100.0 * (1.001 ** i) for i in range(60)]
    values[30] *= 1.10  # 单日 +10%，低波品种极端跳变
    hits = detect_jumps(dates, values)
    assert len(hits) == 1
    assert hits[0]["date"] == "2024-01-31"


def test_detect_jumps_ignores_gradual_trend():
    dates = [d("2024-01-01") + timedelta(days=i) for i in range(60)]
    values = [100.0 * (1.01 ** i) for i in range(60)]  # 每日 +1%，趋势非跳变
    assert detect_jumps(dates, values) == []


# ---- 其他纯函数 ------------------------------------------------------------

def test_sha256_known_content(tmp_path):
    p = tmp_path / "a.txt"
    p.write_bytes(b"abc")
    assert sha256_file(p) == ("ba7816bf8f01cfea414140de5dae2223"
                              "b00361a396177a9cb410ff61f20015ad")


# ---- load_signal ----------------------------------------------------------

def test_load_signal_roundtrip_and_validation(tmp_path):
    import pandas as pd
    good = pd.DataFrame({
        "DateTime": pd.to_datetime(["2024-01-02", "2024-01-03"]),
        "温度计总值": [50.0, 51.0],
    })
    p = tmp_path / "sig.xlsx"
    good.to_excel(p, index=False)
    df = load_signal(p)
    assert list(df["温度计总值"]) == [50.0, 51.0]

    dup = pd.DataFrame({"DateTime": pd.to_datetime(["2024-01-02", "2024-01-02"]),
                        "温度计总值": [50.0, 51.0]})
    dup.to_excel(p, index=False)
    with pytest.raises(ValueError, match="重复日期"):
        load_signal(p)

    nan_df = pd.DataFrame({"DateTime": pd.to_datetime(["2024-01-02", "2024-01-03"]),
                           "温度计总值": [50.0, None]})
    nan_df.to_excel(p, index=False)
    with pytest.raises(ValueError, match="缺失值"):
        load_signal(p)
