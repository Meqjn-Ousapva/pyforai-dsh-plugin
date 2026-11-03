import { spawn, spawnSync } from 'node:child_process'
import { chmodSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

export const inject = ['tools', 'workingDirectory', 'systemPrompt']

const DEFAULT_TIMEOUT_MS = 30_000
const MAX_OUTPUT_BYTES = 4 * 1024 * 1024

export function apply(ctx, config = {}) {
  const settings = {
    binaryPath: typeof config?.binaryPath === 'string' ? config.binaryPath : 'auto',
    pythonCheck: ['auto', 'on', 'off'].includes(config?.pythonCheck) ? config.pythonCheck : 'auto',
    timeoutMs:
      Number.isFinite(config?.timeoutMs) && config.timeoutMs > 0
        ? config.timeoutMs
        : DEFAULT_TIMEOUT_MS,
  }

  const binary = resolveBinary(settings.binaryPath)
  verifyBinary(binary)

  ctx.systemPrompt.section({
    name: 'tool:pyforai',
    order: ctx.systemPrompt.getSectionOrder('TOOL_GOAL'),
    text: `## Python: use pyforai

When you create or edit Python code, use the pyforai tools:
- For a new Python file, call pyforai_edit with command "fmt" to add anchors, then pyforai_check.
- For structural changes (wrap, replace-body, move), call pyforai_edit; do not hand-reindent.
- After any Python write or edit, call pyforai_check before finishing.
- pyforai_edit writes unless dryRun is true; use dryRun to preview a risky edit.
- If the tools are unavailable, fall back to direct editing and say so.`,
  })

  ctx.effect(() => ctx.tools.register(checkTool(ctx, binary, settings)))
  ctx.effect(() => ctx.tools.register(editTool(ctx, binary, settings)))
}

// ---------------------------------------------------------------------------
// binary resolution

function resolveBinary(configured) {
  if (configured && configured !== 'auto') return configured
  if (process.platform === 'linux') {
    const arch =
      process.arch === 'arm64' ? 'arm64' : process.arch === 'x64' ? 'amd64' : null
    if (arch) {
      const bundled = fileURLToPath(new URL(`./bin/pyforai-linux-${arch}`, import.meta.url))
      if (existsSync(bundled)) {
        try {
          chmodSync(bundled, 0o755)
        } catch {
          // The package may be read-only; spawn will surface EACCES with context.
        }
        return bundled
      }
    }
  }
  return 'pyforai'
}

function verifyBinary(binary) {
  const probe = spawnSync(binary, ['--version'], {
    encoding: 'utf8',
    timeout: 5000,
    env: childEnv(),
  })
  if (probe.error || probe.status !== 0) {
    const detail =
      probe.error?.message ||
      (probe.stderr && probe.stderr.trim()) ||
      `exit ${probe.status ?? probe.signal}`
    throw new Error(
      `pyforai: cannot run ${binary}: ${detail}. ` +
        'Install it with ./install.sh or set binaryPath to an absolute path.',
    )
  }
}

function childEnv() {
  const env = {
    PATH: process.env.PATH ?? '/usr/local/bin:/usr/bin:/bin',
    HOME: process.env.HOME ?? '',
    TMPDIR: process.env.TMPDIR ?? '/tmp',
  }
  if (process.env.LANG) env.LANG = process.env.LANG
  if (process.env.LC_ALL) env.LC_ALL = process.env.LC_ALL
  return env
}

// ---------------------------------------------------------------------------
// process execution

function run(binary, args, cwd, signal, timeoutMs) {
  return new Promise((resolve, reject) => {
    let settled = false
    let stdout = ''
    let stderr = ''
    let bytes = 0
    let timer
    let child

    try {
      child = spawn(binary, args, {
        cwd,
        env: childEnv(),
        stdio: ['ignore', 'pipe', 'pipe'],
        signal,
      })
    } catch (error) {
      reject(error)
      return
    }

    const finish = (error, value) => {
      if (settled) return
      settled = true
      if (timer) clearTimeout(timer)
      if (error) reject(error)
      else resolve(value)
    }

    const fail = (message) => {
      try {
        child.kill('SIGKILL')
      } catch {
        // Already exited.
      }
      finish(new Error(message))
    }

    timer = setTimeout(() => fail(`pyforai timed out after ${timeoutMs} ms`), timeoutMs)

    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdout.on('data', (chunk) => {
      bytes += Buffer.byteLength(chunk)
      if (bytes > MAX_OUTPUT_BYTES) {
        fail('pyforai output exceeded the 4 MiB limit')
        return
      }
      stdout += chunk
    })
    child.stderr.on('data', (chunk) => {
      stderr += chunk
      if (stderr.length > 100_000) stderr = stderr.slice(-100_000)
    })
    child.on('error', (error) => finish(error))
    child.on('close', (code, signalName) => finish(null, { code, signal: signalName, stdout, stderr }))
  })
}

async function resolveCwd(ctx, exec) {
  if (exec.agent) {
    try {
      return await ctx.workingDirectory.ensure(exec.agent, exec.signal)
    } catch {
      // Fall through to the profile default.
    }
  }
  return ctx.workingDirectory.defaultDirectory ?? process.cwd()
}

function parseJson(result, operation) {
  const text = result.stdout.trim()
  if (text) {
    try {
      return JSON.parse(text)
    } catch (error) {
      throw new Error(`pyforai ${operation} returned invalid JSON: ${error.message}`)
    }
  }
  const detail = result.stderr.trim() || `exit ${result.code ?? result.signal}`
  throw new Error(`pyforai ${operation} failed: ${detail}`)
}

// ---------------------------------------------------------------------------
// tools

function checkTool(ctx, binary, settings) {
  return {
    name: 'pyforai_check',
    description:
      'Check Python files for `# end <kind>` anchor consistency. Read-only and fast. ' +
      'Call this after writing or editing Python; returns diagnostics with line, column, code, and hint.',
    parameters: {
      type: 'object',
      properties: {
        paths: {
          type: 'array',
          items: { type: 'string' },
          description:
            'Files or directories to check. Relative paths resolve against the session workspace.',
        },
        strict: {
          type: 'boolean',
          description: 'Also require anchors for blocks above the size/depth thresholds.',
        },
        minLines: {
          type: 'number',
          description: 'Strict mode: minimum block span in lines (default 5).',
        },
        minDepth: {
          type: 'number',
          description: 'Strict mode: minimum nesting depth (default 3).',
        },
      },
      required: ['paths'],
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => [{ type: 'text', text: renderCheck(value) }],
    },
    timeoutMs: settings.timeoutMs,
    isConcurrencySafe: () => true,
    presentCall: (args) => ({
      card: 'generic',
      title: 'Check Python anchors',
      kind: 'read',
      rawInput: args,
    }),
    async execute(args, exec) {
      if (!Array.isArray(args?.paths) || args.paths.length === 0) {
        throw new Error('pyforai_check: paths must be a non-empty array')
      }
      const argv = ['check', '--json', ...args.paths.map(String)]
      if (args.strict === true) argv.push('--strict')
      if (Number.isFinite(args.minLines)) argv.push('--min-lines', String(args.minLines))
      if (Number.isFinite(args.minDepth)) argv.push('--min-depth', String(args.minDepth))
      const cwd = await resolveCwd(ctx, exec)
      const result = await run(binary, argv, cwd, exec.signal, settings.timeoutMs)
      return parseJson(result, 'check')
    },
  }
}

function editTool(ctx, binary, settings) {
  return {
    name: 'pyforai_edit',
    description:
      'Use for Python code generation and structural edits: fmt inserts anchors, wrap adds try/if/with/for/while, ' +
      'replace_body replaces a block body, move relocates a block. Preserves indentation and anchors and ' +
      'writes atomically. Call fmt on a new Python file, then pyforai_check; set dryRun to preview. ' +
      'Prefer this over hand-reindenting.',
    parameters: {
      type: 'object',
      properties: {
        command: {
          type: 'string',
          enum: ['fmt', 'wrap', 'replace_body', 'move'],
          description: 'Edit operation.',
        },
        file: { type: 'string', description: 'Python file to edit.' },
        header: {
          type: 'number',
          description: '1-based line of the block header (wrap/replace_body/move).',
        },
        anchor: {
          type: 'string',
          description:
            'LINE:COL of an existing anchor; column is 0-based (wrap/replace_body/move).',
        },
        dryRun: { type: 'boolean', description: 'Preview the diff without writing.' },
        kind: {
          type: 'string',
          enum: ['try', 'if', 'with', 'for', 'while'],
          description: 'wrap: wrapper kind.',
        },
        condition: { type: 'string', description: 'wrap if/while: condition expression.' },
        context: { type: 'string', description: 'wrap with: context expression.' },
        target: { type: 'string', description: 'wrap for: loop variable.' },
        iterable: { type: 'string', description: 'wrap for: iterable expression.' },
        exceptClause: {
          type: 'string',
          description: 'wrap try: text after `except ` (default Exception).',
        },
        handler: { type: 'string', description: 'wrap try: handler body (default raise).' },
        code: { type: 'string', description: 'replace_body: replacement body code.' },
        keepDocstring: {
          type: 'boolean',
          description: 'replace_body: keep the existing docstring.',
        },
        all: {
          type: 'boolean',
          description: 'fmt: insert anchors for every multi-line block.',
        },
        minLines: { type: 'number', description: 'fmt: minimum block span (default 5).' },
        minDepth: { type: 'number', description: 'fmt: minimum nesting depth (default 3).' },
        beforeLine: { type: 'number', description: 'move: insert before this line.' },
        afterLine: { type: 'number', description: 'move: insert after this line.' },
        intoLine: {
          type: 'number',
          description: 'move: append into the block starting at this line.',
        },
      },
      required: ['command', 'file'],
    },
    output: {
      schema: { type: 'object', additionalProperties: true },
      render: (_args, value) => [{ type: 'text', text: renderEdit(value) }],
    },
    timeoutMs: settings.timeoutMs,
    isConcurrencySafe: () => false,
    presentCall: (args) => ({
      card: 'generic',
      title: `pyforai ${args?.command ?? 'edit'}`,
      kind: 'other',
      rawInput: args,
    }),
    async execute(args, exec) {
      const argv = buildEditArgs(args, settings)
      const cwd = await resolveCwd(ctx, exec)
      const result = await run(binary, argv, cwd, exec.signal, settings.timeoutMs)
      const payload = parseJson(result, `edit ${args.command}`)
      const normalized = normalizeEditPayload(args.command, payload)
      if (normalized && normalized.ok === false) {
        const message = normalized.error || 'pyforai edit failed'
        const details = renderDiagnostics(normalized.diagnostics)
        throw new Error(details ? `${message}\n${details}` : message)
      }
      return normalized
    },
  }
}

function normalizeEditPayload(command, payload) {
  if (command !== 'fmt') return payload
  const results = Array.isArray(payload?.results) ? payload.results : []
  const failure = results.find((result) => result && result.ok === false)
  if (failure) return failure
  if (results.length === 1) return results[0]
  return {
    ok: payload?.ok !== false,
    changed: Number(payload?.changed) > 0,
    path: results.map((result) => result?.path).filter(Boolean).join(', '),
    operation: 'fmt',
    detail: `fmt: ${payload?.changed ?? results.length} file(s) changed`,
    diff: results
      .filter((result) => result?.diff)
      .map((result) => result.diff)
      .join('\n'),
    diagnostics: [],
    results,
  }
}

function buildEditArgs(args, settings) {
  const command = args?.command
  const file = args?.file
  if (!['fmt', 'wrap', 'replace_body', 'move'].includes(command)) {
    throw new Error('pyforai_edit: command must be fmt, wrap, replace_body, or move')
  }
  if (typeof file !== 'string' || file.length === 0) {
    throw new Error('pyforai_edit: file is required')
  }

  const argv = [command === 'replace_body' ? 'replace-body' : command]
  if (command === 'fmt') {
    argv.push('--json', file)
    if (args.all === true) argv.push('--all')
    if (Number.isFinite(args.minLines)) argv.push('--min-lines', String(args.minLines))
    if (Number.isFinite(args.minDepth)) argv.push('--min-depth', String(args.minDepth))
  } else {
    const hasHeader = Number.isFinite(args.header) && args.header > 0
    const hasAnchor = typeof args.anchor === 'string' && args.anchor.length > 0
    if (hasHeader === hasAnchor) {
      throw new Error('pyforai_edit: specify exactly one of header and anchor')
    }
    argv.push(file, '--json')
    argv.push(hasHeader ? '--header' : '--anchor', hasHeader ? String(args.header) : args.anchor)

    if (command === 'wrap') {
      if (typeof args.kind !== 'string' || args.kind.length === 0) {
        throw new Error('pyforai_edit: wrap requires kind')
      }
      argv.push('--kind', args.kind)
      if (typeof args.condition === 'string') argv.push('--condition', args.condition)
      if (typeof args.context === 'string') argv.push('--context', args.context)
      if (typeof args.target === 'string') argv.push('--target', args.target)
      if (typeof args.iterable === 'string') argv.push('--iterable', args.iterable)
      if (typeof args.exceptClause === 'string') argv.push('--except', args.exceptClause)
      if (typeof args.handler === 'string') argv.push('--handler', args.handler)
    } else if (command === 'replace_body') {
      if (typeof args.code !== 'string' || args.code.length === 0) {
        throw new Error("pyforai_edit: replace_body requires code (use 'pass' for an empty body)")
      }
      argv.push('--code', args.code)
      if (args.keepDocstring === true) argv.push('--keep-docstring')
    } else {
      const destinations = [
        ['--before-line', args.beforeLine],
        ['--after-line', args.afterLine],
        ['--into-line', args.intoLine],
      ].filter(([, value]) => Number.isFinite(value) && value > 0)
      if (destinations.length !== 1) {
        throw new Error(
          'pyforai_edit: move requires exactly one of beforeLine, afterLine, intoLine',
        )
      }
      argv.push(destinations[0][0], String(destinations[0][1]))
    }
  }

  if (args.dryRun === true) argv.push('--dry-run')

  if (settings.pythonCheck === 'on' || settings.pythonCheck === 'off') {
    argv.push('--python-check', settings.pythonCheck)
  } else if (command === 'wrap' || command === 'replace_body') {
    argv.push('--python-check', 'auto')
  }
  return argv
}

// ---------------------------------------------------------------------------
// rendering

function renderCheck(value) {
  try {
    const files = Array.isArray(value?.files) ? value.files : []
    const errors = Number.isFinite(value?.errors)
      ? value.errors
      : files.reduce(
          (sum, file) =>
            sum +
            (Array.isArray(file.diagnostics)
              ? file.diagnostics.filter((diagnostic) => diagnostic.severity === 'error').length
              : 0),
          0,
        )
    const lines = [`checked ${files.length} file(s): ${errors} error(s)`]
    for (const file of files) {
      for (const diagnostic of Array.isArray(file.diagnostics) ? file.diagnostics : []) {
        lines.push(
          `${file.path}:${diagnostic.line}:${diagnostic.col}: ${diagnostic.code} ${diagnostic.message}`,
        )
        if (diagnostic.hint) lines.push(`  hint: ${diagnostic.hint}`)
      }
    }
    return bounded(lines.join('\n'))
  } catch {
    return bounded(JSON.stringify(value))
  }
}

function renderEdit(value) {
  try {
    if (Array.isArray(value?.results)) {
      const changed = value.results.filter((result) => result?.changed)
      if (changed.length === 0) {
        return bounded(`fmt: no change (${value.results.length} file(s))`)
      }
      return bounded(
        changed
          .map(
            (result) =>
              `${result.path}: ${result.operation}: ${result.detail}` +
              (result.diff ? `\n${result.diff}` : ''),
          )
          .join('\n\n'),
      )
    }
    if (!value || value.ok === false) {
      return bounded(
        `${value?.error || 'pyforai edit failed'}\n${renderDiagnostics(value?.diagnostics)}`.trim(),
      )
    }
    if (value.changed) {
      const lines = [`${value.path}: ${value.operation}: ${value.detail || 'changed'}`]
      if (value.diff) lines.push('', value.diff)
      return bounded(lines.join('\n'))
    }
    return bounded(`${value.path}: ${value.operation}: no change`)
  } catch {
    return bounded(JSON.stringify(value))
  }
}

function renderDiagnostics(diagnostics) {
  if (!Array.isArray(diagnostics) || diagnostics.length === 0) return ''
  return diagnostics
    .map(
      (diagnostic) =>
        `${diagnostic.code} at ${diagnostic.line}:${diagnostic.col}: ${diagnostic.message}` +
        (diagnostic.hint ? `\n  hint: ${diagnostic.hint}` : ''),
    )
    .join('\n')
}

function bounded(text, maxLines = 200, maxChars = 12_000) {
  const lines = String(text).split('\n')
  let out = lines.slice(0, maxLines).join('\n')
  if (lines.length > maxLines) out += `\n... (${lines.length - maxLines} more lines)`
  if (out.length > maxChars) out = `${out.slice(0, maxChars)}\n... (truncated)`
  return out
}
