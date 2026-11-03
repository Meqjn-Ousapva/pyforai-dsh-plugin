# pyforai（Go 实现）

同一套 CLI 的编译版：**单个静态二进制**，不依赖 Python / glibc，启动约 1 ms，适合被 agent 高频调用。

```bash
$ pyforai --version
pyforai 0.2.0 (go)

$ file /usr/local/bin/pyforai
ELF 64-bit LSB executable, x86-64, statically linked, stripped
```

## 为什么选 Go

| 方案 | 优点 | 代价 |
|---|---|---|
| C | 二进制最小 | 手写解析、内存管理、错误处理，维护成本最高 |
| Rust | 安全、性能好 | 代码量/编译时间更大；Python 解析器要额外 crate |
| **Go** | 标准库够用、静态二进制、交叉编译简单、开发快 | 需要自己写 Python 结构扫描器 |

C/Rust/Go 都没有内置 Python 解析器，三者都要自己解决块边界问题。Go 在“实现成本 / 部署成本 / 迭代速度”上最平衡，所以选 Go。

## 构建

本仓库的 `Makefile` 把 `GOCACHE`/`GOPATH` 放在 `go/.gocache`、`go/.gopath`（当前环境的 `~/.cache` 是只读的）。普通机器上直接 `go build` 即可。

```bash
make build     # bin/pyforai（本机架构）
make static    # bin/pyforai-linux-amd64 + bin/pyforai-linux-arm64
make test      # go test ./...
make oracle    # Go vs Python 的 check 对照（需要 Python）
```

验证静态链接：

```bash
file bin/pyforai-linux-amd64
# ELF 64-bit LSB executable, x86-64 ... statically linked
ldd bin/pyforai-linux-amd64
# not a dynamic executable
```

## 部署到 Ubuntu / RHEL

```bash
sudo ./install.sh
# 或指定目录：
PYFORAI_INSTALL_DIR=$HOME/.local/bin ./install.sh
pyforai --version
```

`install.sh` 按 `uname -m` 选择 amd64/arm64，安装到 `/usr/local/bin/pyforai`。静态二进制不依赖目标机 glibc 版本，也不需要 Python。

## 兼容性

命令、flags、JSON 字段与 Python 版一致：

- `check`：`--strict`、`--min-lines`、`--min-depth`、`--json`、目录递归、E000–E010/E100。
- `fmt`：`--all`、`--min-lines`、`--min-depth`、`--dry-run`、`--json`。
- `wrap`：`--header` / `--anchor`、`--kind try|if|with|for|while`、`--condition`、`--context`、`--target`、`--iterable`、`--except`、`--handler` / `--handler-file`。
- `replace-body`：`--header` / `--anchor`、`--code` / `--code-file`、`--keep-docstring`。
- `move`：`--header` / `--anchor`、`--before-line` / `--after-line` / `--into-line`。
- 所有编辑命令支持 `--dry-run`、`--json`、`--python-check auto|on|off`。
- flags 可以放在位置参数前或后；支持 `--flag=value`。

**一致性验证**：`go/oracle_check.py` 在 62 个项目内 Python 文件上对照 Python 版
`check --json` 的 `(code, line, col)`，当前 **0 差异**。`examples/demo_*` 上的
`fmt` / `wrap` / `replace-body` / `move` 输出与 Python 版逐字节一致。

## 性能

本机（Linux x86_64，含进程启动），100 次取平均：

| 命令 | Python 版 | Go 版 | 加速 |
|---|---|---|---|
| `check examples/demo_good.py` | 50.3 ms | **1.36 ms** | ~37× |
| `fmt --all --dry-run examples/demo_before.py` | 50.3 ms | **1.31 ms** | ~38× |
| `fmt ... --python-check on` | — | 30.9 ms | CPython 校验开销 |

`check` 是高频路径，纯 Go 扫描，不启动 Python。

## 校验模式

Go 版是 **结构扫描器**（lexer + 缩进/块解析），不是完整 Python 解析器。它能抓：

- 未闭合字符串/括号、空 suite、块边界、缩进、装饰器、async、match、clauses；
- 锚点的全部不变式（E001–E008、E010）。

它不能抓所有表达式级语法错误。为此编辑命令提供 `--python-check`：

| 命令 | 默认 | 理由 |
|---|---|---|
| `fmt` | `off` | 纯插入注释，不引入新表达式 |
| `move` | `off` | 移动已有代码，不引入新表达式 |
| `wrap` | `auto` | header/handler 是用户输入，可能有语法错误 |
| `replace-body` | `auto` | 新 body 是用户输入 |

- `auto`：找到 `python3` 就用 `python3 -m py_compile` 校验；找不到则退回结构校验。
- `on`：要求 Python，找不到就报错。
- `off`：只做结构校验，最快（约 1.3 ms）。

`Commit` 永远先跑结构校验和锚点校验；`--python-check` 是额外的一层。校验失败时不写文件。

## 限制

- 只支持 UTF-8（含 BOM）；非 UTF-8 的 PEP 263 编码报 E000。Python 版支持这些编码。
- CRLF 统一为检测到的主换行符；混合换行不逐行保留。
- 结构扫描器不是完整 parser；表达式级语法错误只在 `--python-check` 时由 CPython 捕获。
- `match` 的 `replace-body` / `move --into` 仍被拒绝（与 Python 版一致）。
- `move` 只保证语法/缩进，不保证作用域、import、控制流语义。
- 不提供 `.deb` / `.rpm`；用静态二进制 + `install.sh`。

## 代码结构

```
go/
├── scan.go        # lexer（字符串/注释/括号/缩进）+ 块解析器
├── check.go       # L1：E001–E008、E010、E100、strict
├── edit.go        # L2：fmt / wrap / replace-body / move、原子写、diff、py_compile 校验
├── cli.go         # 子命令、flags、JSON、目录递归
├── oracle_check.py
└── cmd/pyforai/   # main
```

## 测试

```bash
make test
make oracle
```

Go 测试覆盖 scanner、checker、fmt/wrap/replace/move、BOM/CRLF、空块拒绝、CPython 校验拒绝。Oracle 覆盖 62 个项目内文件，当前 0 差异。
