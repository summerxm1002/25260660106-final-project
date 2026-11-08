"""阶段②取数与校验（Executor）。

职责（DESIGN.md §3.1 / §4.7）：
- 从 data/raw/ 信号 xlsx 抽取温度计序列，落 signal.csv 快照（原件只读）；
- 用 akshare 拉 sh515450 后复权日线，落 price_hfq.csv 快照；
- 自动确认上市日期；回测窗口 = [max(上市日, 信号首日), min(信号末日, 行情末日, 用户 as_of)]；
- snapshot_manifest.json 记录各快照 SHA-256、as_of、上市日确认来源；
- 数据质量报告（data_quality.json）：缺口/跳变/as_of 检查，预期内特征只报告不报错。

仅本模块允许网络访问。CLI:
    python -m src.workflow.fetch --run-dir runs/run-001 [--asof 2026-08-12]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_SIGNAL_XLSX = Path("data/raw/红利低波50ETF择时信号.xlsx")
ETF_SYMBOL = "515450"  # akshare fund_etf_hist_em 用纯数字代码（sh515450）
SIGNAL_DATE_COL = "DateTime"
SIGNAL_VALUE_COL = "温度计总值"

# 数据质量阈值
GAP_NORMAL_BDAY = 3      # 超过此工作日间隔记为缺口（节假日属预期内）
GAP_ESCALATE_BDAY = 10   # 超过此工作日间隔才升级人工（H3）
JUMP_ABS_THRESH = 0.04   # 单日 |收益率| 超 4% 视为候选跳变
JUMP_REL_MULT = 4.0      # 且超过滚动窗口 std 的 4 倍才报告（自适应波动率）


class AsOfError(ValueError):
    """as_of 校验失败：信号与行情窗口无交集或用户 as_of 早于窗口起点。"""


@dataclass
class QualityReport:
    """数据质量报告：只记录不阻断（as_of 无交集除外，抛 AsOfError）。"""
    gaps_signal: list[dict] = field(default_factory=list)
    gaps_price: list[dict] = field(default_factory=list)
    jumps_price: list[dict] = field(default_factory=list)
    asof_status: str = "OK"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "gaps_signal": self.gaps_signal,
            "gaps_price": self.gaps_price,
            "jumps_price": self.jumps_price,
            "asof_status": self.asof_status,
            "escalate": any(g["missing_bdays"] > GAP_ESCALATE_BDAY
                            for g in self.gaps_signal + self.gaps_price),
            "notes": self.notes,
        }


# ---------------------------------------------------------------- 纯函数（可单测）

def find_gaps(dates: list[date], max_normal_bday: int = GAP_NORMAL_BDAY) -> list[dict]:
    """列出相邻日期间隔超过 max_normal_bday 个工作日的缺口。"""
    gaps = []
    ds = pd.to_datetime(sorted(dates)).normalize()
    for prev, curr in zip(ds[:-1], ds[1:]):
        bdays = int(np.busday_count(prev.date(), curr.date()))
        if bdays > max_normal_bday:
            gaps.append({"from": prev.date().isoformat(),
                         "to": curr.date().isoformat(),
                         "missing_bdays": bdays})
    return gaps


def detect_jumps(dates: list[date], values: list[float],
                 abs_thresh: float = JUMP_ABS_THRESH,
                 rel_mult: float = JUMP_REL_MULT,
                 window: int = 20) -> list[dict]:
    """自适应跳变检测：|ret| 超绝对阈值且超 rolling-std×rel_mult 才报告。"""
    s = pd.Series(values, index=pd.to_datetime(dates), dtype=float).sort_index()
    ret = s.pct_change()
    roll_std = ret.rolling(window, min_periods=5).std()
    hit = ret.abs().gt(abs_thresh) & ret.abs().gt(rel_mult * roll_std)
    return [{"date": d.date().isoformat(), "ret": round(float(ret[d]), 4),
             "rolling_std": round(float(roll_std[d]), 4)}
            for d in ret.index[hit.fillna(False)]]


def resolve_window(signal_start: date, signal_end: date,
                   price_start: date, price_end: date,
                   user_asof: date | None = None) -> dict:
    """计算回测窗口并返回裁切标志。无交集抛 AsOfError。"""
    start = max(signal_start, price_start)
    end = min(signal_end, price_end)
    flags = []
    if price_end > signal_end:
        flags.append("行情覆盖超出信号末日，窗口已按信号末日裁切（防未来信息泄露）")
    elif price_end < signal_end:
        flags.append("行情末日早于信号末日（行情源滞后），窗口按行情末日截断")
    if user_asof is not None:
        end = min(end, user_asof)
        flags.append(f"用户 as_of {user_asof.isoformat()} 已生效")
    if end < start:
        raise AsOfError(
            f"窗口无交集：信号[{signal_start},{signal_end}] "
            f"行情[{price_start},{price_end}] as_of={user_asof}")
    return {"window_start": start, "window_end": end, "flags": flags}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- IO 与组装

def load_signal(xlsx_path: Path = DEFAULT_SIGNAL_XLSX) -> pd.DataFrame:
    """读取温度计 xlsx：按日期排序，重复/缺失即报错（数据完整性问题）。"""
    df = pd.read_excel(xlsx_path)
    missing = {SIGNAL_DATE_COL, SIGNAL_VALUE_COL} - set(df.columns)
    if missing:
        raise ValueError(f"信号文件缺少列: {missing}（实际列: {list(df.columns)}）")
    df = df[[SIGNAL_DATE_COL, SIGNAL_VALUE_COL]].copy()
    df[SIGNAL_DATE_COL] = pd.to_datetime(df[SIGNAL_DATE_COL]).dt.normalize()
    if df[SIGNAL_DATE_COL].duplicated().any():
        dups = df.loc[df[SIGNAL_DATE_COL].duplicated(), SIGNAL_DATE_COL].dt.date.tolist()
        raise ValueError(f"信号文件存在重复日期: {dups[:5]}...")
    if df[SIGNAL_VALUE_COL].isna().any():
        raise ValueError("信号文件存在缺失值")
    return df.sort_values(SIGNAL_DATE_COL).reset_index(drop=True)


def fetch_price_hfq(symbol: str = ETF_SYMBOL) -> pd.DataFrame:
    """akshare 拉后复权日线。网络访问仅允许出现在本函数。"""
    import akshare as ak  # 延迟导入：测试与回测阶段不依赖网络
    df = ak.fund_etf_hist_em(symbol=symbol, period="daily", adjust="hfq")
    df = df.rename(columns={"日期": "date"})
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    keep = ["date", "open", "close", "high", "low", "volume", "amount"]
    df = df.rename(columns={"开盘": "open", "收盘": "close", "最高": "high",
                            "最低": "low", "成交量": "volume", "成交额": "amount"})
    return df[[c for c in keep if c in df.columns]].sort_values("date").reset_index(drop=True)


def _write_csv_atomic(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(path)  # 原子改名，避免半个快照


def run_fetch(run_dir: Path, signal_xlsx: Path = DEFAULT_SIGNAL_XLSX,
              user_asof: date | None = None) -> dict:
    """阶段②完整执行：抽取+拉取+校验+落盘，返回 manifest 内容。"""
    run_dir = Path(run_dir)
    data_dir = run_dir / "data"
    tmp_dir = run_dir / "tmp"
    data_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # 1) 信号快照（原件只读）
    signal = load_signal(signal_xlsx)
    signal_path = tmp_dir / "signal.csv"
    _write_csv_atomic(signal, signal_path)

    # 2) 行情快照（hfq），上市日自动确认 = 行情首日
    price = fetch_price_hfq()
    price_path = tmp_dir / "price_hfq.csv"
    _write_csv_atomic(price, price_path)
    listing_date = price["date"].min().date()
    listing_source = (f"akshare fund_etf_hist_em(symbol={ETF_SYMBOL}, adjust=hfq) "
                      f"首日 {listing_date.isoformat()}（自动确认）")

    # 3) as_of 与窗口
    signal_start = signal[SIGNAL_DATE_COL].min().date()
    signal_end = signal[SIGNAL_DATE_COL].max().date()
    price_start = price["date"].min().date()
    price_end = price["date"].max().date()
    win = resolve_window(signal_start, signal_end, price_start, price_end, user_asof)

    # 4) 数据质量报告（预期内特征只记录）
    q = QualityReport(
        gaps_signal=find_gaps(signal[SIGNAL_DATE_COL].tolist()),
        gaps_price=find_gaps(price["date"].tolist()),
        jumps_price=detect_jumps(price["date"].tolist(), price["close"].tolist()),
    )
    q.notes.extend(win["flags"])
    if q.jumps_price:
        q.notes.append(f"后复权价存在 {len(q.jumps_price)} 个候选跳变，"
                       f"除息/除权已用复权处理，跳变多为极端行情，人工复核即可")
    q.asof_status = "OK"

    # 5) manifest + 质量报告落盘，tmp 原子归档
    manifest = {
        "run_id": run_dir.name,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "files": {
            "signal.csv": {"sha256": sha256_file(signal_path),
                           "rows": int(len(signal))},
            "price_hfq.csv": {"sha256": sha256_file(price_path),
                              "rows": int(len(price))},
        },
        "as_of": {
            "signal_start": signal_start.isoformat(),
            "signal_end": signal_end.isoformat(),
            "price_start": price_start.isoformat(),
            "price_end": price_end.isoformat(),
            "window_start": win["window_start"].isoformat(),
            "window_end": win["window_end"].isoformat(),
            "user_asof": user_asof.isoformat() if user_asof else None,
        },
        "listing": {"date": listing_date.isoformat(), "source": listing_source},
        "data_quality": "data_quality.json",
    }
    (tmp_dir / "data_quality.json").write_text(
        json.dumps(q.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    (tmp_dir / "snapshot_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    for name in ("signal.csv", "price_hfq.csv", "data_quality.json",
                 "snapshot_manifest.json"):
        (tmp_dir / name).replace(data_dir / name)
    tmp_dir.rmdir()

    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description="阶段②取数与校验")
    ap.add_argument("--run-dir", required=True, help="run 目录，如 runs/run-001")
    ap.add_argument("--signal-xlsx", default=str(DEFAULT_SIGNAL_XLSX))
    ap.add_argument("--asof", default=None, help="用户 as_of，YYYY-MM-DD")
    args = ap.parse_args()
    asof = date.fromisoformat(args.asof) if args.asof else None
    manifest = run_fetch(Path(args.run_dir), Path(args.signal_xlsx), asof)
    print(json.dumps({"manifest": "ok",
                      "window": manifest["as_of"]["window_start"] + " ~ "
                                + manifest["as_of"]["window_end"],
                      "listing": manifest["listing"],
                      "files": manifest["files"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
