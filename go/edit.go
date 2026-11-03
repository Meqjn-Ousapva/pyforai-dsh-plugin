package pyforai

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strings"
	"unicode/utf8"
)

// EditError is a structural edit that was refused.
type EditError struct {
	Message     string
	Diagnostics []Diagnostic
}

func (e *EditError) Error() string { return e.Message }

// EditResult is the outcome of a successful edit (or dry run).
type EditResult struct {
	Ok          bool         `json:"ok"`
	Path        string       `json:"path"`
	Operation   string       `json:"operation"`
	Changed     bool         `json:"changed"`
	Detail      string       `json:"detail"`
	Diff        string       `json:"diff"`
	Diagnostics []Diagnostic `json:"diagnostics"`
}

// Document is a source file split into lines, with atomic writes.
type Document struct {
	Path         string
	Original     string
	Lines        []string
	Newline      string
	FinalNewline bool
	BOM          bool
}

func LoadDocument(path string) (*Document, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	bom := bytes.HasPrefix(data, []byte{0xEF, 0xBB, 0xBF})
	if bom {
		data = data[3:]
	}
	if !utf8.Valid(data) {
		return nil, fmt.Errorf("%s: source is not valid UTF-8", path)
	}
	text := string(data)
	return &Document{
		Path:         path,
		Original:     text,
		Lines:        splitLines(text),
		Newline:      detectNewline(text),
		FinalNewline: strings.HasSuffix(text, "\n") || strings.HasSuffix(text, "\r"),
		BOM:          bom,
	}, nil
}

func (d *Document) Render() string {
	text := strings.Join(d.Lines, d.Newline)
	if d.FinalNewline && len(d.Lines) > 0 {
		text += d.Newline
	}
	return text
}

func (d *Document) Splice(start, end int, newLines []string) {
	if start < 0 {
		start = 0
	}
	if end > len(d.Lines) {
		end = len(d.Lines)
	}
	if start > end {
		start = end
	}
	out := make([]string, 0, len(d.Lines)-(end-start)+len(newLines))
	out = append(out, d.Lines[:start]...)
	out = append(out, newLines...)
	out = append(out, d.Lines[end:]...)
	d.Lines = out
}

func (d *Document) Commit(operation string, dryRun bool, pythonCheck string, detail string) (*EditResult, error) {
	newText := d.Render()
	model := Scan(newText)
	if model.ScanErr != nil {
		return nil, &EditError{
			Message: "refusing to write: the result has a syntax/structure error",
			Diagnostics: []Diagnostic{{
				Code: "E100", Severity: "error", Line: model.ScanErr.Line, Col: model.ScanErr.Col,
				Message: model.ScanErr.Msg,
			}},
		}
	}
	result := CheckModel(model, false, 5, 3)
	if !result.Ok {
		return nil, &EditError{
			Message:     "refusing to write: the result has anchor errors",
			Diagnostics: result.Diagnostics,
		}
	}
	if err := validatePython(newText, pythonCheck); err != nil {
		return nil, err
	}
	changed := newText != d.Original
	diff := ""
	if changed {
		diff = UnifiedDiff(d.Original, newText, d.Path)
	}
	if changed && !dryRun {
		payload := []byte(newText)
		if d.BOM {
			payload = append([]byte{0xEF, 0xBB, 0xBF}, payload...)
		}
		if err := writeAtomic(d.Path, payload); err != nil {
			return nil, err
		}
	}
	return &EditResult{
		Ok:          true,
		Path:        d.Path,
		Operation:   operation,
		Changed:     changed,
		Detail:      detail,
		Diff:        diff,
		Diagnostics: []Diagnostic{},
	}, nil
}

func writeAtomic(path string, data []byte) error {
	info, err := os.Stat(path)
	if err != nil {
		return err
	}
	dir := filepath.Dir(path)
	tmp, err := os.CreateTemp(dir, ".pyforai-*")
	if err != nil {
		return err
	}
	tmpName := tmp.Name()
	defer os.Remove(tmpName)
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Chmod(info.Mode()); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmpName, path)
}

// ---------------------------------------------------------------------------
// shared helpers

func loadChecked(path string) (*Document, *Model, *CheckResult, error) {
	doc, err := LoadDocument(path)
	if err != nil {
		return nil, nil, nil, err
	}
	model := Scan(doc.Original)
	result := CheckModel(model, false, 5, 3)
	if !result.Ok {
		return nil, nil, nil, &EditError{
			Message:     fmt.Sprintf("%s: fix existing anchor errors before editing", path),
			Diagnostics: result.Diagnostics,
		}
	}
	return doc, model, result, nil
}

