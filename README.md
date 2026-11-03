# python-for-AI

> 用注释锚点给 Python 补一层 AI 可读的**结构表示**：把隐式的块边界变成显式、可校验、可寻址的东西。语言零改动，权威放在工具链。

```python
for item in items:
    if item.enabled:
        results.append(item.value)
    # end if
# end for
```

Python 解析器完全忽略 `# end if` / `# end for`。这正是重点：**不新增语法，不丢语料**。但 `pyforai` 会把锚点和 AST 对照，不一致就是硬错误。

这对应两层能力：

- **L1 `check`**：把锚点当作“断言”，校验它和缩进是否一致；错误信息直接告诉你期望的 kind / 行号。
- **L2 `wrap` / `replace-body` / `move`**：把锚点当作“句柄”，结构化编辑，自动处理缩进，模型不再做空白手术。

---

## 为什么是注释，而不是大括号或新方言

缩进的真正麻烦有两半：

1. **块结构不可寻址**——token 流里没有块边界，块没有名字，只能按行号或文本片段指代。
2. **结构变换不局部**——包一层 `try` / `if` 要重排整段，diff 放大、缩进漂移。

大括号能同时治两半，但代价是丢语料、破工具链。注释锚点只能治第一半；第二半靠 L2 的结构化编辑。这是它便宜的原因，也是它天花板有限的原因。

三条选 Python 的理由，恰好都指向“别动语法”：

- **语料丰富**：任何语法扩展都是拿先验换结构。注释是 Python 里唯一“有表达力、又被解析器完全忽略”的通道，零语法增量。
- **胶水 + 可下沉**：Python 是编排层，控制流密集，正是 dedent 语义最密集的地方；核心模块仍可换 C/Rust/Go。
- **快反馈**：但缩进的静默错误会绕过反馈——语法合法、测试未必覆盖、formatter 还会把错误结构固化。锚点的作用是把这类错误重新拉回快反馈。

---

## 它解决什么，不解决什么

| | 锚点的作用 | 强度 |
|---|---|---|
| 生成期 | 关闭块时显式承诺一次，减少“丢栈” | 弱正向 |
| 编辑期 | 本身不解决 reindent，必须配 L2 | 无 |
| 校验期 | 把“意图 vs 词法”的分歧变成可检测错误 | 中等 |
| 表示期 | 块有 handle，可 wrap/replace/move、可检索、可审阅 | 强 |

必须说清楚的一个限制：**锚点是同一意图的第二次采样，不是独立 checksum。** 如果作者对结构的理解和缩进错在同一处，锚点也会错在同一处。它能抓“漂移”，抓不到“系统性误解”。这仍然有价值——缩进事故里漂移占大头——但不要把它当形式化证明。

---

## 安装

只依赖标准库，Python ≥ 3.10。

```bash
cd python-for-AI
python -m pip install -e .
```

不安装也能直接跑：

```bash
python -m pyforai --help
```

---

## 30 秒快速开始

```bash
# L1：校验
python -m pyforai check examples/demo_good.py
python -m pyforai check examples/demo_bad.py

# 只看不改
python -m pyforai fmt --all --dry-run examples/demo_before.py

# L2：把 for 循环包进 try
cp examples/demo_before.py /tmp/demo.py
python -m pyforai wrap /tmp/demo.py --header 6 --kind try \
    --except "Exception as e" --handler raise
```

`demo_bad.py` 会给出四条可自纠的错误，例如：

```
examples/demo_bad.py:13:4: E001 kind mismatch: the block at column 4 is `for` (line 10), not `if`
  hint: the block ending here is `for` (opened at line 10); write `# end for`
examples/demo_bad.py:20:4: E003 the `if` at line 18 ends at line 22 (it continues into an `else`/`elif` clause); the anchor is inside it
  hint: move the anchor after line 22
```

---

## 锚点规范（摘要）

完整规范见 [`docs/SPEC.md`](docs/SPEC.md)。

```python
# end if | for | while | try | with | def | class | match
```

规则：

1. 锚点独占一行，列号与块 header 相同。
2. 放在整个复合语句之后；`if/elif/else`、`try/except/else/finally` 只在整个语句结束后放一个。
3. 块最后一条语句和锚点之间只能有注释/空行。
4. 一个块一个锚点；嵌套时内层锚点先于外层。
5. **稀疏使用**：块长、嵌套深、或 dedent 处容易出错时才写。不要给三行块都加。

`async def/for/with` 归一化为 `def/for/with`，没有 `# end async def`。

---

## L1：`check`

```bash
python -m pyforai check path/                 # 递归检查目录
python -m pyforai check --strict path/        # 额外要求“大/深”块必须有锚点
python -m pyforai check --json path/          # 给 agent 的结构化输出
```

`--strict` 的门槛：

