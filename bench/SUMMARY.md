# pyforai / plugin 价值总结

生成日期：2026-11-03  
数据来源：E1（`bench/e1/`）、E1.1（`bench/e1/e11/`）、E2（`bench/e2/`）。

## 一句话结论

**这个 plugin 的可靠优势在“校验”和“大块重排的模型输出经济性”，不在“让强模型修得更对或更快”。** 现有数据支持前者，不支持后者。

## 口径说明

- 数据主要来自 `pyforai` 的 CLI/checker 与 `pyforai wrap`；DSH native plugin 的 schema 和 system prompt 本身没有单独做 A/B 对照。
- E1 的 592 个漂移是**注入生成**的，不是自然发生的 bug；检出率不能直接外推为“真实项目里能抓多少 bug”。
- E2 的“模型侧输出”是字节代理：
  - manual 取 per-edit snapshot 的 diff 字节；
  - plugin 取 `pyforai` 命令行的字节；
  - 不是 token，也不含推理 token。
- 样本量：E1 repair 每臂 6 run；E1.1 每臂 4 run；E2 每个 cell 1 run。除特别说明外，不做显著性声明。

## 优势与证据

| 优势 | 数据 | 强度 |
|---|---|---|
| 抓“语法合法但结构错误”的漂移 | 592 个注入 case 中 `pyforai check` 检出 **476/476（100%）**；`py_compile` **0%**；干净锚点文件误报 **0/165** | 强 |
| 诊断可定位 | 诊断行号与锚点/漂移行的平均距离 **0–1 行**；E001–E008 均命中预期 code | 强 |
| 删除锚点的覆盖检查 | `check --strict` 抓 **60/60** 个 E010；strict 总体 **536/536** | 强 |
| 大块重排减少模型输出 | 200 条语句 wrap：manual **15,940 B** vs plugin **251 B**，约 **63×**；三档均值 **8,207 B vs 296 B**，约 **28×** | 中（字节代理，非 token） |
| 重排结果结构正确、无 collateral | E2 6/6 run 的目标 AST 与 expected 完全一致；目标 `for` body 之外 **0 collateral** | 中（任务较简单） |
| 工具链/可审计性 | 锚点把块边界显式化；`check` 给出 `E004 L58` 这类可操作诊断；native plugin 省掉 CLI help/参数发现 | 中（native schema 本身未量化） |

## 数据明细

### 1. 校验：E1 drift suite

- 20 个真实文件（12 个 CPython stdlib + 8 个本仓库），592 个语法合法漂移。
- 检出：**476/476 = 100%**；误报：**0/165 = 0%**。
- 逐类：E001/E002/E003/E004/E005/E007/E008 各 40–60 个 case，全部检出；E004 的 `dedent_last` 58/58。
- 已知盲区：锚点随代码一起移动的 `consistent_shift` **56 个 case，0 检出**。这是设计限制，不是漏测。
- `fmt`：20/20 成功、20/20 过 `check`；但只有 18/20 过 `strict`。
- `fmt` 生成 derived anchors，`fmt → check` 是自证的；`fmt` 后的 `anchor_errors=0` 不能当质量信号。
- `black` 会把错位锚点重新对齐：`wrong_column` **3/3 在 black 后不再被检出**。所以 **check 要在 formatter 之前跑**。

### 2. 修复：E1 与 E1.1

| 实验 | 结果 |
|---|---|
| E1 repair（3 任务 × 2 模式 × 2 臂） | `check_on` **6/6**，`check_off` **6/6**；全部首轮修好；改锚点 0；laundering 0 |
| E1.1（4 任务 × 3 臂，无 `audit` 双胞胎） | `no_check` **4/4**，`tool_check` **4/4**，`forced_diagnostic` **4/4**；全部首轮修好 |

E1.1 的时间（N=4，仅方向性）：

| arm | 平均首次编辑 | 平均墙钟 |
|---|---|---|
| `no_check` | 15.5s | 30.5s |
| `tool_check` | 11.8s | 25.5s |
| `forced_diagnostic` | 18.0s | 28.2s |

`tool_check` 方向性快约 4s，但有一个 50s 离群值，**不能当结论**。修复侧没有可证明的优势：强模型在这些任务上本来就能修。

### 3. 编辑：E2 forced-reindent

任务：把 20/80/200 条语句的 `for` 循环整体包进 `try/except`，没有 `else:` 复用之类的捷径。

| size | manual 模型侧输出 | plugin 模型侧输出 | 倍数 | manual 墙钟 | plugin 墙钟 |
|---|---|---|---|---|---|
| 20 | 2,060 B | 408 B | 5.0× | 21s | 29s |
| 80 | 6,620 B | 229 B | 28.9× | 24s | 27s |
| 200 | 15,940 B | 251 B | **63.5×** | 33s | 34s |

- 三档 6/6 solved，目标 AST 3/3，collateral 0。
- **墙钟没有变快**：plugin 多花工具调用 + check 的几秒；强模型直接批量编辑已经很快。
- 因此结构化编辑的明确价值是 **output token / 上下文 / 成本**，不是延迟。
- 注意：这里的 plugin 臂用的是 CLI，不是 native tool；formatter 臂因 `black` 不可用未跑。

## 不成立的宣称

| 宣称 | 数据结论 |
|---|---|
| 让模型修得更好 | E1 与 E1.1 全部 ceiling，`check_on`/`no_check` 无 solved 差异 |
| 让模型修得更快 | E2 墙钟 plugin 29/27/34s vs manual 21/24/33s；E1.1 的 4s 差异不显著 |
| 锚点是形式化证明 | 56 个 consistent-shift case 检出 0；锚点与缩进错在同一处时抓不到 |
| `fmt` 后 check 通过 = 结构正确 | `fmt` 是 derived anchors，check 必然通过 |
| 弱模型也会受益 | 未测；当前没有弱模型数据 |

## 适合的定位

- **适合：CI / code review 的结构漂移守卫。** 检出率高、误报低、诊断可定位、运行成本低。
- **适合：大块重排时降低模型输出量。** E2 的 63× 信号支持这个方向，但需要真实 token 计数确认。
- **不适合宣称：强模型的修复成功率或速度提升。** 当前数据不支持。
- **待验证：弱模型 / 小模型是否收益更大。** 需要本地 3B/7B 或受限预算实验。

## 后续验证

1. 用真实 token 计数替换 `model_payload_proxy`。
2. 用 native plugin tool 重跑 E2，排除 CLI 参数/help 开销。
3. 在真实函数的 200 行块上复现 E2，并加 `move` / `replace-body`。
4. E1.1 需要多锚点、无 `pass` 残留的任务，或弱/中等模型，才能看出诊断价值。
5. `fmt` 与 `check --strict` 的覆盖率差异需要修（当前 18/20）。

## 证据索引

- [E1 findings](e1/FINDINGS.md)
- [E1 drift report](e1/drift/results/report.md)
- [E1 repair report](e1/repair/results/report.md)
- [E1.1 findings](e1/e11/FINDINGS.md)
- [E1.1 report](e1/e11/results/report.md)
- [E2 findings](e2/FINDINGS.md)
- [E2 report](e2/results/report.md)