func resolveBlock(model *Model, matches []Match, header int, anchor *[2]int) (*Block, error) {
	if header > 0 {
		var found *Block
		for i := range model.Blocks {
			b := &model.Blocks[i]
			if b.Line != header {
				continue
			}
			if found == nil || b.Col < found.Col {
				found = b
			}
		}
		if found == nil {
			return nil, fmt.Errorf("no compound statement starts at line %d", header)
		}
		return found, nil
	}
	if anchor != nil {
		for _, m := range matches {
			if m.Anchor.Line == anchor[0] && m.Anchor.Col == anchor[1] {
				b := m.Block
				return &b, nil
			}
		}
		return nil, fmt.Errorf("no valid anchor at line %d, column %d (run `pyforai check`)", anchor[0], anchor[1])
	}
	return nil, fmt.Errorf("specify --header or --anchor")
}

func blockSpan(doc *Document, block *Block, matches []Match, includeAnchor bool) (int, int) {
	start := block.FirstLine - 1
	end := block.EndLine
	if includeAnchor {
		for _, m := range matches {
			if m.Block.Key() == block.Key() && m.Anchor.Line > end {
				return start, m.Anchor.Line
			}
		}
	}
	for end < len(doc.Lines) {
		text := doc.Lines[end]
		if strings.TrimSpace(text) == "" {
			break
		}
		trimmed := strings.TrimLeft(text, " \t")
		if strings.HasPrefix(trimmed, "#") && len(leadingWS(text)) > block.Col {
			end++
			continue
		}
		break
	}
	return start, end
}

func indentUnitForBlock(doc *Document, block *Block) string {
	if block.BodyLine <= 0 || block.BodyLine > len(doc.Lines) || block.Line > len(doc.Lines) {
		return "    "
	}
	headerPrefix := leadingWS(doc.Lines[block.Line-1])
	bodyPrefix := leadingWS(doc.Lines[block.BodyLine-1])
	if strings.HasPrefix(bodyPrefix, headerPrefix) && len(bodyPrefix) > len(headerPrefix) {
		return bodyPrefix[len(headerPrefix):]
	}
	return "    "
}

func indentLines(doc *Document, body []string, startIndex int, unit string, interior map[int]bool) []string {
	out := make([]string, 0, len(body))
	for offset, line := range body {
		lineNo := startIndex + offset + 1
		if isBlankLine(line) || interior[lineNo] {
			out = append(out, line)
		} else {
			out = append(out, unit+line)
		}
	}
	return out
}

func reindentLine(line, oldPrefix, newPrefix string) string {
	if oldPrefix == newPrefix {
		return line
	}
	if strings.HasPrefix(line, oldPrefix) {
		return newPrefix + line[len(oldPrefix):]
	}
	return line
}

func looksLikeString(line string) bool {
	s := strings.TrimLeft(line, " \t")
	if s == "" {
		return false
	}
	if s[0] == '\'' || s[0] == '"' {
		return true
	}
	i := 0
	for i < len(s) && strings.ContainsRune("rRbBuUfF", rune(s[i])) {
		i++
	}
	return i > 0 && i < len(s) && (s[i] == '\'' || s[i] == '"')
}

func dedentText(code string) []string {
	code = strings.ReplaceAll(code, "\r\n", "\n")
	code = strings.TrimRight(code, "\n")
	if strings.TrimSpace(code) == "" {
		return nil
	}
	raw := strings.Split(code, "\n")
	min := -1
	for _, line := range raw {
		if strings.TrimSpace(line) == "" {
			continue
		}
		n := len(leadingWS(line))
		if min < 0 || n < min {
			min = n
		}
	}
	if min < 0 {
		return nil
	}
	out := make([]string, len(raw))
	for i, line := range raw {
		if len(line) >= min {
			out[i] = line[min:]
		} else {
			out[i] = line
		}
	}
	return out
}

// ---------------------------------------------------------------------------
// fmt

type FmtOptions struct {
	All         bool
	MinLines    int
	MinDepth    int
	DryRun      bool
	PythonCheck string
}