```bash
python -m pyforai check --strict --min-lines 5 --min-depth 3 .
```

默认模式只校验“已经写了的锚点”，不会因为缺锚点报错；`--strict` 才会把覆盖变成策略（`E010`）。

错误码：

| 码 | 含义 |
|---|---|
| `E001` | kind 不匹配（该块是 `for`，锚点写了 `if`） |
| `E002` | 该列没有块 header |
| `E003` | 锚点在块内部（常见于 `else`/`except` 之前） |
| `E004` | 块结束和锚点之间还有代码 |
| `E005` | 重复锚点 |
| `E006` | 锚点后的第一行代码更深（防御性检查） |
| `E007` | 锚点前面有代码（不是独占一行） |
| `E008` | 外层锚点出现在内层之前 |
| `E010` | strict 模式下缺锚点 |
| `E100` | 语法错误 |

---

## L2：`wrap` / `replace-body` / `move`

所有编辑命令都走同一条流水线：

```
读文件 -> 解析 -> 校验现有锚点 -> 变换
       -> 解析结果 -> 校验结果锚点 -> 原子写入
```

任何一步失败都**不写文件**，原文件保持不变。`--dry-run` 只计算并打印 diff。

### `wrap`：包一层

```bash
# 把 header 在 line 6 的 for 循环包进 try
python -m pyforai wrap demo.py --header 6 --kind try \
    --except "Exception as e" --handler raise

# 包 if / with / for / while
python -m pyforai wrap demo.py --header 6 --kind if --condition "items"
python -m pyforai wrap demo.py --header 6 --kind with --context "lock"
python -m pyforai wrap demo.py --header 6 --kind for --target x --iterable xs
python -m pyforai wrap demo.py --header 6 --kind while --condition "ready"
```

- 新 header 放在目标块的基准缩进处；目标块整体多缩进一个单位。
- 缩进单位从目标块自己的 body 推断（4 空格 / 2 空格 / tab 都保持原风格）。
- 装饰器会跟着 `def/class` 一起移动。
- 多行字符串的内部行不会被重排，字符串值不变。
- 自动补 `# end <kind>`。

### `replace-body`：换 body

```bash
python -m pyforai replace-body demo.py --header 4 \
    --code 'return [item.value for item in items if item.enabled]'

# 从文件读（适合多行），或从 stdin
python -m pyforai replace-body demo.py --header 4 --code-file body.py
python -m pyforai replace-body demo.py --header 4 --code-file -
```

- 只替换目标块**第一个 clause** 的 body：`if` 的 `elif/else`、`try` 的 `except` 都会保留。
- 替换代码会自动 dedent 再按 body 缩进。
- `--keep-docstring` 保留原 docstring（原样，不重排）。
- 单行块（`if a: pass`）和 `match` 会被拒绝，并给出原因。

### `move`：移动块

```bash
cp examples/demo_move.py /tmp/demo_move.py

# 把 line 8 的 def second 移到 line 4 的 def first 前面
python -m pyforai move /tmp/demo_move.py --header 8 --before-line 4

# 移到另一个语句后面
python -m pyforai move /tmp/demo_move.py --header 8 --after-line 4

# 追加到 line 4 这个块的 body 末尾
python -m pyforai move /tmp/demo_move.py --header 8 --into-line 4
```

- 目标块连同装饰器、锚点、块内尾随注释一起移动。
- 按目标缩进重新缩进；相对缩进保持。
- 拒绝：移到自身/后代内部、把父块的唯一语句移走（会留下空 body）。
- **move 是语法操作**，不检查变量作用域、控制流、import。语义由调用方负责。
- move 不负责空行/风格；大改之后建议跑一次 black/ruff-format。

---

## `fmt` 的定位（重要）

```bash
python -m pyforai fmt --all --dry-run path/
python -m pyforai fmt --all path/
```

`fmt` 只做一件事：给**没有锚点**的块插入锚点。

- 插入顺序是内层优先；同一行结束的嵌套块按列从大到小，最终文件读起来是内到外。
- 如果文件里已有**无效**锚点，`fmt` 会拒绝运行。这是故意的：静默“修好”一个断言，会掩盖它本来要暴露的 bug。
- **`fmt` 插入的是 AST 镜像，不是断言。** 它提升可读性、给编辑器提供句柄，但不增加校验价值——因为它和解析器看到的是同一棵树。真正的校验价值来自“先写锚点、再让 `check` 对照”的流程。

---

## 给 agent 的接口

```bash
python -m pyforai check --json .
python -m pyforai wrap demo.py --header 6 --kind try --except Exception --handler pass --json
python -m pyforai replace-body demo.py --header 4 --code-file - --json
python -m pyforai move demo.py --header 8 --into-line 4 --json
```

约定：

