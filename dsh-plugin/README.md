# dsh-pyforai — DSH plugin for Python

> **DSH插件 / DSH plugin for Python:** expose pyforai's Python structural
> validation and structural editing as two native DSH tools.

A Host-only DSH bundle that exposes the `pyforai` binary as two native tools:

- `pyforai_check` — validate `# end <kind>` anchors in Python files.
- `pyforai_edit` — `fmt`, `wrap`, `replace_body`, and `move`, with automatic
  reindentation and atomic writes.

The bundle is self-contained: it ships static `pyforai` binaries for Linux
amd64/arm64 in `bin/`. It falls back to `pyforai` on `PATH` when the bundled
binary is unavailable, or when `config.binaryPath` names an explicit
path/command.

## Config

```yaml
binaryPath: auto      # auto = bundled Linux binary; or an absolute path/command
pythonCheck: auto     # auto | on | off; passed to edit commands
timeoutMs: 30000
```

`auto` follows the per-command defaults: `fmt` and `move` use the fast
structural validation; `wrap` and `replace_body` use CPython's `py_compile`
when `python3` is available. `on` and `off` override this for every edit
command. Set `off` for maximum speed or `on` to require Python validation.

## Install

From the repository root:

```bash
python3 -m pyforai ...          # or: make static
```

Then install the bundle through DSH's plugin manager:

```text
plugin_manager action=install_bundle target=/absolute/path/to/<repo>/dsh-plugin
```

The source bundle is linked into the current profile; keep the checkout in
place for a linked install. The tools appear as `pyforai_check` and
`pyforai_edit` in the next request.

## Automatic use

On activation the plugin registers a system-prompt section `tool:pyforai`.
It tells the agent to:

- call `pyforai_edit` with `fmt` on a new Python file, then `pyforai_check`;
- use `pyforai_edit` for wrap / replace-body / move instead of hand-reindenting;
- run `pyforai_check` after any Python write or edit.

The section is always active while the plugin is enabled.  Evaluation arms can
carry an explicit override; the default is to follow it.

## Reloading after a code change

The Host imports `index.js` once. After editing it, toggle the bundle:

```text
plugin_manager set_bundle target=@local/pyforai enabled=false
plugin_manager set_bundle target=@local/pyforai enabled=true
```

or restart the Harness.

## Config schema

This bundle reads its row config directly and does not export a `Config`
schema; set `binaryPath`, `pythonCheck`, and `timeoutMs` in
`cordis.patch.yml`. The Plugin Manager shows no config fields for this row.

## Sandbox

The plugin spawns the bundled binary with `spawn` (no shell) and forwards the
tool cancellation signal. Its file writes are not mediated by DSH's file
sandbox; treat it as a trusted profile plugin and keep paths inside the
session workspace unless you explicitly need otherwise.

## Notes

- Relative paths resolve against the calling agent's session workspace.
- `pyforai_edit` writes files unless `dryRun: true`; it uses atomic writes.
- The plugin runs the binary with `spawn` (no shell) and forwards the tool
  cancellation signal.
- After rebuilding the Go binary, replace `bin/pyforai-linux-*` (or set
  `binaryPath` to the new path) and toggle the bundle.
- Display metadata: `locale/en.json`, `locale/zh.json`, `icon.svg`.
