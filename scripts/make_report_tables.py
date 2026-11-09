"""由三个 run 的 metrics.json 生成报告表格（booktabs tabular，无标题注释）。

产出 docs/final_report/tables/{key_data,acceptance,iterations}.tex；
caption/来源注记在 docs/final_report/sections/ 中撰写（latex 技能规范）。
重跑：python scripts/make_report_tables.py
"""
import json
from pathlib import Path

OUT = Path("docs/final_report/tables")
OUT.mkdir(parents=True, exist_ok=True)


def load(run):
    return json.loads(Path(f"runs/{run}/result/metrics.json")
                      .read_text(encoding="utf-8"))


m2 = load("run-002")
s2, b2, a2 = m2["strategy"], m2["baseline"], m2["acceptance"]
m1, m3 = load("run-001"), load("run-003")


def pct(x, nd=2):
    return f"{x * 100:.{nd}f}\\%"


# ── 表1 关键数据（侧栏）────────────────────────────────────
(OUT / "key_data.tex").write_text(
    "\\begin{tabular}{lcc}\n"
    "\\toprule\n"
    "指标 & v2 策略 & 买入持有 \\\\\n"
    "\\midrule\n"
    f"年化收益 & {pct(s2['annual_return'])} & {pct(b2['annual_return'])} \\\\\n"
    f"最大回撤 & {pct(s2['max_drawdown'])} & {pct(b2['max_drawdown'])} \\\\\n"
    f"夏普（rf=0） & {s2['sharpe']:.3f} & {b2['sharpe']:.3f} \\\\\n"
    f"累计净值 & {s2['total_return'] + 1:.3f} & {b2['total_return'] + 1:.3f} \\\\\n"
    f"交易次数 & {s2['n_trades']} & --- \\\\\n"
    "\\bottomrule\n"
    "\\end{tabular}\n", encoding="utf-8")

# ── 表2 验收对照（全宽）────────────────────────────────────
row1 = ("1 年化收益 & $\\geq$基线$\\times$1.05 & " + pct(b2['annual_return'])
        + " & $\\geq$" + pct(a2['annual_threshold']) + " $\\to$ "
        + pct(s2['annual_return']) + " & 达标 \\\\")
row2 = ("2 最大回撤 & $\\leq$基线$\\times$0.7 & " + pct(b2['max_drawdown'])
        + " & $\\leq$" + pct(a2['mdd_limit']) + " $\\to$ "
        + pct(s2['max_drawdown']) + " & {\\color{red}未达标} \\\\")
row3 = ("3 夏普比率 & $\\geq$基线$\\times$1.2 & " + f"{b2['sharpe']:.4f}"
        + " & $\\geq$" + f"{a2['sharpe_threshold']:.4f}"
        + " $\\to$ " + f"{s2['sharpe']:.4f}" + " & 达标 \\\\")
row4 = f"4 交易次数 & $\\geq$ 10 & --- & {s2['n_trades']} & 达标 \\\\"
row5 = ("5 稳健性 & 阈值$\\pm$5 结论不反转 & ---"
        " & 75--85 五组同判未通过（退化） & 字面达标/实质存疑 \\\\")
row6 = ("\\multicolumn{5}{l}{综合：五条须全部通过 $\\to$"
        " {\\color{red}未通过（4/5），如实呈现，不放宽标准}} \\\\")
(OUT / "acceptance.tex").write_text(
    "\\begin{tabular}{llllc}\n\\toprule\n"
    "标准 & 要求 & 基线 & 实际 & 判定 \\\\\n\\midrule\n"
    + "\n".join([row1, row2, row3, row4, row5])
    + "\n\\midrule\n" + row6 + "\n\\bottomrule\n\\end{tabular}\n", encoding="utf-8")

# ── 表3 三轮迭代历程（全宽）────────────────────────────────
rows = [
    ("run-001 / v1", "单阈值 85", m1, "未达标（回撤）", "指标只逃顶不防熊"),
    ("run-002 / v2", "阈值 85$\\to$80", m2, "未达标（回撤）", "调参无解：75--85 回撤全部相同"),
    ("run-003 / v3", "+MA200 趋势过滤", m3, "未达标（第1/2/3条）",
     "趋势过滤对低波均值回复品种方向性有害；champion 约束否决"),
]
body = ""
for name, desc, m, verdict, lesson in rows:
    sm = m["strategy"]
    body += (f"{name} & {desc} & {pct(sm['annual_return'])}/{pct(sm['max_drawdown'])}"
             f"/{sm['sharpe']:.3f} & {sm['n_trades']} & {verdict} & {lesson} \\\\\n")
(OUT / "iterations.tex").write_text(
    "\\begin{tabular}{llcccp{3.6cm}}\n"
    "\\toprule\n"
    "run / 假设 & 规则改动 & 年化/回撤/夏普 & 交易 & 门禁判定 & 被证实/证伪的设计知识 \\\\\n"
    "\\midrule\n"
    + body +
    "\\bottomrule\n"
    "\\end{tabular}\n", encoding="utf-8")

print("saved docs/final_report/tables/{key_data,acceptance,iterations}.tex")
