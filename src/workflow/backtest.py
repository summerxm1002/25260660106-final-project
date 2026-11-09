"""阶段③回测执行（Executor）。

职责（DESIGN.md §3.1 / task.md §2/§3）：
- 只读 run 的数据快照（回测前复核对 snapshot_manifest.json 的 SHA-256，不符即拒绝）；
- 信号生成：t 日收盘温度计 > 阈值 → 目标清仓，≤ 阈值 → 目标满仓；
- 模拟撮合：t 日判定，t+1 收盘执行；佣金单边万 3 双边计提；起点 ≤ 阈值立即满仓；
- 绩效指标与买入持有基线同快照、同窗口、同口径计算；
- 阈值敏感性扫描（±5，5 组）落 result/sensitivity/；
- 产出 trades.csv / equity.csv / metrics.json。

CLI:
    python -m src.workflow.backtest --run-dir runs/run-001 [--threshold 85]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.workflow.fetch import sha256_file

TRADING_DAYS = 252
SENSITIVITY_STEPS = (-5.0, -2.5, 0.0, 2.5, 5.0)  # 阈值 ±5 共 5 组


class SnapshotError(RuntimeError):
    """快照完整性校验失败：拒绝回测。"""


# ---------------------------------------------------------------- 纯函数（可单测）

def generate_targets(temp: list[float], threshold: float,
                     enter_at_start: bool = True) -> list[int]:
    """t 日收盘判定：≤ 阈值 → 1（满仓），> 阈值 → 0（清仓）。"""
    return [0 if (t > threshold) else 1 for t in temp]


def generate_targets_ma(temp: list[float], close: list[float],
                        ma: list[float], threshold: float) -> list[int]:
    """v3 双确认：均线可计算时，温度 ≤ 阈值 且 收盘 ≥ 均线 → 满仓，否则清仓；
    均线不足 min_periods 的日期（NaN）仅温度计条件生效。"""
    targets = []
    for t, c, m in zip(temp, close, ma):
        if np.isnan(m):
            targets.append(0 if t > threshold else 1)
        else:
            targets.append(1 if (t <= threshold and c >= m) else 0)
    return targets


def simulate(dates, closes, targets, commission: float, enter_at_start: bool = True) -> pd.DataFrame:
    """t 日判定 → t+1 收盘执行的权益模拟。

    exec_pos[i] = 第 i 日收盘起持有的仓位（interval i→i+1 的收益率归它）：
      exec_pos[0] = targets[0]（起点立即执行）；exec_pos[i] = targets[i-1]（i≥1）。
    交易成本在执行日按 |Δ仓位| × commission 计提。
    """
    n = len(closes)
    exec_pos = np.zeros(n, dtype=int)
    exec_pos[0] = targets[0] if enter_at_start else 0
    for i in range(1, n):
        exec_pos[i] = targets[i - 1]
    ret = np.zeros(n)
    ret[1:] = closes[1:] / closes[:-1] - 1.0
    cost = np.zeros(n)
    cost[0] = exec_pos[0] * commission  # 起点建仓成本
    prev = exec_pos[0]
    for i in range(1, n):
        cost[i] = abs(exec_pos[i] - prev) * commission
        prev = exec_pos[i]
    equity = np.empty(n)
    equity[0] = 1.0 - cost[0]  # 起点建仓佣金直接从本金扣
    for i in range(1, n):
        equity[i] = equity[i - 1] * (1.0 + exec_pos[i - 1] * ret[i] - cost[i])
    return pd.DataFrame({
        "date": pd.to_datetime(dates),
        "close": closes,
        "exec_position": exec_pos,
        "strategy_ret": np.concatenate([[-cost[0]], exec_pos[:-1] * ret[1:] - cost[1:]]),
        "strategy_equity": equity,
        "baseline_equity": closes / closes[0],
    })


def extract_trades(sim: pd.DataFrame, commission: float) -> pd.DataFrame:
    """从持仓变化还原成交明细（每次执行 = 一笔，含起点建仓）。"""
    rows = []
    prev = 0
    for _, r in sim.iterrows():
        pos = int(r["exec_position"])
        if pos != prev:
            rows.append({
                "date": r["date"].date().isoformat(),
                "side": "BUY" if pos > prev else "SELL",
                "price": round(float(r["close"]), 6),
                "turnover_frac": abs(pos - prev),
                "commission": round(abs(pos - prev) * commission, 8),
                "position_after": pos,
            })
            prev = pos
    return pd.DataFrame(rows)


def compute_metrics(equity: pd.Series, daily_ret: pd.Series) -> dict:
    """年化（252）、最大回撤、夏普（rf=0）、总收益。输入已含成本的日收益序列。"""
    n = len(equity) - 1  # 收益区间数
    total_return = float(equity.iloc[-1] / equity.iloc[0] - 1.0)
    annual_return = float((equity.iloc[-1]) ** (TRADING_DAYS / n) - 1.0) if n > 0 else 0.0
    cummax = equity.cummax()
    max_drawdown = float((equity / cummax - 1.0).min())
    r = daily_ret.iloc[1:]
    std = float(r.std(ddof=1))
    sharpe = float(r.mean() / std * np.sqrt(TRADING_DAYS)) if std > 0 else float("nan")
    return {"total_return": round(total_return, 6),
            "annual_return": round(annual_return, 6),
            "max_drawdown": round(max_drawdown, 6),
            "sharpe": round(sharpe, 4),
            "n_days": int(n)}


# ---------------------------------------------------------------- 组装

def verify_snapshot(data_dir: Path) -> dict:
    """回测前核对快照哈希（DESIGN §4.7.2），不符拒绝运行。"""
    manifest = json.loads((data_dir / "snapshot_manifest.json").read_text(encoding="utf-8"))
    for name, info in manifest["files"].items():
        actual = sha256_file(data_dir / name)
        if actual != info["sha256"]:
            raise SnapshotError(f"{name} 哈希不符：manifest={info['sha256'][:16]}.. "
                                f"actual={actual[:16]}.. 快照被改动，拒绝回测")
    return manifest


def load_window(data_dir: Path, manifest: dict) -> tuple[pd.DataFrame, list[str]]:
    """取窗口内 信号×行情 对齐表。

    按 DateTime 精确匹配内连接（DESIGN §4.7.3：禁止前向填充信号）。
    无当日信号的行情日予以剔除（不拿旧信号代替），跨缺口收益按持仓
    区间完整计入；返回 (对齐表, 被剔除的行情日)。
    """
    signal = pd.read_csv(data_dir / "signal.csv", encoding="utf-8-sig")
    price = pd.read_csv(data_dir / "price_hfq.csv", encoding="utf-8-sig")
    signal.columns = ["date", "temp"]
    signal["date"] = pd.to_datetime(signal["date"])
    price["date"] = pd.to_datetime(price["date"])
    win = manifest["as_of"]
    lo, hi = pd.Timestamp(win["window_start"]), pd.Timestamp(win["window_end"])
    sig_w = signal[(signal["date"] >= lo) & (signal["date"] <= hi)]
    px_w = price[(price["date"] >= lo) & (price["date"] <= hi)]
    merged = px_w.merge(sig_w, on="date", how="inner")
    dropped = sorted(set(px_w["date"]) - set(sig_w["date"]))
    return merged.reset_index(drop=True), [d.date().isoformat() for d in dropped]


def run_backtest(run_dir: Path, threshold: float | None = None) -> dict:
    run_dir = Path(run_dir)
    data_dir = run_dir / "data"
    result_dir = run_dir / "result"
    sens_dir = result_dir / "sensitivity"
    result_dir.mkdir(parents=True, exist_ok=True)
    sens_dir.mkdir(parents=True, exist_ok=True)

    hypothesis = json.loads((run_dir / "hypothesis.json").read_text(encoding="utf-8"))
    th = float(threshold if threshold is not None else hypothesis["rule"]["threshold"])
    commission = float(hypothesis["cost"]["commission_bps"]) / 1e4
    enter_at_start = bool(hypothesis["rule"].get("enter_at_start", True))

    manifest = verify_snapshot(data_dir)
    df, dropped = load_window(data_dir, manifest)

    rule_type = hypothesis["rule"]["type"]
    closes = df["close"].to_numpy(float)
    if rule_type == "temp_threshold_with_ma_trend_filter":
        ma_period = int(hypothesis["rule"]["ma_period"])
        ma_min = int(hypothesis["rule"].get("ma_min_periods", ma_period))
        ma = df["close"].rolling(ma_period, min_periods=ma_min).mean().to_numpy()
        make_targets = lambda th: generate_targets_ma(
            df["temp"].tolist(), closes, ma, th)
        rule_desc = (f"温度计>{th:g} 或 收盘<MA{ma_period} 任一触发离场；"
                     f"温度≤{th:g} 且收复 MA{ma_period} 双确认回场；"
                     f"均线前 {ma_min - 1} 日仅温度计生效")
    elif rule_type == "single_threshold":
        make_targets = lambda th: generate_targets(df["temp"].tolist(), th,
                                                   enter_at_start)
        rule_desc = f"单阈值二元择时：>{th:g} 清仓，≤{th:g} 满仓"
    else:
        raise ValueError(f"未知规则类型: {rule_type}")

    targets = make_targets(th)
    sim = simulate(df["date"].tolist(), closes, targets, commission,
                   enter_at_start)
    trades = extract_trades(sim, commission)
    sm = compute_metrics(sim["strategy_equity"], sim["strategy_ret"])
    bm = compute_metrics(sim["baseline_equity"],
                         sim["baseline_equity"].pct_change().fillna(0.0))
    sm["n_trades"] = int(len(trades))
    sm["cost_total"] = float(trades["commission"].sum()) if len(trades) else 0.0

    # 阈值 ±5 敏感性（同口径）
    sens = {}
    for step in SENSITIVITY_STEPS:
        th_s = th + step
        t_s = make_targets(th_s)
        s_s = simulate(df["date"].tolist(), closes, t_s, commission,
                       enter_at_start)
        tr_s = extract_trades(s_s, commission)
        m_s = compute_metrics(s_s["strategy_equity"], s_s["strategy_ret"])
        m_s["n_trades"] = int(len(tr_s))
        sens[str(th_s)] = m_s
        (sens_dir / f"metrics_th{th_s:g}.json").write_text(
            json.dumps({"threshold": th_s, "strategy": m_s, "baseline": bm},
                       ensure_ascii=False, indent=2), encoding="utf-8")

    # 五条验收标准的对照数值（布尔判定属阶段④ auto_review，此处只给数值）
    acceptance = {
        "annual_threshold": round(1.05 * bm["annual_return"], 6),
        "annual_actual": sm["annual_return"],
        "mdd_limit": round(0.7 * bm["max_drawdown"], 6),
        "mdd_actual": sm["max_drawdown"],
        "sharpe_threshold": round(1.2 * bm["sharpe"], 4),
        "sharpe_actual": sm["sharpe"],
        "n_trades_min": 10,
        "n_trades_actual": sm["n_trades"],
        "sensitivity_thresholds": [th + s for s in SENSITIVITY_STEPS],
    }

    metrics = {
        "run_id": run_dir.name,
        "hypothesis_id": hypothesis["hypothesis_id"],
        "threshold": th,
        "window": {k: manifest["as_of"][k] for k in
                   ("window_start", "window_end")},
        "convention": {
            "rule": rule_desc,
            "execution": "t 日收盘判定，t+1 收盘执行；起点按信号立即建仓",
            "price": "后复权收盘价（hfq），分红已计入；均线同源同口径",
            "annualization": f"{TRADING_DAYS} 交易日；夏普 rf=0，日频年化",
            "cost": f"佣金单边 {hypothesis['cost']['commission_bps']}bp，双边计提，无最低/无印花税/无滑点",
            "position_sizing": "权益比例记账（等效全进全出，未按 100 股整手取整）",
            "calendar_alignment": ("按信号日历内连接：无当日信号的行情日剔除不代判"
                                   + (f"（本轮剔除 {len(dropped)} 日: {', '.join(dropped)}）"
                                      if dropped else "（本轮无剔除）")),
        },
        "strategy": sm,
        "baseline": bm,
        "acceptance": acceptance,
        "sensitivity": sens,
    }

    tmp = result_dir / "tmp"
    tmp.mkdir(exist_ok=True)
    sim.round(8).to_csv(tmp / "equity.csv", index=False, encoding="utf-8-sig")
    trades.to_csv(tmp / "trades.csv", index=False, encoding="utf-8-sig")
    (tmp / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    for name in ("equity.csv", "trades.csv", "metrics.json"):
        (tmp / name).replace(result_dir / name)
    tmp.rmdir()
    return metrics


def main() -> None:
    ap = argparse.ArgumentParser(description="阶段③回测执行")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--threshold", type=float, default=None,
                    help="覆盖假设阈值（默认用 hypothesis.json）")
    args = ap.parse_args()
    m = run_backtest(Path(args.run_dir), args.threshold)
    a = m["acceptance"]
    print(json.dumps({
        "window": m["window"],
        "strategy": m["strategy"],
        "baseline": m["baseline"],
        "acceptance": a,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
