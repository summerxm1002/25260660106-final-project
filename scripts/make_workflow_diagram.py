"""生成 docs/workflow.png：带注释的长程智能体工作流图（设计视图）。

角色配色（Okabe-Ito 色系，色盲友好）：
  Generator=#0072B2  Executor=#009E73  Critic=#D55E00
  Human=#CC79A7      Controller/确定性门禁=#555555
重跑：python scripts/make_workflow_diagram.py
"""
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Polygon

plt.rcParams.update({
    'font.sans-serif': ['Microsoft YaHei', 'SimHei'],
    'axes.unicode_minus': False,
})

C_GEN, C_EXE, C_CRIT, C_HUM, C_CTL = '#0072B2', '#009E73', '#D55E00', '#CC79A7', '#555555'
C_GATE, C_ARROW, C_ART = '#B22222', '#555555', '#777777'

fig, ax = plt.subplots(figsize=(13.5, 10.2))
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.axis('off')


def box(x, y, w, h, title, sub='', color=C_CTL, gate=False, fill_alpha=0.10):
    p = FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                       boxstyle='round,pad=0.4,rounding_size=1.2',
                       facecolor=color, alpha=fill_alpha, edgecolor=color, lw=1.8)
    ax.add_patch(p)
    if gate:
        ax.plot([x - w / 2 + 1.2, x + w / 2 - 1.2], [y + h / 2, y - h / 2],
                color=C_GATE, lw=0.7, alpha=0.18, zorder=1)
    ax.text(x, y + (1.6 if sub else 0), title, ha='center', va='center',
            fontsize=10.5, fontweight='bold', color='#222222')
    if sub:
        ax.text(x, y - 2.2, sub, ha='center', va='center', fontsize=8, color='#444444')
    return x, y, w, h


def artifact(x, y, text):
    ax.text(x, y, text, ha='center', va='center', fontsize=7.5,
            color=C_ART, style='italic')


def arrow(x1, y1, x2, y2, label='', color=C_ARROW, lx=0, ly=0):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle='-|>', color=color, lw=1.5,
                                shrinkA=2, shrinkB=2))
    if label:
        ax.text((x1 + x2) / 2 + lx, (y1 + y2) / 2 + ly, label, fontsize=8,
                color=color, ha='center', va='center',
                bbox=dict(facecolor='white', edgecolor='none', pad=0.8))


def diamond(x, y, w, h, text, color=C_CTL):
    ax.add_patch(Polygon([(x, y + h / 2), (x + w / 2, y), (x, y - h / 2), (x - w / 2, y)],
                         closed=True, facecolor='white', edgecolor=color, lw=1.8))
    ax.text(x, y, text, ha='center', va='center', fontsize=9, fontweight='bold', color='#222222')


MX = 36  # 主列中心 x

# ── 触发条 ──────────────────────────────────────────────
box(MX, 95.5, 52, 4.6,
    '触发：手动发起新迭代 ｜ 未达标自动修订（≤5 轮） ｜ 新数据到达自动复核',
    color=C_CTL)

# ── 主列 ────────────────────────────────────────────────
box(MX, 87.5, 30, 6.2, '① 提出假设', 'Generator 生成 v(k) 假设与修订动机\n（只读历史 run，仅可写 inbox/）', C_GEN)
box(MX, 78.5, 26, 5.2, 'H1 门禁：结构性改则？', '人工批准（参数微调免批）', C_HUM, gate=True)
box(MX, 69.5, 30, 6.2, '② 取数与校验', 'Executor：akshare 后复权日线 + 信号 xlsx\nas_of 校验 · 上市日自动确认 · 快照+SHA-256', C_EXE)
box(MX, 59.5, 30, 6.2, '③ 回测执行', 'Executor：只读快照（禁联网）\n单阈值择时模拟 t 判定 / t+1 执行', C_EXE)
box(MX, 49.5, 30, 6.2, '④ 自动评审（确定性）', 'Controller：五条验收标准数值判定\n+ 阈值 ±5 敏感性扫描', C_CTL)
diamond(MX, 40, 24, 9.5, '数值达标？')
box(MX, 28.5, 30, 6.2, '⑤ 评审门槛', 'Critic 独立评审（只读·无网络·隔离上下文）\nController 代录 verdict（PASS/FAIL/ESCALATE）', C_CRIT)
diamond(MX, 18.5, 22, 9, '通过？')

# ── 左侧：修订回路 ──────────────────────────────────────
box(8.5, 40, 13, 9, '⑥ 修订', 'Generator\n引用上轮裁决\n生成 v(k+1)', C_GEN)
ax.text(8.5, 30.5, '迭代计数 n ≤ 5\n（Controller 硬计数）', ha='center', fontsize=8, color=C_GATE)

