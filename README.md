# 红利低波50ETF 温度计择时策略研究——长程智能体工作流

> 课程：金融人工智能编程 2026 秋 · 期末作业
> 作者：25级FMBA 邢敏 · 学号 25260660106
> 代码仓库：https://github.com/summerxm1002/25260660106-final-project （公开）

## 任务概述

为"红利低波50ETF（sh515450）温度计逆向择时波段交易"设计的端到端长程智能体
工作流。策略研究是周期性重复的循环：**提出假设 → 取数 → 回测 → 评审 → 修订 →
再回测**，直至通过验收标准。工作流支持持久化状态、重复评估与中断恢复，
完整定义见 `docs/plans/task.md`，架构设计见 `docs/DESIGN.md`。

## 仓库结构指引

| 路径 | 内容 |
|---|---|
| `docs/plans/task.md` | 任务定义（策略规则、回测设定、验收标准、修订预案） |
| `docs/DESIGN.md` | 架构设计（角色与交接、状态库、核验与改进机制） |
| `docs/workflow.png` | 带注释的工作流图（角色、产物、门禁/人工批准节点） |
| `data/raw/` | 原始信号数据（红利低波50ETF择时信号.xlsx，只读） |
| `src/workflow/` | 工作流实现（当前已落地：阶段②取数与校验） |
| `tests/` | 单元测试 |
| `runs/` | run 状态库（每次迭代的快照、指标、裁决记录） |

## 环境配置与运行说明

**环境**：Python 3.13（Anaconda）；依赖 pandas、numpy、akshare、openpyxl、
matplotlib、pytest；报告编译需 TeX Live（xelatex + fandol 中文字体）。

```bash
# 安装依赖（akshare 体积大，国内建议清华镜像）
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple akshare pandas numpy openpyxl matplotlib pytest

# 单元测试（33 项）
python -m pytest tests/ -q

# 阶段②取数与校验（需联网；快照与 manifest 落 runs/<run>/data/）
python -m src.workflow.fetch --run-dir runs/run-001

# 阶段③回测执行（含阈值 ±5 敏感性；产物落 runs/<run>/result/）
python -m src.workflow.backtest --run-dir runs/run-002

# 阶段④自动评审（确定性门禁；产物落 runs/<run>/review/auto_review.json）
python -m src.workflow.review --run-dir runs/run-002

# 终局图与报告表格重生成
python scripts/make_final_figures.py && python scripts/make_report_tables.py

# 报告编译（latex 技能 helper，在仓库根目录执行）
python <latex-skill-dir>/scripts/compile_pdf.py docs/final_report/main.tex --engine xelatex
```

## 文件清单

| 路径 | 内容 |
|---|---|
| `docs/plans/task.md` | 任务定义（策略规则、回测设定、验收标准、修订预案） |
| `docs/DESIGN.md` | 架构设计（角色与交接、状态库、核验与改进机制） |
| `docs/workflow.png` | 带注释的工作流图（角色、产物、门禁/人工批准节点） |
| `docs/iteration_log.md` | 迭代日志（run-001~003 逐轮记录 + 终局裁决） |
| `docs/figures/` | 终局报告图（fig0 侧栏小图 ~ fig3 温度计与交易点） |
| `docs/final_report/` | 最终 A4 研究备忘（main.tex + sections/ + tables/ + main.pdf） |
| `data/raw/` | 原始信号数据（红利低波50ETF择时信号.xlsx，只读） |
| `src/workflow/` | 工作流实现：fetch（取数校验）/ backtest（回测）/ review（评审门禁） |
| `tests/` | 单元测试 33 项（校验逻辑、回测时序、验收判定） |
| `runs/` | run 状态库：run-001~003（假设快照、数据快照哈希、指标、敏感性、裁决）+ champion.json |
| `scripts/` | 工作流图、终局图与报告表格生成脚本 |

## 本人贡献声明

信号资产：独立构建"红利低波50ETF 温度计"择时指标（估值、热度、拥挤度三维度合成，日度，2018-01-02 至 2026-08-12），并完成数据整理与入库，该指标为本研究的信号源与核心自有资产；
任务与策略决策：选定研究标的（红利低波50ETF 515450）与"温度计逆向择时波段交易"研究方向；提出 v1 初始假设（温度计 >85 清仓、其余时间满仓的单阈值二元规则）；在修订循环中作出全部关键决策——批准 v1→v2 降阈值迭代、行使 H1 人工批准节点批准 v3 结构变更（叠加 200 日均线趋势过滤）、行使 H2 终局裁决止损并定稿 v2；
过程把关：逐轮复核任务定义、架构设计、回测结果与终局报告，提出并被采纳的修改包括：设定最大迭代次数上限（5 轮）、修正报告结论措辞为诚实口径、验收标准与 as_of 纪律的确认；
工具使用与分工：本项目全部代码、文档与图表在 Kimi Code（LLM 智能体）辅助下完成，本人负责全部指令下达、命令审批与成果验收；所有数值均由确定性 Python 代码计算，LLM 不对数值产物直接负责。
