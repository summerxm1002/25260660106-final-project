"""阶段④自动评审的单元测试。"""
import pytest

from src.workflow.review import evaluate_acceptance


def strat(ann, mdd, shp, n):
    return {"annual_return": ann, "max_drawdown": mdd, "sharpe": shp, "n_trades": n}


BASE = strat(0.10, -0.10, 0.8, 0)


def test_all_pass():
    s = strat(0.11, -0.06, 1.0, 12)  # 年化≥10.5% 回撤≤-7% 夏普≥0.96
    r = evaluate_acceptance(s, BASE)
    assert r["overall_pass"] and r["main_ok"]
    assert all(c["ok"] for c in r["criteria"].values())


def test_mdd_criterion_direction():
    # 回撤更深（更负）必须判 FAIL：-0.09 < 0.7×-0.10=-0.07
    r = evaluate_acceptance(strat(0.11, -0.09, 1.0, 12), BASE)
    assert not r["criteria"]["max_drawdown"]["ok"]
    # 回撤更浅（-0.05 ≥ -0.07）判 PASS
    r2 = evaluate_acceptance(strat(0.11, -0.05, 1.0, 12), BASE)
    assert r2["criteria"]["max_drawdown"]["ok"]


def test_each_criterion_independent():
    assert not evaluate_acceptance(strat(0.10, -0.05, 1.0, 12), BASE)["criteria"]["annual_return"]["ok"]
    assert not evaluate_acceptance(strat(0.11, -0.05, 0.9, 12), BASE)["criteria"]["sharpe"]["ok"]
    assert not evaluate_acceptance(strat(0.11, -0.05, 1.0, 9), BASE)["criteria"]["n_trades"]["ok"]


def test_robustness_reversal_detected():
    sens = {"80": strat(0.11, -0.06, 1.0, 12), "90": strat(0.09, -0.06, 1.0, 12)}
    r = evaluate_acceptance(strat(0.11, -0.06, 1.0, 12), BASE, sens)
    assert r["robustness"]["ok"] is False
    assert not r["overall_pass"]


def test_robustness_degenerate_all_fail_flagged():
    sens = {th: strat(0.11, -0.09, 1.0, 12) for th in ("80", "90")}  # 全 FAIL 但一致
    r = evaluate_acceptance(strat(0.11, -0.09, 1.0, 12), BASE, sens)
    assert r["robustness"]["ok"] is True
    assert "退化稳健" in r["robustness"]["note"]
    assert not r["overall_pass"]


def test_robustness_none_skipped():
    r = evaluate_acceptance(strat(0.11, -0.06, 1.0, 12), BASE, None)
    assert r["robustness"]["ok"] is None
    assert r["overall_pass"]
