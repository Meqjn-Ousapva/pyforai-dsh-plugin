# 三臂实验设计：锚点、结构化编辑与 AI 编程效率

## 1. 问题

在 Python 上，给 AI 增加一层显式的结构表示（`# end if` 注释锚点）和/或结构化编辑（`pyforai wrap / replace-body / move`），能否降低“产生正确代码”的成本？

这里的“正确”指隐藏测试通过；“成本”指修复轮数、墙钟时间、变更行数、最终产物大小，以及工具调用次数。

实验不是比较模型能力，而是比较**同一模型在不同工作流下的表现**。

## 2. 假设

| 编号 | 假设 | 主要观察 |
|---|---|---|
| H1 | 在**结构重构**任务上，C（锚点+结构化编辑）> B（锚点）> A（无锚点），按隐藏测试通过率和修复轮数衡量 | R1 |
| H2 | 在**从零写**任务上，三臂差异较小；B/C 的产物略大（锚点开销），但通过率不应下降 | W1 |
| H3 | B/C 的锚点错误接近 0（因为它们运行 `check`）；C 的 diff churn 和修复轮数低于 B | 全部 |
| H4 | C 的墙钟时间/工具调用更高；效率问题转化为“成功率增益是否值得这个成本” | 全部 |

H1 是主假设。如果 H1 不成立，这个方向的继续投入就缺乏依据。

## 3. 分支

| 臂 | 规则 | 允许的工具 |
|---|---|---|
| **A** | 普通 Python；不写锚点；不用 `pyforai` | 编辑器/测试 |
| **B** | 普通 Python；对 5+ 行或 3+ 层嵌套的块手写 `# end <kind>`；结束前跑 `check` | 编辑器/测试/`check` |
| **C** | B + 用 `pyforai` 做结构变换；新代码用 `fmt` 补锚点 | 编辑器/测试/`check`/`fmt`/`wrap`/`replace-body`/`move` |

三臂共享同一份基础 prompt，只有 arm rules 不同。这样差异来自工作流，而不是任务描述。

## 4. 任务

### W1：从零写（retry 装饰器）

实现 `retry(attempts, base_delay, exceptions, sleep)` 装饰器：指数退避 + jitter、只捕获指定异常、最后一次重抛、保留元数据、可注入 `sleep`。

为什么选它：`for` + `try/except` + `if` + 闭包，缩进密集；隐藏测试覆盖边界（`attempts=1`、jitter 上下界、参数透传）。

### R1：结构重构（给已有循环加重试）

`start.py` 里有一个可用的 `fetch_with_retry`：循环里调用一次 `client.fetch()` 就 `break`。要求改成捕获 `ConnectionError`、按 `attempts` 重试、失败间 `sleep(delay)`、最后一次重抛、非 `ConnectionError` 直接传播。

为什么选它：必须把 `for` 的 body 从“取一次”改成“try/except + sleep + continue”，是典型的“局部语义变化导致整段重排”。这正是锚点和结构化编辑应该发挥作用的地方。

### R2：更大的结构重构（per-account error isolation）

`start.py` 里有一个 `reconcile`：两层循环 + 三层 `if`，处理每个 account 的
ledger entries。要求把 `if account.active:` 的整个 body 包进
`try/except Exception as exc`，单个 account 失败只记录到 `report["errors"]`，
不中断其余 account；inactive 的 `else` 分支留在 try 外面。

为什么加它：R1 只改一个 5 行块，结构变换太小，容易天花板。R2 要整体重排
8+ 行、三层嵌套，更接近“结构重构真正会出错”的形态。它是 pilot 出现天花板后
加的**难度探针**，用来检查任务是否仍然太容易。

每个任务有：

- `task.md`：规格；
- `tests_public.py`：agent 可见、可运行的测试；
- `bench/hidden/<task>.py`：隐藏测试，agent 完成后才复制进 run 目录；
- `start.py`（仅重构任务）：不改动的起点，用于 diff 和 churn 计算。

## 5. 指标

### 主指标

- **hidden_pass**：隐藏测试是否全部通过（0/1）。
- **public_pass**：公开测试是否全部通过（0/1）。

