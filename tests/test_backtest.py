"""阶段③回测执行的单元测试（纯函数，无网络）。"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from src.workflow.backtest import (
    SnapshotError,
    compute_metrics,
    extract_trades,
    generate_targets,
    load_window,
    simulate,
    verify_snapshot,
)


def d(s):
    return date.fromisoformat(s)


# ---- generate_targets -----------------------------------------------------

def test_targets_binary_threshold_boundary():
    # 边界：恰好 85 视为 ≤85 → 满仓
    assert generate_targets([50.0, 90.0, 85.0001, 85.0], 85.0) == [1, 0, 0, 1]


# ---- generate_targets_ma（v3 双确认） ---------------------------------------

from src.workflow.backtest import generate_targets_ma  # noqa: E402


def test_ma_phase_requires_both_conditions():
    temp = [50.0, 50.0, 50.0, 50.0]
    close = [110.0, 90.0, 110.0, 90.0]
    ma = [100.0, 100.0, 100.0, 100.0]
    # 温度达标但跌破均线 → 清仓；收复均线 → 满仓
    assert generate_targets_ma(temp, close, ma, 85.0) == [1, 0, 1, 0]


def test_ma_phase_temp_hot_overrides_above_ma():
    temp = [90.0, 50.0]
    close = [110.0, 110.0]
    ma = [100.0, 100.0]
    # 均线上方但温度 >85 → 清仓（逃顶条件独立生效）
    assert generate_targets_ma(temp, close, ma, 85.0) == [0, 1]


def test_nan_ma_phase_temp_only():
    temp = [50.0, 90.0]
    close = [100.0, 100.0]
    ma = [float("nan"), float("nan")]
    # 均线未形成（上市前 199 日）：仅温度计条件
    assert generate_targets_ma(temp, close, ma, 85.0) == [1, 0]


# ---- simulate：t 判定 → t+1 收盘执行 ----------------------------------------

def test_exec_lag_one_day():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"])
    closes = np.array([100.0, 110.0, 121.0, 133.1])  # 每日 +10%
    temp = [50.0, 90.0, 50.0, 50.0]
    targets = generate_targets(temp, 85.0)
    sim = simulate(dates, closes, targets, commission=0.0)
    # t+1 执行：day1 判定清仓，day2 收盘才卖；day2 的收益仍吃到
    assert sim["exec_position"].tolist() == [1, 1, 0, 1]
    assert sim["strategy_equity"].tolist() == pytest.approx([1.0, 1.1, 1.21, 1.21])
    trades = extract_trades(sim, 0.0)
    assert trades["side"].tolist() == ["BUY", "SELL", "BUY"]
    assert trades["date"].tolist() == ["2024-01-02", "2024-01-04", "2024-01-05"]


def test_start_hot_stays_flat_until_first_cold():
    dates = pd.to_datetime(["2024-01-0%d" % i for i in range(2, 6)])
    closes = np.array([100.0, 100.0, 100.0, 100.0])
    temp = [90.0, 90.0, 50.0, 50.0]
    targets = generate_targets(temp, 85.0)
    sim = simulate(dates, closes, targets, commission=0.0)
    assert sim["exec_position"].tolist() == [0, 0, 0, 1]  # day2 判定，day3 收盘入场
    trades = extract_trades(sim, 0.0)
    assert len(trades) == 1 and trades["date"].iloc[0] == "2024-01-05"


def test_commission_deducted_on_both_sides():
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    closes = np.array([100.0, 100.0, 100.0])
    temp = [50.0, 90.0, 50.0]
    targets = generate_targets(temp, 85.0)
    sim = simulate(dates, closes, targets, commission=0.0003)
    # day0 建仓 1×万3；day1 判定；day2 收盘卖出 1×万3 → 权益 1 - 0.0003 - 0.0003
    assert sim["strategy_equity"].iloc[-1] == pytest.approx(1 - 0.0006)
    trades = extract_trades(sim, 0.0003)
    assert trades["commission"].sum() == pytest.approx(0.0006)


def test_strategy_never_loses_more_than_baseline_in_crash_when_flat():
    dates = pd.to_datetime(["2024-01-0%d" % i for i in range(2, 6)])
    closes = np.array([100.0, 90.0, 81.0, 72.9])  # 连续 -10%
    temp = [90.0, 90.0, 90.0, 90.0]  # 全程 >85 清仓
    sim = simulate(dates, closes, generate_targets(temp, 85.0), commission=0.0)
    assert sim["strategy_equity"].iloc[-1] == pytest.approx(1.0)  # 空仓免疫下跌
    assert sim["baseline_equity"].iloc[-1] == pytest.approx(0.729)


# ---- compute_metrics ------------------------------------------------------

def test_metrics_known_values():
    equity = pd.Series([1.0, 1.1, 0.99])
    ret = equity.pct_change().fillna(0.0)
    m = compute_metrics(equity, ret)
    assert m["total_return"] == pytest.approx(-0.01)
    assert m["annual_return"] == pytest.approx(0.99 ** 126 - 1)
    assert m["max_drawdown"] == pytest.approx(-0.1)
    assert m["sharpe"] == pytest.approx(0.0, abs=1e-9)  # +10%/-10% 均值 0


def test_metrics_flat_series_sharpe_nan_guard():
    equity = pd.Series([1.0, 1.0, 1.0])
    m = compute_metrics(equity, equity.pct_change().fillna(0.0))
    assert m["sharpe"] != m["sharpe"]  # NaN，不抛异常
    assert m["max_drawdown"] == 0.0


# ---- 快照校验与窗口对齐 ------------------------------------------------------

def _make_run(tmp_path, tamper=False, drop_signal_rows=0):
    data = tmp_path / "data"
    data.mkdir()
    sig = pd.DataFrame({"DateTime": pd.date_range("2024-01-02", periods=4, freq="B"),
                        "温度计总值": [50.0, 90.0, 50.0, 50.0]})
    px = pd.DataFrame({"date": pd.date_range("2024-01-02", periods=4, freq="B"),
                       "open": 1.0, "close": [1.0, 1.0, 1.0, 1.0],
                       "high": 1.0, "low": 1.0, "volume": 1, "amount": 1.0})
    if drop_signal_rows:
        sig = sig.iloc[:-drop_signal_rows]
    sig.to_csv(data / "signal.csv", index=False, encoding="utf-8-sig")
    px.to_csv(data / "price_hfq.csv", index=False, encoding="utf-8-sig")
    from src.workflow.fetch import sha256_file
    manifest = {
        "files": {
            "signal.csv": {"sha256": sha256_file(data / "signal.csv"), "rows": len(sig)},
            "price_hfq.csv": {"sha256": sha256_file(data / "price_hfq.csv"), "rows": len(px)},
        },
        "as_of": {"window_start": "2024-01-02", "window_end": "2024-01-05"},
    }
    if tamper:
        (data / "signal.csv").write_text("hacked", encoding="utf-8")
    (data / "snapshot_manifest.json").write_text(
        __import__("json").dumps(manifest), encoding="utf-8")
    return data, manifest


def test_snapshot_hash_mismatch_rejected(tmp_path):
    data, _ = _make_run(tmp_path, tamper=True)
    with pytest.raises(SnapshotError, match="哈希不符"):
        verify_snapshot(data)


def test_snapshot_ok(tmp_path):
    data, _ = _make_run(tmp_path)
    m = verify_snapshot(data)
    assert m["files"]["signal.csv"]["rows"] == 4


def test_price_day_without_signal_is_dropped_not_filled(tmp_path):
    # 无当日信号的行情日：精确匹配内连接剔除，禁止用旧信号代替
    data, manifest = _make_run(tmp_path, drop_signal_rows=1)
    df, dropped = load_window(data, manifest)
    assert dropped == ["2024-01-05"]
    assert df["temp"].notna().all()
    assert len(df) == 3


def test_window_alignment_inner(tmp_path):
    data, manifest = _make_run(tmp_path)
    df, dropped = load_window(data, manifest)
    assert len(df) == 4 and dropped == []
    assert df["temp"].notna().all()