# ── 右侧：终局 ──────────────────────────────────────────
box(73, 19.5, 22, 7.5, 'H2 人工终局验收', '批准 → 定稿 / 否决 → 终止\n如实输出未通过原因', C_HUM, gate=True)
box(73, 9.5, 22, 6.5, '定稿与归档', 'champion.json 更新\n三件套+报告 git 提交', C_CTL)
ax.text(94, 40, 'ESCALATE\n（疑似未来函数/\n数据完整性问题）\n→ 立即停全链', ha='center', fontsize=8, color=C_GATE)

# ── 箭头：主列 ──────────────────────────────────────────
arrow(MX, 93.2, MX, 90.8)
arrow(MX, 84.4, MX, 81.2)
arrow(MX, 75.9, MX, 72.7)
arrow(MX, 66.4, MX, 62.7)
arrow(MX, 56.4, MX, 52.7)
arrow(MX, 46.4, MX, 44.9)
arrow(MX, 35.2, MX, 31.7)
arrow(MX, 25.4, MX, 23.1)

# ── 箭头：分支 ──────────────────────────────────────────
arrow(MX - 12, 40, 15.2, 40, '否', C_GATE, ly=1.8)          # 数值不达标 → ⑥
arrow(8.5, 44.8, 8.5, 87.5, color=C_ARROW)                   # ⑥ 上行
arrow(15.2, 87.5, MX - 15.2, 87.5, color=C_ARROW)            # 汇入①
arrow(MX - 11, 18.5, 62, 19.5, 'PASS', '#1a7a1a', ly=1.8)    # 通过 → H2
arrow(MX - 11, 18.4, 14.5, 32.2, 'FAIL', C_GATE, lx=-1.5, ly=-2)  # 未过 → ⑥
arrow(73, 15.7, 73, 12.9, color=C_ARROW)                     # H2 → 归档
arrow(MX + 11, 40.8, 88, 43.5, color=C_GATE)                 # ESCALATE 支路

# ── 产物标注 ────────────────────────────────────────────
artifact(MX + 19.5, 87.5, 'inbox/hypothesis.json')
artifact(MX + 19.5, 69.5, 'data/ 快照+哈希+as_of')
artifact(MX + 19.5, 59.5, 'trades.csv / equity.csv')
artifact(MX + 19.5, 49.5, 'metrics.json + sensitivity/')
artifact(MX + 19.5, 28.5, 'auto_review.json + critic_verdict.md')

# ── 中断恢复注记 ────────────────────────────────────────
ax.text(64, 65, '断点续跑：每阶段完成即检查点\n（tmp 原子改名）；恢复时按\n输入哈希跳过已完成阶段',
        fontsize=8, color='#333333',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='#FFF8DC', edgecolor='#C8B560', lw=0.8))

# ── 运行限制面板 ────────────────────────────────────────
ax.text(93.5, 82, '运行限制', fontsize=9.5, fontweight='bold', ha='center')
limits = ['迭代 ≤ 5 轮', 'LLM 预算：G≤5 / C≤3 次', '阶段超时 120–600s', 'run 时间盒 30 min',
          '网络仅 ② 开放', 'Critic 只读无网', '同因失败 ×2 → 升级人工']
for i, t in enumerate(limits):
    ax.text(93.5, 78.6 - i * 2.6, '· ' + t, fontsize=7.8, ha='center', color='#333333')

# ── 图例 ────────────────────────────────────────────────
lg_y = 0.6
legend_items = [('Generator（提议假设）', C_GEN), ('Executor（确定性计算）', C_EXE),
                ('Critic（独立评审）', C_CRIT), ('Human（人工门禁）', C_HUM),
                ('Controller / 确定性门禁', C_CTL)]
x0 = 2.5
ax.text(x0, lg_y + 2.8, '图例：', fontsize=8.5, fontweight='bold', va='center')
for i, (name, c) in enumerate(legend_items):
    xx = x0 + 6.5 + i * 17.0
    ax.add_patch(FancyBboxPatch((xx, lg_y + 1.9), 2.6, 1.7, boxstyle='round,pad=0.15',
                                facecolor=c, alpha=0.25, edgecolor=c, lw=1.2))
    ax.text(xx + 3.2, lg_y + 2.8, name, fontsize=7.6, va='center', color='#333333')
ax.text(x0, lg_y - 0.7, '红框斜纹 = 门禁/人工批准　｜　italic 灰字 = 产物落盘　｜　FAIL 沿左侧回路修订（n≤5），PASS 走右侧终局',
        fontsize=7.5, color='#555555', va='center')

# ── 标题与脚注 ──────────────────────────────────────────
ax.set_title('红利低波50ETF（515450）温度计择时策略研究——长程智能体工作流（设计视图）',
             fontsize=13, fontweight='bold', pad=14)
fig.text(0.01, 0.012,
         '注：本图为设计视图（非运行数据）；角色职责、状态库结构与 as_of 机制详见 docs/DESIGN.md；'
         '任务定义见 docs/plans/task.md。脚本：scripts/make_workflow_diagram.py',
         fontsize=7.5, color='#666666')

fig.savefig('docs/workflow.png', dpi=300, bbox_inches='tight', facecolor='white')
plt.close(fig)
print('saved docs/workflow.png')