func Format(path string, opts FmtOptions) (*EditResult, error) {
	doc, model, result, err := loadChecked(path)
	if err != nil {
		return nil, err
	}
	matched := map[blockKey]bool{}
	for _, m := range result.Matches {
		matched[m.Block.Key()] = true
	}
	type insertion struct {
		after  int
		col    int
		kind   string
		prefix string
	}
	var plan []insertion
	for _, b := range model.Blocks {
		if b.OneLine || matched[b.Key()] {
			continue
		}
		span := b.EndLine - b.Line + 1
		if !opts.All && span < opts.MinLines && b.Depth < opts.MinDepth {
			continue
		}
		after := b.EndLine
		for after < len(doc.Lines) {
			text := doc.Lines[after]
			if strings.TrimSpace(text) == "" {
				break
			}
			trimmed := strings.TrimLeft(text, " \t")
			if strings.HasPrefix(trimmed, "#") && len(leadingWS(text)) > b.Col {
				after++
				continue
			}
			break
		}
		plan = append(plan, insertion{
			after:  after,
			col:    b.Col,
			kind:   b.Kind,
			prefix: leadingWS(doc.Lines[b.Line-1]),
		})
	}
	if len(plan) == 0 {
		return &EditResult{Ok: true, Path: path, Operation: "fmt", Changed: false, Diagnostics: []Diagnostic{}}, nil
	}
	sort.SliceStable(plan, func(i, j int) bool {
		if plan[i].after != plan[j].after {
			return plan[i].after > plan[j].after
		}
		return plan[i].col < plan[j].col
	})
	for _, ins := range plan {
		line := ins.prefix + "# end " + ins.kind
		doc.Splice(ins.after, ins.after, []string{line})
	}
	return doc.Commit("fmt", opts.DryRun, opts.PythonCheck, fmt.Sprintf("inserted %d anchor(s)", len(plan)))
}

// ---------------------------------------------------------------------------
// wrap

type WrapOptions struct {
	Header       int
	Anchor       *[2]int
	Kind         string
	Condition    string
	Context      string
	Target       string
	Iterable     string
	ExceptClause string
	Handler      string
	DryRun       bool
	PythonCheck  string
}

func Wrap(path string, opts WrapOptions) (*EditResult, error) {
	switch opts.Kind {
	case "try", "if", "with", "for", "while":
	default:
		return nil, fmt.Errorf("unsupported wrapper kind: %q", opts.Kind)
	}
	doc, model, result, err := loadChecked(path)
	if err != nil {
		return nil, err
	}
	block, err := resolveBlock(model, result.Matches, opts.Header, opts.Anchor)
	if err != nil {
		return nil, err
	}
	unit := indentUnitForBlock(doc, block)
	base := leadingWS(doc.Lines[block.FirstLine-1])
	start, end := blockSpan(doc, block, result.Matches, true)

	var headerLine string
	var trailer []string
	switch opts.Kind {
	case "try":
		clause := strings.TrimSpace(opts.ExceptClause)
		if clause == "" {
			clause = "Exception"
		}
		clause = strings.TrimSuffix(clause, ":")
		handler := opts.Handler
		if strings.TrimSpace(handler) == "" {
			handler = "raise"
		}
		headerLine = base + "try:"
		trailer = []string{base + "except " + clause + ":"}
		handlerLines := dedentText(handler)
		if len(handlerLines) == 0 {
			handlerLines = []string{"pass"}
		}
		for _, line := range handlerLines {
			if strings.TrimSpace(line) == "" {
				trailer = append(trailer, "")
			} else {
				trailer = append(trailer, base+unit+line)
			}
		}
		trailer = append(trailer, base+"# end try")
	case "if":
		if strings.TrimSpace(opts.Condition) == "" {
			return nil, fmt.Errorf("condition is required")
		}
		headerLine = base + "if " + opts.Condition + ":"
		trailer = []string{base + "# end if"}
	case "with":
		if strings.TrimSpace(opts.Context) == "" {
			return nil, fmt.Errorf("context is required")
		}
		headerLine = base + "with " + opts.Context + ":"
		trailer = []string{base + "# end with"}
	case "for":
		if strings.TrimSpace(opts.Target) == "" || strings.TrimSpace(opts.Iterable) == "" {
			return nil, fmt.Errorf("target and iterable are required")
		}
		headerLine = base + "for " + opts.Target + " in " + opts.Iterable + ":"
		trailer = []string{base + "# end for"}
	case "while":
		if strings.TrimSpace(opts.Condition) == "" {
			return nil, fmt.Errorf("condition is required")
		}
		headerLine = base + "while " + opts.Condition + ":"
		trailer = []string{base + "# end while"}
	}

	body := append([]string{}, doc.Lines[start:end]...)
	indented := indentLines(doc, body, start, unit, model.StringInterior)
	newLines := []string{headerLine}
	newLines = append(newLines, indented...)
	newLines = append(newLines, trailer...)
	doc.Splice(start, end, newLines)
	return doc.Commit("wrap", opts.DryRun, opts.PythonCheck, fmt.Sprintf("wrapped `%s` at line %d in `%s`", block.Kind, block.Line, opts.Kind))
}

