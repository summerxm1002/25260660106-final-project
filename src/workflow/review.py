"""阶段④自动评审（确定性门禁）。

对照 task.md §6 五条验收标准逐条数值判定，产出 review/auto_review.json。
LLM 无权修改判定结果（DESIGN §2.3：数值门槛一票否决）。
阈值稳健性：±5 范围内各阈值的"整体判定"须与 v1 一致（结论不反转）；
若全部阈值同判 FAIL，标注"退化稳健"供 Critic 讨论。

CLI:
    python -m src.workflow.review --run-dir runs/run-001
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

N_TRADES_MIN = 10
ANNUAL_MULT = 1.05
MDD_MULT = 0.7
SHARPE_MULT = 1.2


def evaluate_acceptance(strategy: dict, baseline: dict,
                        sensitivity: dict | None = None) -> dict:
    """五条验收标准逐条判定。strategy/baseline 为 metrics 字典。"""
    s_ann, b_ann = strategy["annual_return"], baseline["annual_return"]
    s_mdd, b_mdd = strategy["max_drawdown"], baseline["max_drawdown"]
    s_shp, b_shp = strategy["sharpe"], baseline["sharpe"]

    criteria = {
        "annual_return": {"actual": s_ann, "threshold": round(ANNUAL_MULT * b_ann, 6),
                          "ok": bool(s_ann >= ANNUAL_MULT * b_ann)},
        "max_drawdown": {"actual": s_mdd, "limit": round(MDD_MULT * b_mdd, 6),
                         "ok": bool(s_mdd >= MDD_MULT * b_mdd)},
        "sharpe": {"actual": s_shp, "threshold": round(SHARPE_MULT * b_shp, 4),
                   "ok": bool(s_shp >= SHARPE_MULT * b_shp)},
        "n_trades": {"actual": strategy.get("n_trades", 0),
                     "min": N_TRADES_MIN,
                     "ok": bool(strategy.get("n_trades", 0) >= N_TRADES_MIN)},
    }
    main_ok = all(c["ok"] for c in criteria.values())

    robustness = {"ok": None, "note": None, "per_threshold": {}}
    if sensitivity:
        verdicts = {}
        for th, m in sensitivity.items():
            sub = evaluate_acceptance(m, baseline, None)
            verdicts[th] = all(c["ok"] for c in sub["criteria"].values())
            robustness["per_threshold"][th] = {
                "annual": m["annual_return"], "mdd": m["max_drawdown"],
                "sharpe": m["sharpe"], "n_trades": m.get("n_trades", 0),
                "all_ok": verdicts[th]}
        same = len(set(verdicts.values())) == 1
        robustness["ok"] = bool(same)
        robustness["note"] = ("退化稳健：全部阈值同判 FAIL，'不反转'无信息量"
                              if same and not all(verdicts.values())
                              else ("各阈值判定一致（PASS）" if same
                                    else "判定反转，稳健性不成立"))

    overall = main_ok and (robustness["ok"] in (None, True))
    return {"criteria": criteria, "main_ok": main_ok,
            "robustness": robustness, "overall_pass": bool(overall)}


def run_auto_review(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    metrics = json.loads((run_dir / "result" / "metrics.json")
                         .read_text(encoding="utf-8"))
    review = evaluate_acceptance(metrics["strategy"], metrics["baseline"],
                                 metrics.get("sensitivity"))
    out = {
        "run_id": metrics["run_id"],
        "hypothesis_id": metrics["hypothesis_id"],
        "threshold": metrics["threshold"],
        "window": metrics["window"],
        "rule": ("收益/回撤/夏普 同快照同口径对照买入持有基线；"
                 "交易次数与阈值稳健性为绝对/相对标准"),
        "acceptance": review,
        "verdict": "PASS" if review["overall_pass"] else "FAIL",
    }
    review_dir = run_dir / "review"
    review_dir.mkdir(exist_ok=True)
    path = review_dir / "auto_review.json.tmp"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    path.replace(review_dir / "auto_review.json")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="阶段④自动评审（确定性门禁）")
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args()
    out = run_auto_review(Path(args.run_dir))
    print(json.dumps({"verdict": out["verdict"],
                      "main_ok": out["acceptance"]["main_ok"],
                      "criteria": {k: v["ok"] for k, v in
                                   out["acceptance"]["criteria"].items()},
                      "robustness": out["acceptance"]["robustness"]["ok"],
                      "robustness_note": out["acceptance"]["robustness"]["note"]},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