### 次指标

- **repair_attempts**：agent 自己记录的测试-修复轮数（来自 `attempts.log`）。
- **wall_time_s**：`finished_at - started_at`（agent 写的时间戳）。
- **diff_added / diff_removed**：相对 `start.py` 的变更行数；从零写任务相对空文件。
- **loc**：最终 `solution.py` 的非空行数。
- **anchor_count / anchor_errors**：最终锚点数量和 `check` 错误数（合规性/质量）。
- **pyforai_calls**：`commands.log` 中 `pyforai` 命令数（工具成本）。
- **tampered_tests**：`tests_public.py` 是否被修改（完整性检查）。

### 效率口径

不造一个任意的复合指数。报告两条曲线：

- **success per wall-minute** = hidden passes / 总墙钟分钟；
- **success per 100 changed lines** = hidden passes / (diff_added + diff_removed) × 100。

再配一张 success vs. cost 的散点/表。读者可以自己选择权重。如果必须给一个决策口径，用：

> 在 R1 上，C 的 hidden pass 比 A 至少高 15 个百分点，且墙钟时间不超过 A 的 2 倍，才值得继续投入。

## 6. 协议

1. `python bench/harness.py init` 生成 6 个目录（2 任务 × 3 臂），每个目录有相同的 `task.md`、`tests_public.py`、`start.py`/空 `solution.py`、arm rules、prompt。
2. 每个 run 由一个独立的 agent 执行；agent 只看到自己的 run 目录。工作目录固定为项目根，测试命令为 `(cd bench/runs/<id> && python -m unittest tests_public -v)`。
3. agent 最多 3 次修复；结束前写 `summary.md`、`started_at.txt`、`finished_at.txt`、`attempts.log`、`commands.log`。
4. `python bench/harness.py score` 评分：语法、`pyforai check`、公开测试、隐藏测试、diff、日志。
5. `python bench/harness.py report` 聚合为 `report.md` / `report.csv`。

隐藏测试只在评分时复制到 run 目录；agent 运行期间不可见。`tests_public.py` 的 SHA-256 在 `init` 时记录，评分时比对，篡改会被标记。

### 控制变量

- 同一底层模型、同一基础 prompt、同一任务文本。
- 同一时间预算（3 次修复）和测试超时（120s）。
- 同一评分脚本，不依赖评分者主观判断。
- 任务顺序在正式实验中应随机化或 counterbalance；pilot 中并行执行，顺序影响较小。

## 7. 样本量与功效

主指标是二值结果。两比例检验的近似样本量（每臂）：

```
n ≈ (z_{1-α/2} + z_{1-β})^2 * [p1(1-p1) + p2(1-p2)] / (p1 - p2)^2
```

取 α=0.05（双侧）、power=0.8、p1=0.5：

| 目标差异 Δ | 每臂 n |
|---|---|
| 0.20 | ≈ 90 |
| 0.25 | ≈ 55 |
| 0.30 | ≈ 36 |
| 0.40 | ≈ 17 |

三臂 × 两任务的全因子设计，总量是 `3 × 2 × n`。25 个百分点差异需要约 330 次 run，成本很高。更现实的设计：

- **按任务配对**：同一任务跑三臂，用 McNemar / 配对 bootstrap；任务数 20–30 时对中等效应有较好功效。
- **序贯设计**：先跑 10 个任务 × 3 臂，若 C 相对 A 的增益方向明确，再扩展到 30。
- **混合效应模型**：`hidden_pass ~ arm + (1 | task)`，任务作为随机截距，比把任务当独立样本更合理。

**Pilot 只有 1 run/cell，不能做统计推断。** 它只用于验证流水线、估计方差、发现天花板/地板效应。

## 8. 分析计划

1. 每 run 表：任务、臂、public、hidden、anchor errors、LOC、diff、repair、wall、pyforai calls、tamper。
2. 按臂聚合：通过率、均值/中位数、成本。
3. 主分析（正式实验）：混合效应 logistic 回归，`hidden_pass ~ arm + (1 | task)`；报告 C−A、C−B 的 odds ratio 和 95% CI。
4. 次分析：`repair_attempts`、`wall_time_s`、`diff` 用配对 Wilcoxon 或 bootstrap CI。
5. 效率：success per wall-minute、success per 100 changed lines；画 success vs cost。
6. 合规性：B/C 的 anchor errors、pyforai calls；如果 B/C 没有实际使用锚点/工具，按“未遵循方案”单独报告，不能当作臂效应。