// ---------------------------------------------------------------------------
// replace-body

type ReplaceBodyOptions struct {
	Header        int
	Anchor        *[2]int
	Code          string
	KeepDocstring bool
	DryRun        bool
	PythonCheck   string
}

func ReplaceBody(path string, opts ReplaceBodyOptions) (*EditResult, error) {
	doc, model, result, err := loadChecked(path)
	if err != nil {
		return nil, err
	}
	block, err := resolveBlock(model, result.Matches, opts.Header, opts.Anchor)
	if err != nil {
		return nil, err
	}
	if block.Kind == "match" {
		return nil, fmt.Errorf("replace-body is not supported for `match`; target a case body instead")
	}
	if block.OneLine {
		return nil, fmt.Errorf("cannot replace the body of a one-line `%s`; expand it to multiple lines first", block.Kind)
	}
	if len(block.Clauses) == 0 || block.Clauses[0].BodyStart == 0 {
		return nil, fmt.Errorf("`%s` at line %d has no body", block.Kind, block.Line)
	}
	clause := block.Clauses[0]
	unit := indentUnitForBlock(doc, block)
	base := leadingWS(doc.Lines[block.FirstLine-1])
	bodyIndent := base + unit

	start := clause.BodyStart - 1
	end := clause.BodyEnd
	removedDocstring := false
	if start >= 0 && start < len(doc.Lines) && looksLikeString(doc.Lines[start]) {
		if opts.KeepDocstring {
			found := false
			for _, ll := range model.Starts {
				if ll.Line == clause.BodyStart {
					start = ll.EndLine
					found = true
					break
				}
			}
			if !found {
				return nil, fmt.Errorf("could not locate the docstring end at line %d", clause.BodyStart)
			}
		} else {
			removedDocstring = true
		}
	}

	codeLines := dedentText(opts.Code)
	if len(codeLines) == 0 {
		codeLines = []string{"pass"}
	}
	newLines := make([]string, 0, len(codeLines))
	for _, line := range codeLines {
		if strings.TrimSpace(line) == "" {
			newLines = append(newLines, "")
		} else {
			newLines = append(newLines, bodyIndent+line)
		}
	}
	doc.Splice(start, end, newLines)
	detail := fmt.Sprintf("replaced body of `%s` at line %d", block.Kind, block.Line)
	if removedDocstring {
		detail += "; docstring removed"
	}
	return doc.Commit("replace-body", opts.DryRun, opts.PythonCheck, detail)
}

// ---------------------------------------------------------------------------
// move

type MoveOptions struct {
	Header      int
	Anchor      *[2]int
	BeforeLine  int
	AfterLine   int
	IntoLine    int
	DryRun      bool
	PythonCheck string
}