- `--json` 输出单对象；`check` 输出 `{ok, errors, warnings, files}`。
- 失败时 `ok=false`，`diagnostics` 带 `code/line/col/message/hint`，退出码 1。
- `--dry-run` 返回 diff 但不写文件，适合“先看再决定”。
- 行号 1-based，列号 0-based（与 `ast`/`tokenize` 一致）。

在 CI / pre-commit 里可以直接当 gate：

```bash
python -m pyforai check --strict src/
```

---

## 设计原则

1. **权威在工具链，不在语法。** Python 忽略锚点；`pyforai` 把不一致当硬错误。这样既拿到校验，又不分叉语言。
2. **锚点可选、稀疏。** 双表示对短块是净负担；只在值得的地方写。
3. **不做空白手术。** L2 负责 reindent；模型只表达“把哪个块包进什么”。
4. **先校验再写。** 结果必须能 parse 且通过 anchor check；否则原文件不动。
5. **不碰多行字符串内部。** 宁可视觉不齐，也不改字符串值。
6. **保持编码和换行。** PEP 263 / BOM / CRLF / 末尾换行都尽量原样保留。

---

## 限制（v0.1）

- 不支持 clause 级锚点（`# end if` 放在 `else` 之前）。`else`/`elif`/`except`/`finally`/`case` 本身已经是显式边界 token。
- 不支持替换 `match` 的 body，或把块 move 进 `match`。
- 只能移动复合语句，不能移动单条简单语句。
- move 不做语义检查（作用域、import、控制流）。
- 不做空行/风格规范化；大改之后建议跑一次 formatter。
- 锚点不是独立 checksum（见上文“第二次采样”）。

---

## 测试

```bash
python -m unittest discover -s tests -v
```

当前 83 个测试，覆盖：所有块类型、装饰器、async、match、嵌套/稀疏锚点、8 类错误、strict、JSON、CRLF、BOM、多行字符串、原子写入、dry-run、fmt 幂等、wrap/replace/move 的成功与拒绝路径。

---

## 目录结构

```
python-for-AI/
├── pyforai/
│   ├── anchors.py     # 块模型、锚点词法、逻辑行起点
│   ├── checker.py     # L1：校验、诊断、strict、fmt 计划
│   ├── editor.py      # L2：wrap / replace-body / move / fmt，原子写
│   └── cli.py         # 命令行与 JSON
├── tests/             # unittest，无第三方依赖
├── examples/
│   ├── demo_good.py   # 默认 check 通过
│   ├── demo_bad.py    # 四类错误
│   ├── demo_before.py # 无锚点，用于 fmt/wrap 演示
│   └── demo_move.py   # 用于 move 演示
├── docs/SPEC.md       # 规范：词法、位置、不变式、错误码、编辑语义
├── bench/             # 三臂实验：任务、arms、harness、pilot 报告
│   ├── DESIGN.md
│   ├── README.md
│   ├── harness.py
│   ├── tasks/ hidden/ arms/ runs/
│   └── report.md
└── pyproject.toml
```

---

## 评测（三臂实验）

`bench/` 里是可复现的三臂实验：**无锚点 / 锚点 / 锚点+结构化编辑 × 从零写 / 结构重构**。

```bash
python bench/harness.py init
# 用任意 agent runner 跑 bench/runs/<id>/prompt.md
python bench/harness.py score
python bench/harness.py report
```

- 设计、假设、样本量、效度威胁：[`bench/DESIGN.md`](bench/DESIGN.md)
- 运行方式：[`bench/README.md`](bench/README.md)
- pilot 原始数字：[`bench/report.md`](bench/report.md)
- pilot 分析与结论：[`bench/PILOT.md`](bench/PILOT.md)

Pilot 只有 1 run/cell，只用于验证流水线和检查天花板/地板效应，不做统计推断。
本次 pilot（3 任务 × 3 臂 = 9 个 run）的结论是**天花板效应**：全部首轮通过，
任务太简单，尚不能检验“锚点是否减少语义缩进错误”。成本上 **A < C < B**：
A 最低；C（结构化编辑）比 B（手写锚点）更省，说明手写锚点的维护成本才是大头；
但在当前难度下，两者相对 A 都是纯开销。下一步应先做难度校准，而不是扩大样本。

## 下一步

- **Lens 模式**：盘上保持纯 Python，读时注入锚点/块号，写时剥离或结构化回写。
- **更多结构化操作**：extract-function、rename、import-aware move。
- **LSP / MCP**：把 `check`、`wrap`、`replace-body` 暴露给编辑器或 agent runtime。
- **评测**：同一组任务（从零写 vs 结构重构）对照“无锚点 / 锚点 / 锚点+结构化编辑”，看语法错误率、语义 dedent 错误率、测试通过率、token、修复轮数。结构重构才是主战场；如果这一类没有显著收益，这个方向就该收手。
