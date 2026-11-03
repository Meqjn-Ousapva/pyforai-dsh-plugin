package pyforai

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

// Version is the compiled tool version.
const Version = "0.2.0"

var excludedDirs = map[string]bool{
	".git": true, ".hg": true, ".svn": true,
	".venv": true, "venv": true, "__pycache__": true,
	".mypy_cache": true, ".pytest_cache": true, ".ruff_cache": true,
	".tox": true, "build": true, "dist": true, "node_modules": true, ".eggs": true,
}

// Run dispatches the CLI.  It returns the process exit code.
func Run(args []string) int {
	if len(args) == 0 {
		usage()
		return 2
	}
	switch args[0] {
	case "--version", "-version", "version":
		fmt.Printf("pyforai %s (go)\n", Version)
		return 0
	case "--help", "-h", "help":
		usage()
		return 0
	case "check":
		return cmdCheck(args[1:])
	case "fmt":
		return cmdFmt(args[1:])
	case "wrap":
		return cmdWrap(args[1:])
	case "replace-body":
		return cmdReplaceBody(args[1:])
	case "move":
		return cmdMove(args[1:])
	default:
		fmt.Fprintf(os.Stderr, "pyforai: unknown command %q\n", args[0])
		usage()
		return 2
	}
}

func usage() {
	fmt.Fprint(os.Stderr, `pyforai — comment anchors and structural editing for Python

Usage:
  pyforai check [--strict] [--min-lines N] [--min-depth N] [--json] PATH...
  pyforai fmt   [--all] [--min-lines N] [--min-depth N] [--dry-run] [--json] PATH...
  pyforai wrap  FILE (--header N | --anchor LINE:COL) --kind KIND ...
  pyforai replace-body FILE (--header N | --anchor LINE:COL) (--code S | --code-file F)
  pyforai move  FILE (--header N | --anchor LINE:COL) (--before-line N | --after-line N | --into-line N)

Flags may appear before or after the positional path.

Global:
  pyforai --version
`)
}

// ---------------------------------------------------------------------------
// argument parsing

type parsedArgs struct {
	values     map[string]string
	bools      map[string]bool
	positional []string
}

// parseArgs parses GNU-style flags anywhere in argv.  flags maps a flag name
// to true when it takes a value.
func parseArgs(args []string, flags map[string]bool) (*parsedArgs, error) {
	p := &parsedArgs{values: map[string]string{}, bools: map[string]bool{}}
	for i := 0; i < len(args); i++ {
		arg := args[i]
		if arg == "--" {
			p.positional = append(p.positional, args[i+1:]...)
			break
		}
		if strings.HasPrefix(arg, "-") && arg != "-" {
			name := strings.TrimLeft(arg, "-")
			value := ""
			hasValue := false
			if idx := strings.IndexByte(name, '='); idx >= 0 {
				value = name[idx+1:]
				name = name[:idx]
				hasValue = true
			}
			takesValue, known := flags[name]
			if !known {
				return nil, fmt.Errorf("unknown flag --%s", name)
			}
			if takesValue {
				if !hasValue {
					if i+1 >= len(args) {
						return nil, fmt.Errorf("flag --%s requires a value", name)
					}
					value = args[i+1]
					i++
				}
				p.values[name] = value
			} else {
				if hasValue {
					return nil, fmt.Errorf("flag --%s does not take a value", name)
				}
				p.bools[name] = true
			}
			continue
		}
		p.positional = append(p.positional, arg)
	}
	return p, nil
}

func (p *parsedArgs) String(name, def string) string {
	if value, ok := p.values[name]; ok {
		return value
	}
	return def
}

func (p *parsedArgs) Int(name string, def int) (int, error) {
	value, ok := p.values[name]
	if !ok {
		return def, nil
	}
	parsed, err := strconv.Atoi(strings.TrimSpace(value))
	if err != nil {
		return 0, fmt.Errorf("--%s must be an integer", name)
	}
	return parsed, nil
}