func Move(path string, opts MoveOptions) (*EditResult, error) {
	count := 0
	if opts.BeforeLine > 0 {
		count++
	}
	if opts.AfterLine > 0 {
		count++
	}
	if opts.IntoLine > 0 {
		count++
	}
	if count != 1 {
		return nil, fmt.Errorf("specify exactly one of --before-line, --after-line, --into-line")
	}
	doc, model, result, err := loadChecked(path)
	if err != nil {
		return nil, err
	}
	block, err := resolveBlock(model, result.Matches, opts.Header, opts.Anchor)
	if err != nil {
		return nil, err
	}
	start, end := blockSpan(doc, block, result.Matches, true)
	oldPrefix := ""
	if start < len(doc.Lines) {
		oldPrefix = leadingWS(doc.Lines[start])
	}

	var destPos int
	var destIndent string
	var destinationDesc string
	if opts.IntoLine > 0 {
		var destination *Block
		for i := range model.Blocks {
			if model.Blocks[i].Line == opts.IntoLine {
				destination = &model.Blocks[i]
				break
			}
		}
		if destination == nil {
			return nil, fmt.Errorf("no compound statement starts at line %d", opts.IntoLine)
		}
		if destination.Kind == "match" {
			return nil, fmt.Errorf("`into` is not supported for `match`; target a case body instead")
		}
		if destination.Key() == block.Key() ||
			(destination.Line >= block.FirstLine && destination.EndLine <= block.EndLine) {
			return nil, fmt.Errorf("cannot move a block into itself or one of its descendants")
		}
		if len(destination.Clauses) == 0 || destination.Clauses[0].BodyEnd == 0 {
			return nil, fmt.Errorf("`%s` at line %d has no body", destination.Kind, opts.IntoLine)
		}
		destPos = destination.Clauses[0].BodyEnd
		destIndent = leadingWS(doc.Lines[destination.FirstLine-1]) + indentUnitForBlock(doc, destination)
		destinationDesc = fmt.Sprintf("into block at line %d", opts.IntoLine)
	} else {
		line := opts.BeforeLine
		if opts.AfterLine > 0 {
			line = opts.AfterLine
		}
		stmtStart, stmtEnd, err := statementSpan(model, result.Matches, doc, line)
		if err != nil {
			return nil, err
		}
		if opts.BeforeLine > 0 {
			destPos = stmtStart - 1
			destinationDesc = fmt.Sprintf("before line %d", opts.BeforeLine)
		} else {
			destPos = stmtEnd
			destinationDesc = fmt.Sprintf("after line %d", opts.AfterLine)
		}
		destIndent = leadingWS(doc.Lines[stmtStart-1])
	}

	if start <= destPos && destPos <= end {
		return nil, fmt.Errorf("destination is inside the block being moved")
	}
	// Moving the only statement of a parent leaves an empty suite.
	for _, parent := range model.Blocks {
		if parent.Line >= block.FirstLine || parent.EndLine < block.EndLine || parent.Col >= block.Col {
			continue
		}
		if len(parent.Clauses) > 0 &&
			parent.Clauses[0].BodyStart == block.FirstLine &&
			parent.Clauses[0].BodyEnd == block.EndLine {
			return nil, fmt.Errorf("moving this block would leave its parent without a body")
		}
	}

	moved := append([]string{}, doc.Lines[start:end]...)
	remaining := make([]string, 0, len(doc.Lines)-(end-start))
	remaining = append(remaining, doc.Lines[:start]...)
	remaining = append(remaining, doc.Lines[end:]...)
	if destPos > end {
		destPos -= end - start
	}
	reindented := make([]string, 0, len(moved))
	for i, line := range moved {
		lineNo := start + i + 1
		if isBlankLine(line) || model.StringInterior[lineNo] {
			reindented = append(reindented, line)
		} else {
			reindented = append(reindented, reindentLine(line, oldPrefix, destIndent))
		}
	}
	out := make([]string, 0, len(remaining)+len(reindented))
	out = append(out, remaining[:destPos]...)
	out = append(out, reindented...)
	out = append(out, remaining[destPos:]...)
	doc.Lines = out
	return doc.Commit("move", opts.DryRun, opts.PythonCheck, fmt.Sprintf("moved `%s` from line %d %s", block.Kind, block.Line, destinationDesc))
}

func statementSpan(model *Model, matches []Match, doc *Document, line int) (int, int, error) {
	for _, b := range model.Blocks {
		if b.Line == line {
			start := b.FirstLine
			_, end := blockSpan(doc, &b, matches, true)
			return start, end, nil
		}
	}
	for _, ll := range model.Starts {
		if ll.Line == line {
			return ll.Line, ll.EndLine, nil
		}
	}
	return 0, 0, fmt.Errorf("no statement starts at line %d", line)
}

// ---------------------------------------------------------------------------
// diff

type diffOp struct {
	kind byte
	text string
}

