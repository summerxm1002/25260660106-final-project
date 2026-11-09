"""终局报告三图：净值对比 / 回撤对照 / 温度计与交易点。

数据源：runs/run-002（champion v2，阈值 80）的产物，全部只读。
重跑：python scripts/make_final_figures.py
"""
import matplotlib.pyplot as plt
import pandas as pd

plt.rcParams.update({
    'font.sans-serif': ['Microsoft YaHei', 'SimHei'],
    'axes.unicode_minus': False,
    'figure.dpi': 100, 'savefig.dpi': 300, 'savefig.bbox': 'tight',
    'font.size': 10, 'axes.titlesize': 12, 'axes.labelsize': 10,
    'axes.spines.top': False, 'axes.spines.right': False,
    'lines.linewidth': 1.8, 'legend.frameon': False,
})
C_STRAT, C_BASE, C_TEMP, C_BUY, C_SELL = '#0072B2', '#999999', '#D55E00', '#009E73', '#D55E00'
SRC_NOTE = ('数据：run-002 快照（信号截至 2026-08-12，后复权行情）'
            '；来源：自制温度计指标 + akshare/东方财富；as of 2026-08-12')

eq = pd.read_csv('runs/run-002/result/equity.csv', encoding='utf-8-sig')
eq['date'] = pd.to_datetime(eq['date'])
tr = pd.read_csv('runs/run-002/result/trades.csv', encoding='utf-8-sig')
tr['date'] = pd.to_datetime(tr['date'])
sig = pd.read_csv('runs/run-002/data/signal.csv', encoding='utf-8-sig')
sig.columns = ['date', 'temp']
sig['date'] = pd.to_datetime(sig['date'])
sig = sig[(sig['date'] >= eq['date'].min()) & (sig['date'] <= eq['date'].max())]

# ── fig1 净值对比（对数轴）────────────────────────────────
fig, ax = plt.subplots(figsize=(8, 4.2), constrained_layout=True)
ax.plot(eq['date'], eq['strategy_equity'], color=C_STRAT, label='v2 策略（阈值 80）')
ax.plot(eq['date'], eq['baseline_equity'], color=C_BASE, label='买入持有基线', lw=1.4)
ax.set_yscale('log')
ax.set_yticks([1.0, 1.2, 1.5, 2.0])
ax.set_yticklabels(['1.00', '1.20', '1.50', '2.00'])
ax.set_ylabel('净值（起点 = 1，对数轴）')
ax.set_title('v2 策略与买入持有净值对比（2020-02-26 ~ 2026-08-12）')
for x, t in [('2020-07-07', '逃顶①'), ('2021-02-26', '逃顶②'), ('2023-05-05', '逃顶③'), ('2024-09-30', '逃顶④')]:
    ax.axvline(pd.Timestamp(x), color=C_SELL, ls=':', lw=1, alpha=0.6)
    ax.annotate(t, xy=(pd.Timestamp(x), ax.get_ylim()[1]), xytext=(2, -12),
                textcoords='offset points', fontsize=8, color=C_SELL)
ax.axvspan(pd.Timestamp('2022-02-11'), pd.Timestamp('2022-10-31'), color='#CC79A7', alpha=0.12)
ax.annotate('2022 慢熊：温度计全程≤85\n策略满仓穿越（-13.87%，未达标区间）',
            xy=(pd.Timestamp('2022-06-20'), 1.12), fontsize=8, color='#8B3A62', ha='center')
ax.legend(loc='lower right')
fig.text(0.01, -0.02, SRC_NOTE + '；成本：佣金单边万 3 双边。', fontsize=8, color='#666666')
fig.savefig('docs/figures/fig1_equity.png', facecolor='white')
plt.close(fig)

# ── fig2 回撤对照 ─────────────────────────────────────────
fig, ax = plt.subplots(figsize=(8, 3.2), constrained_layout=True)
for col, c, lb in [('strategy_equity', C_STRAT, 'v2 策略'), ('baseline_equity', C_BASE, '买入持有')]:
    dd = eq[col] / eq[col].cummax() - 1
    ax.plot(eq['date'], dd * 100, color=c, label=lb, lw=1.5)
ax.axhline(-9.71, color=C_SELL, ls='--', lw=1)
ax.annotate('验收上限 = 基线回撤×0.7 = -9.71%', xy=(eq['date'].iloc[30], -9.71),
            xytext=(0, 4), textcoords='offset points', fontsize=8, color=C_SELL)
ax.axvspan(pd.Timestamp('2022-02-11'), pd.Timestamp('2022-10-31'), color='#CC79A7', alpha=0.12)
ax.annotate('两者回撤重合（-13.87%）', xy=(pd.Timestamp('2022-06-20'), -13.2),
            fontsize=8, color='#8B3A62', ha='center')
ax.set_ylabel('回撤（%）')
ax.set_title('回撤对照：策略未能削减买入持有的最大回撤')
ax.legend(loc='lower left')
fig.text(0.01, -0.02, SRC_NOTE + '。', fontsize=8, color='#666666')
fig.savefig('docs/figures/fig2_drawdown.png', facecolor='white')
plt.close(fig)

# ── fig3 温度计与交易点 ───────────────────────────────────
fig, ax = plt.subplots(figsize=(8, 4.2), constrained_layout=True)
ax.plot(sig['date'], sig['temp'], color=C_TEMP, lw=1.2, label='温度计总值')
ax.axhline(80, color=C_SELL, ls='--', lw=1)
ax.annotate('阈值 80（上方清仓 / 下方满仓）', xy=(pd.Timestamp('2023-09-01'), 80),
            xytext=(0, 4), textcoords='offset points', fontsize=8, color=C_SELL)
buys = tr[tr['side'] == 'BUY']
sells = tr[tr['side'] == 'SELL']
sig_idx = sig.set_index('date')['temp']
ax.scatter(buys['date'], [sig_idx.get(d, 5) for d in buys['date']],
           marker='^', color=C_BUY, s=45, zorder=5, label='买入（t+1 执行）')
ax.scatter(sells['date'], [sig_idx.get(d, 95) for d in sells['date']],
           marker='v', color=C_SELL, s=45, zorder=5, label='卖出（t+1 执行）')
ax.set_ylim(-5, 108)
ax.set_ylabel('温度计总值（0-100）')
ax.set_title('温度计信号与 v2 交易点：逃顶有效、防熊缺位')
ax.legend(loc='upper left', ncols=3, fontsize=8)
fig.text(0.01, -0.02, SRC_NOTE + '；买卖点为 run-002 实际成交（19 笔）。', fontsize=8, color='#666666')
fig.savefig('docs/figures/fig3_temp_trades.png', facecolor='white')
plt.close(fig)

print('saved docs/figures/fig1_equity.png fig2_drawdown.png fig3_temp_trades.png')