func (p *parsedArgs) Bool(name string) bool { return p.bools[name] }

// ---------------------------------------------------------------------------
// check

type checkFileJSON struct {
	Path        string       `json:"path"`
	Ok          bool         `json:"ok"`
	Anchors     int          `json:"anchors"`
	Diagnostics []Diagnostic `json:"diagnostics"`
}

type checkJSON struct {
	Ok       bool            `json:"ok"`
	Errors   int             `json:"errors"`
	Warnings int             `json:"warnings"`
	Files    []checkFileJSON `json:"files"`
}

func cmdCheck(args []string) int {
	parsed, err := parseArgs(args, map[string]bool{
		"strict": false, "min-lines": true, "min-depth": true, "json": false, "help": false,
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	if parsed.Bool("help") {
		usage()
		return 0
	}
	minLines, err := parsed.Int("min-lines", 5)
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	minDepth, err := parsed.Int("min-depth", 3)
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	if len(parsed.positional) == 0 {
		fmt.Fprintln(os.Stderr, "pyforai: check requires at least one PATH")
		return 2
	}
	paths, err := expandPaths(parsed.positional)
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}

	files := []checkFileJSON{}
	errorsCount := 0
	warnings := 0
	for _, path := range paths {
		text, readErr := readSource(path)
		if readErr != nil {
			errorsCount++
			diagnostic := Diagnostic{
				Code: "E000", Severity: "error", Line: 0, Col: 0,
				Message: readErr.Error(),
			}
			files = append(files, checkFileJSON{Path: path, Ok: false, Diagnostics: []Diagnostic{diagnostic}})
			if !parsed.Bool("json") {
				fmt.Printf("%s: E000 %s\n", path, readErr)
			}
			continue
		}
		model := Scan(text)
		result := CheckModel(model, parsed.Bool("strict"), minLines, minDepth)
		errorsHere := 0
		for _, d := range result.Diagnostics {
			if d.Severity == "error" {
				errorsHere++
			}
		}
		errorsCount += errorsHere
		files = append(files, checkFileJSON{
			Path:        path,
			Ok:          result.Ok,
			Anchors:     len(result.Matches),
			Diagnostics: result.Diagnostics,
		})
		if !parsed.Bool("json") {
			for _, d := range result.Diagnostics {
				fmt.Printf("%s:%d:%d: %s %s\n", path, d.Line, d.Col, d.Code, d.Message)
				if d.Hint != "" {
					fmt.Printf("  hint: %s\n", d.Hint)
				}
			}
		}
	}

	if parsed.Bool("json") {
		payload := checkJSON{
			Ok:       errorsCount == 0,
			Errors:   errorsCount,
			Warnings: warnings,
			Files:    files,
		}
		encoded, _ := json.MarshalIndent(payload, "", "  ")
		fmt.Println(string(encoded))
	} else {
		fmt.Printf("checked %d file(s): %d error(s), %d warning(s)\n", len(paths), errorsCount, warnings)
	}
	if errorsCount > 0 {
		return 1
	}
	return 0
}

func readSource(path string) (string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	data = bytes.TrimPrefix(data, []byte{0xEF, 0xBB, 0xBF})
	if !utf8.Valid(data) {
		return "", fmt.Errorf("source is not valid UTF-8")
	}
	return string(data), nil
}

func expandPaths(args []string) ([]string, error) {
	var out []string
	seen := map[string]bool{}
	for _, arg := range args {
		info, err := os.Stat(arg)
		if err != nil {
			return nil, err
		}
		if info.IsDir() {
			walkErr := filepath.WalkDir(arg, func(path string, entry fs.DirEntry, err error) error {
				if err != nil {
					return err
				}
				if entry.IsDir() {
					if path != arg && excludedDirs[entry.Name()] {
						return filepath.SkipDir
					}
					return nil
				}
				if !strings.HasSuffix(entry.Name(), ".py") {
					return nil
				}
				abs, _ := filepath.Abs(path)
				if !seen[abs] {
					seen[abs] = true
					out = append(out, path)
				}
				return nil
			})
			if walkErr != nil {
				return nil, walkErr
			}
			continue
		}
		abs, _ := filepath.Abs(arg)
		if !seen[abs] {
			seen[abs] = true
			out = append(out, arg)
		}
	}
	sort.Strings(out)
	return out, nil
}

// ---------------------------------------------------------------------------
// edit command plumbing

type editFailureJSON struct {
	Ok          bool         `json:"ok"`
	Path        string       `json:"path"`
	Operation   string       `json:"operation"`
	Error       string       `json:"error"`
	Diagnostics []Diagnostic `json:"diagnostics"`
}

func failureFor(path, operation string, err error) *editFailureJSON {
	diagnostics := []Diagnostic{}
	if editErr, ok := err.(*EditError); ok {
		diagnostics = editErr.Diagnostics
		if diagnostics == nil {
			diagnostics = []Diagnostic{}
		}
	}
	return &editFailureJSON{
		Ok:          false,
		Path:        path,
		Operation:   operation,
		Error:       err.Error(),
		Diagnostics: diagnostics,
	}
}

func emitEditResult(result *EditResult, jsonOut, dryRun bool) {
	if jsonOut {
		encoded, _ := json.MarshalIndent(result, "", "  ")
		fmt.Println(string(encoded))
		return
	}
	if result.Changed {
		if result.Diff != "" {
			fmt.Print(result.Diff)
		}
		if result.Detail != "" {
			fmt.Printf("%s: %s: %s\n", result.Path, result.Operation, result.Detail)
		} else {
			fmt.Printf("%s: %s\n", result.Path, result.Operation)
		}
		if dryRun {
			fmt.Println("(dry run: file not written)")
		}
	} else {
		fmt.Printf("%s: %s: no change\n", result.Path, result.Operation)
	}
}

func emitEditFailure(path, operation string, err error, jsonOut bool) {
	payload := failureFor(path, operation, err)
	if jsonOut {
		encoded, _ := json.MarshalIndent(payload, "", "  ")
		fmt.Println(string(encoded))
		return
	}
	fmt.Fprintf(os.Stderr, "pyforai: %s: %s: %v\n", path, operation, err)
	for _, d := range payload.Diagnostics {
		fmt.Fprintf(os.Stderr, "  %s at %d:%d: %s\n", d.Code, d.Line, d.Col, d.Message)
		if d.Hint != "" {
			fmt.Fprintf(os.Stderr, "    hint: %s\n", d.Hint)
		}
	}
}

func parseAnchor(value string) (*[2]int, error) {
	if value == "" {
		return nil, nil
	}
	parts := strings.SplitN(value, ":", 2)
	if len(parts) != 2 {
		return nil, fmt.Errorf("anchor must be LINE:COL (column is 0-based)")
	}
	line, err1 := strconv.Atoi(strings.TrimSpace(parts[0]))
	col, err2 := strconv.Atoi(strings.TrimSpace(parts[1]))
	if err1 != nil || err2 != nil || line < 1 || col < 0 {
		return nil, fmt.Errorf("anchor must be LINE:COL (column is 0-based)")
	}
	return &[2]int{line, col}, nil
}

func readInput(path string) ([]byte, error) {
	if path == "-" {
		return io.ReadAll(os.Stdin)
	}
	return os.ReadFile(path)
}

// ---------------------------------------------------------------------------
// fmt

func cmdFmt(args []string) int {
	parsed, err := parseArgs(args, map[string]bool{
		"all": false, "min-lines": true, "min-depth": true, "dry-run": false, "json": false, "python-check": true, "help": false,
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	if parsed.Bool("help") {
		usage()
		return 0
	}
	minLines, err := parsed.Int("min-lines", 5)
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	minDepth, err := parsed.Int("min-depth", 3)
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	checkMode, err := pythonCheckMode(parsed.String("python-check", "off"))
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	if len(parsed.positional) == 0 {
		fmt.Fprintln(os.Stderr, "pyforai: fmt requires at least one PATH")
		return 2
	}
	paths, err := expandPaths(parsed.positional)
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}

	results := make([]any, 0, len(paths))
	failed := false
	changed := 0
	for _, path := range paths {
		result, err := Format(path, FmtOptions{
			All: parsed.Bool("all"), MinLines: minLines, MinDepth: minDepth, DryRun: parsed.Bool("dry-run"), PythonCheck: checkMode,
		})
		if err != nil {
			failed = true
			results = append(results, failureFor(path, "fmt", err))
			if !parsed.Bool("json") {
				emitEditFailure(path, "fmt", err, false)
			}
			continue
		}
		if result.Changed {
			changed++
		}
		results = append(results, result)
		if !parsed.Bool("json") && result.Changed {
			emitEditResult(result, false, parsed.Bool("dry-run"))
		}
	}
	if parsed.Bool("json") {
		payload := map[string]any{
			"ok":      !failed,
			"changed": changed,
			"results": results,
		}
		encoded, _ := json.MarshalIndent(payload, "", "  ")
		fmt.Println(string(encoded))
	} else {
		fmt.Printf("fmt: %d file(s) changed, %d checked\n", changed, len(paths))
	}
	if failed {
		return 1
	}
	return 0
}

// ---------------------------------------------------------------------------
// wrap

func cmdWrap(args []string) int {
	parsed, err := parseArgs(args, map[string]bool{
		"header": true, "anchor": true, "kind": true, "condition": true, "context": true, "python-check": true,
		"target": true, "iterable": true, "except": true, "handler": true, "handler-file": true,
		"dry-run": false, "json": false, "help": false,
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	if parsed.Bool("help") {
		usage()
		return 0
	}
	if len(parsed.positional) != 1 {
		fmt.Fprintln(os.Stderr, "pyforai: wrap requires exactly one FILE")
		return 2
	}
	path := parsed.positional[0]
	header, err := parsed.Int("header", 0)
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	anchor, err := parseAnchor(parsed.String("anchor", ""))
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	if (header > 0) == (anchor != nil) {
		fmt.Fprintln(os.Stderr, "pyforai: specify exactly one of --header and --anchor")
		return 2
	}
	kind := parsed.String("kind", "")
	if kind == "" {
		fmt.Fprintln(os.Stderr, "pyforai: --kind is required")
		return 2
	}
	handlerCode := parsed.String("handler", "")
	if handlerFile := parsed.String("handler-file", ""); handlerFile != "" {
		data, readErr := readInput(handlerFile)
		if readErr != nil {
			emitEditFailure(path, "wrap", readErr, parsed.Bool("json"))
			return 1
		}
		handlerCode = string(data)
	}
	checkMode, err := pythonCheckMode(parsed.String("python-check", "auto"))
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	result, err := Wrap(path, WrapOptions{
		Header:       header,
		Anchor:       anchor,
		Kind:         kind,
		Condition:    parsed.String("condition", ""),
		Context:      parsed.String("context", ""),
		Target:       parsed.String("target", ""),
		Iterable:     parsed.String("iterable", ""),
		ExceptClause: parsed.String("except", ""),
		Handler:      handlerCode,
		DryRun:       parsed.Bool("dry-run"),
		PythonCheck:  checkMode,
	})
	if err != nil {
		emitEditFailure(path, "wrap", err, parsed.Bool("json"))
		return 1
	}
	emitEditResult(result, parsed.Bool("json"), parsed.Bool("dry-run"))
	return 0
}

// ---------------------------------------------------------------------------
// replace-body

func cmdReplaceBody(args []string) int {
	parsed, err := parseArgs(args, map[string]bool{
		"header": true, "anchor": true, "code": true, "code-file": true, "python-check": true,
		"keep-docstring": false, "dry-run": false, "json": false, "help": false,
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	if parsed.Bool("help") {
		usage()
		return 0
	}
	if len(parsed.positional) != 1 {
		fmt.Fprintln(os.Stderr, "pyforai: replace-body requires exactly one FILE")
		return 2
	}
	path := parsed.positional[0]
	header, err := parsed.Int("header", 0)
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	anchor, err := parseAnchor(parsed.String("anchor", ""))
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	if (header > 0) == (anchor != nil) {
		fmt.Fprintln(os.Stderr, "pyforai: specify exactly one of --header and --anchor")
		return 2
	}
	code := parsed.String("code", "")
	codeFile := parsed.String("code-file", "")
	if (code == "") == (codeFile == "") {
		fmt.Fprintln(os.Stderr, "pyforai: specify exactly one of --code and --code-file")
		return 2
	}
	body := code
	if codeFile != "" {
		data, readErr := readInput(codeFile)
		if readErr != nil {
			emitEditFailure(path, "replace-body", readErr, parsed.Bool("json"))
			return 1
		}
		body = string(data)
	}
	checkMode, err := pythonCheckMode(parsed.String("python-check", "auto"))
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	result, err := ReplaceBody(path, ReplaceBodyOptions{
		Header:        header,
		Anchor:        anchor,
		Code:          body,
		KeepDocstring: parsed.Bool("keep-docstring"),
		DryRun:        parsed.Bool("dry-run"),
		PythonCheck:   checkMode,
	})
	if err != nil {
		emitEditFailure(path, "replace-body", err, parsed.Bool("json"))
		return 1
	}
	emitEditResult(result, parsed.Bool("json"), parsed.Bool("dry-run"))
	return 0
}

// ---------------------------------------------------------------------------
// move

func cmdMove(args []string) int {
	parsed, err := parseArgs(args, map[string]bool{
		"header": true, "anchor": true, "before-line": true, "after-line": true, "into-line": true, "python-check": true,
		"dry-run": false, "json": false, "help": false,
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	if parsed.Bool("help") {
		usage()
		return 0
	}
	if len(parsed.positional) != 1 {
		fmt.Fprintln(os.Stderr, "pyforai: move requires exactly one FILE")
		return 2
	}
	path := parsed.positional[0]
	header, err := parsed.Int("header", 0)
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	anchor, err := parseAnchor(parsed.String("anchor", ""))
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	if (header > 0) == (anchor != nil) {
		fmt.Fprintln(os.Stderr, "pyforai: specify exactly one of --header and --anchor")
		return 2
	}
	beforeLine, err := parsed.Int("before-line", 0)
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	afterLine, err := parsed.Int("after-line", 0)
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	intoLine, err := parsed.Int("into-line", 0)
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	checkMode, err := pythonCheckMode(parsed.String("python-check", "off"))
	if err != nil {
		fmt.Fprintf(os.Stderr, "pyforai: %v\n", err)
		return 2
	}
	result, err := Move(path, MoveOptions{
		Header:      header,
		Anchor:      anchor,
		BeforeLine:  beforeLine,
		AfterLine:   afterLine,
		IntoLine:    intoLine,
		DryRun:      parsed.Bool("dry-run"),
		PythonCheck: checkMode,
	})
	if err != nil {
		emitEditFailure(path, "move", err, parsed.Bool("json"))
		return 1
	}
	emitEditResult(result, parsed.Bool("json"), parsed.Bool("dry-run"))
	return 0
}

func pythonCheckMode(value string) (string, error) {
	switch value {
	case "", "auto":
		return "auto", nil
	case "on":
		return "on", nil
	case "off":
		return "off", nil
	default:
		return "", fmt.Errorf("--python-check must be auto, on, or off")
	}
}