func UnifiedDiff(oldText, newText, path string) string {
	a := splitLines(oldText)
	b := splitLines(newText)
	if len(a) == len(b) {
		same := true
		for i := range a {
			if a[i] != b[i] {
				same = false
				break
			}
		}
		if same {
			return ""
		}
	}
	ops := diffOps(a, b)
	var changed []int
	for i, op := range ops {
		if op.kind != ' ' {
			changed = append(changed, i)
		}
	}
	if len(changed) == 0 {
		return ""
	}
	const context = 3
	type hunk struct{ start, end int }
	var hunks []hunk
	hStart := maxInt(0, changed[0]-context)
	hEnd := minInt(len(ops), changed[0]+context+1)
	for _, idx := range changed[1:] {
		if idx-context <= hEnd {
			hEnd = minInt(len(ops), idx+context+1)
		} else {
			hunks = append(hunks, hunk{hStart, hEnd})
			hStart = maxInt(0, idx-context)
			hEnd = minInt(len(ops), idx+context+1)
		}
	}
	hunks = append(hunks, hunk{hStart, hEnd})

	oldNo := make([]int, len(ops)+1)
	newNo := make([]int, len(ops)+1)
	o, n := 1, 1
	for i, op := range ops {
		oldNo[i] = o
		newNo[i] = n
		switch op.kind {
		case ' ':
			o++
			n++
		case '-':
			o++
		case '+':
			n++
		}
	}
	oldNo[len(ops)] = o
	newNo[len(ops)] = n

	var sb strings.Builder
	fmt.Fprintf(&sb, "--- a/%s\n+++ b/%s\n", path, path)
	for _, h := range hunks {
		oldCount, newCount := 0, 0
		for _, op := range ops[h.start:h.end] {
			if op.kind != '+' {
				oldCount++
			}
			if op.kind != '-' {
				newCount++
			}
		}
		fmt.Fprintf(&sb, "@@ -%d,%d +%d,%d @@\n", oldNo[h.start], oldCount, newNo[h.start], newCount)
		for _, op := range ops[h.start:h.end] {
			sb.WriteByte(op.kind)
			sb.WriteString(op.text)
			sb.WriteByte('\n')
		}
	}
	return sb.String()
}

func diffOps(a, b []string) []diffOp {
	n, m := len(a), len(b)
	if n*m > 4_000_000 {
		ops := make([]diffOp, 0, n+m)
		for _, line := range a {
			ops = append(ops, diffOp{'-', line})
		}
		for _, line := range b {
			ops = append(ops, diffOp{'+', line})
		}
		return ops
	}
	dp := make([][]int, n+1)
	for i := range dp {
		dp[i] = make([]int, m+1)
	}
	for i := n - 1; i >= 0; i-- {
		for j := m - 1; j >= 0; j-- {
			if a[i] == b[j] {
				dp[i][j] = dp[i+1][j+1] + 1
			} else if dp[i+1][j] >= dp[i][j+1] {
				dp[i][j] = dp[i+1][j]
			} else {
				dp[i][j] = dp[i][j+1]
			}
		}
	}
	var ops []diffOp
	i, j := 0, 0
	for i < n && j < m {
		if a[i] == b[j] {
			ops = append(ops, diffOp{' ', a[i]})
			i++
			j++
		} else if dp[i+1][j] >= dp[i][j+1] {
			ops = append(ops, diffOp{'-', a[i]})
			i++
		} else {
			ops = append(ops, diffOp{'+', b[j]})
			j++
		}
	}
	for ; i < n; i++ {
		ops = append(ops, diffOp{'-', a[i]})
	}
	for ; j < m; j++ {
		ops = append(ops, diffOp{'+', b[j]})
	}
	return ops
}

func minInt(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// validatePython runs CPython's compiler on the edited text when available.
// The Go scanner is structural; CPython catches expression/statement syntax
// errors that indentation-based scanning cannot.  mode is auto/on/off.
func validatePython(text, mode string) error {
	if mode == "" {
		mode = "auto"
	}
	if mode == "off" {
		return nil
	}
	python, err := exec.LookPath("python3")
	if err != nil {
		if mode == "on" {
			return fmt.Errorf("python3 not found for --python-check=on")
		}
		return nil
	}
	dir, err := os.MkdirTemp("", "pyforai-validate-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(dir)
	path := filepath.Join(dir, "check.py")
	if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
		return err
	}
	cmd := exec.Command(python, "-m", "py_compile", path)
	out, err := cmd.CombinedOutput()
	if err != nil {
		message := strings.TrimSpace(string(out))
		if message == "" {
			message = err.Error()
		}
		return &EditError{
			Message: "refusing to write: python syntax error",
			Diagnostics: []Diagnostic{{
				Code: "E100", Severity: "error", Line: 0, Col: 0, Message: message,
			}},
		}
	}
	return nil
}