## 9. 效度威胁

- **同模型**：三个臂是同一模型的不同工作流，不是不同模型；结论不能外推到“所有 AI”。
- **提示泄漏**：arm rules 本身可能暗示“锚点很重要”，产生需求效应。正式实验应让 arm rules 尽量中性，或做盲评。
- **任务选择**：太容易 → 天花板（三臂都过）；太难 → 地板（三臂都挂）。Pilot 的第一件事就是检查是否卡在天花板。
- **自报日志**：`attempts.log` / 时间戳由 agent 写，可能漏写或误写；关键结论应主要依赖隐藏测试和 diff 这类不可自报的指标。
- **隐藏测试泄漏**：agent 被要求不读 `bench/hidden`，但无法强制；正式实验应把隐藏测试放在 agent 不可见的路径/容器。
- **工具摩擦**：C 需要多步 CLI 调用，可能因参数错误而变慢；这是真实成本，但也可能掩盖工作流本身的效果。应单独记录 `pyforai` 调用失败。
- **锚点开销**：B/C 的 LOC 天然更高；比较通过率时要同时看成本，不能只看 LOC。
- **Pilot 的 N=1**：任务难度和随机性无法分离；任何差异都只能当假设。

## 10. 什么结果会改变结论

- **C 在 R1 上没有超过 A，B 也没有超过 A**：锚点+结构化编辑在这个任务分布上不值得继续；转向纯 AST 编辑（不要锚点），或承认缩进不是主要瓶颈。
- **B 有增益、C 没有**：有效成分是“显式结构”，不是“工具化编辑”；优先做锚点/检查，而不是复杂编辑器。
- **C 有增益但墙钟明显更贵**：先优化工具（更少的调用、更好的错误信息、批量操作），再扩大实验。
- **三臂都接近 100%**：任务是天花板；换更长、更深、更需要跨块重排的任务，否则实验没有信息量。

## 11. 当前 pilot 的状态与结论

Pilot 使用 3 任务 × 3 臂，各 1 次 run，由 DSH subagent 执行。原始数字见
`bench/report.md`，分析见 `bench/PILOT.md`。

关键结果：

- **天花板效应**：9 个 run 全部 public/hidden 通过，0 次修复。三个任务都低于
  模型零修复能力的难度，因此 H1 没有被检验。
- **成本排序 A < C < B**：均值墙钟 A 10.7s、C 43.7s、B 71.7s；LOC 29.7 /
  37.0 / 43.0。**C（结构化编辑）比 B（手写锚点）更省**，说明手写锚点的维护
  成本才是大头；R2 大块重构上 C 16s vs B 81s 最明显。
- **但相对 A 仍是纯开销**：在这个难度上 A 也全过，且最便宜。干预只有在基线
  开始失败时才可能回本。
- **合规性**：B/C 锚点错误为 0，C 确实用了 `replace-body`/`fmt`/`wrap`，A
  确实没用 `pyforai`；无篡改。说明零差异不是“没按方案执行”造成的。
- **C 过度加锚**：pilot 的 C 规则用了 `fmt --all`，覆盖了 `--min-lines`，
  导致 R1 的 28 行文件插了 8 个锚点。已修正为 `fmt --min-lines 5 --min-depth 3`。

Pilot 的作用是验证流水线、检查天花板/地板、估计成本量级；它不是功效足够的
对照实验。**下一步不是扩大样本，而是先做难度校准**：用 A 在一组逐步变难的
任务上跑，找到 hidden pass 约 50–70% 的难度，再在该难度比较 B/C。否则扩大样本
只会得到更精确的“天花板”。

第二个值得单独验证的点：**工具维护锚点 vs 手写锚点**。Pilot 的 C < B 提示
“如果要用锚点，就必须让工具维护”，这比“锚点是否有用”更接近可落地的结论。
