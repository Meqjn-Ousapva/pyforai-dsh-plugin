package pyforai

import (
	"fmt"
	"sort"
	"strings"
)

// Diagnostic is one machine-readable problem.
type Diagnostic struct {
	Code     string `json:"code"`
	Severity string `json:"severity"`
	Line     int    `json:"line"`
	Col      int    `json:"col"`
	Message  string `json:"message"`
	Hint     string `json:"hint"`
}

// Match is a validated anchor-to-block binding.
type Match struct {
	Anchor Anchor
	Block  Block
}

// CheckResult is the outcome of validating one source text.
type CheckResult struct {
	Ok          bool
	Diagnostics []Diagnostic
	Matches     []Match
	Model       *Model
}

func (r *CheckResult) Errors() int {
	n := 0
	for _, d := range r.Diagnostics {
		if d.Severity == "error" {
			n++
		}
	}
	return n
}

// CheckModel validates every anchor in m.  If strict is set, blocks that span
// at least minLines lines or are nested at least minDepth deep must have
// anchors too.
func CheckModel(m *Model, strict bool, minLines, minDepth int) *CheckResult {
	if m.ScanErr != nil {
		return &CheckResult{
			Ok: false,
			Diagnostics: []Diagnostic{{
				Code:     "E100",
				Severity: "error",
				Line:     m.ScanErr.Line,
				Col:      m.ScanErr.Col,
				Message:  "syntax error: " + m.ScanErr.Msg,
				Hint:     "fix the syntax error before checking anchors",
			}},
			Model: m,
		}
	}
	diagnostics, matches := matchAnchors(m)
	if strict {
		diagnostics = append(diagnostics, missingAnchors(m, matches, minLines, minDepth)...)
	}
	ok := true
	for _, d := range diagnostics {
		if d.Severity == "error" {
			ok = false
			break
		}
	}
	sort.SliceStable(diagnostics, func(i, j int) bool {
		if diagnostics[i].Line != diagnostics[j].Line {
			return diagnostics[i].Line < diagnostics[j].Line
		}
		if diagnostics[i].Col != diagnostics[j].Col {
			return diagnostics[i].Col < diagnostics[j].Col
		}
		return diagnostics[i].Code < diagnostics[j].Code
	})
	return &CheckResult{Ok: ok, Diagnostics: diagnostics, Matches: matches, Model: m}
}

func matchAnchors(m *Model) ([]Diagnostic, []Match) {
	diagnostics := []Diagnostic{}
	matches := []Match{}
	consumed := map[blockKey]bool{}

	for _, anchor := range m.Anchors {
		lineText := ""
		if anchor.Line >= 1 && anchor.Line <= len(m.Lines) {
			lineText = m.Lines[anchor.Line-1]
		}
		prefixEnd := anchor.Col
		if prefixEnd > len(lineText) {
			prefixEnd = len(lineText)
		}
		if strings.TrimSpace(lineText[:prefixEnd]) != "" {
			diagnostics = append(diagnostics, Diagnostic{
				Code: "E007", Severity: "error", Line: anchor.Line, Col: anchor.Col,
				Message: "anchor must be on its own line (code appears before the comment)",
				Hint:    "move `# end ...` to its own line at the block header's indentation",
			})
			continue
		}

		var before []Block
		for _, b := range m.Blocks {
			if b.Col == anchor.Col && b.Line < anchor.Line {
				before = append(before, b)
			}
		}
		if len(before) == 0 {
			diagnostics = append(diagnostics, Diagnostic{
				Code: "E002", Severity: "error", Line: anchor.Line, Col: anchor.Col,
				Message: fmt.Sprintf("no compound statement header at column %d", anchor.Col),
				Hint:    "align the anchor with the header of the block it closes",
			})
			continue
		}

		candidate := before[0]
		for _, b := range before[1:] {
			if b.Line > candidate.Line {
				candidate = b
			}
		}

		if candidate.EndLine >= anchor.Line {
			extra := ""
			for _, c := range candidate.Clauses {
				if c.Kind == "else" || c.Kind == "elif" || c.Kind == "except" || c.Kind == "finally" {
					extra = " (it continues into a clause)"
					break
				}
			}
			diagnostics = append(diagnostics, Diagnostic{
				Code: "E003", Severity: "error", Line: anchor.Line, Col: anchor.Col,
				Message: fmt.Sprintf("the `%s` at line %d ends at line %d%s; the anchor is inside it",
					candidate.Kind, candidate.Line, candidate.EndLine, extra),
				Hint: fmt.Sprintf("move the anchor after line %d", candidate.EndLine),
			})
			continue
		}

		between := false
		betweenLine := 0
		for _, s := range m.Starts {
			if s.Line > candidate.EndLine && s.Line < anchor.Line {
				between = true
				betweenLine = s.Line
				break
			}
		}
		if between {
			diagnostics = append(diagnostics, Diagnostic{
				Code: "E004", Severity: "error", Line: anchor.Line, Col: anchor.Col,
				Message: fmt.Sprintf("code at line %d sits between the end of the `%s` (line %d) and the anchor",
					betweenLine, candidate.Kind, candidate.EndLine),
				Hint: fmt.Sprintf("move the anchor directly after line %d, or move it after the enclosing block", candidate.EndLine),
			})
			continue
		}

		if candidate.Kind != anchor.Kind {
			hint := fmt.Sprintf("the block ending here is `%s` (opened at line %d); write `# end %s`",
				candidate.Kind, candidate.Line, candidate.Kind)
			var previous *Block
			for _, b := range m.Blocks {
				if b.Col == anchor.Col && b.Kind == anchor.Kind && b.EndLine < candidate.Line {
					if previous == nil || b.EndLine > previous.EndLine {
						copy := b
						previous = &copy
					}
				}
			}
			if previous != nil {
				hint += fmt.Sprintf(", or move the anchor above the `%s` (the `%s` ended at line %d)",
					candidate.Kind, anchor.Kind, previous.EndLine)
			}
			diagnostics = append(diagnostics, Diagnostic{
				Code: "E001", Severity: "error", Line: anchor.Line, Col: anchor.Col,
				Message: fmt.Sprintf("kind mismatch: the block at column %d is `%s` (line %d), not `%s`",
					anchor.Col, candidate.Kind, candidate.Line, anchor.Kind),
				Hint: hint,
			})
			continue
		}

		if consumed[candidate.Key()] {
			diagnostics = append(diagnostics, Diagnostic{
				Code: "E005", Severity: "error", Line: anchor.Line, Col: anchor.Col,
				Message: fmt.Sprintf("duplicate anchor: the `%s` at line %d is already closed",
					candidate.Kind, candidate.Line),
				Hint: "remove one of the anchors",
			})
			continue
		}

		var next *LogicalLine
		for i := range m.Starts {
			if m.Starts[i].Line > anchor.Line {
				next = &m.Starts[i]
				break
			}
		}
		if next != nil && next.Col > anchor.Col {
			diagnostics = append(diagnostics, Diagnostic{
				Code: "E006", Severity: "error", Line: anchor.Line, Col: anchor.Col,
				Message: fmt.Sprintf("the first code after the anchor is at column %d (line %d), deeper than the anchor (column %d)",
					next.Col, next.Line, anchor.Col),
				Hint: "the block does not end here; move the anchor after the block",
			})
			continue
		}

		consumed[candidate.Key()] = true
		matches = append(matches, Match{Anchor: anchor, Block: candidate})
	}

	reported := map[[2]int]bool{}
	for _, outer := range matches {
		for _, inner := range matches {
			if outer.Anchor.Line == inner.Anchor.Line && outer.Anchor.Col == inner.Anchor.Col {
				continue
			}
			if containsBlock(outer.Block, inner.Block) && outer.Anchor.Line < inner.Anchor.Line {
				key := [2]int{outer.Anchor.Line, outer.Anchor.Col}
				if reported[key] {
					continue
				}
				reported[key] = true
				diagnostics = append(diagnostics, Diagnostic{
					Code: "E008", Severity: "error", Line: outer.Anchor.Line, Col: outer.Anchor.Col,
					Message: fmt.Sprintf("the anchor for the outer `%s` (line %d) appears before the anchor for the inner `%s` (line %d)",
						outer.Block.Kind, outer.Anchor.Line, inner.Block.Kind, inner.Anchor.Line),
					Hint: fmt.Sprintf("move `# end %s` after line %d", outer.Block.Kind, inner.Anchor.Line),
				})
			}
		}
	}

	return diagnostics, matches
}

func containsBlock(outer, inner Block) bool {
	if outer.Line == inner.Line && outer.Col == inner.Col && outer.EndLine == inner.EndLine {
		return false
	}
	return outer.Line <= inner.Line && inner.EndLine <= outer.EndLine
}

func missingAnchors(m *Model, matches []Match, minLines, minDepth int) []Diagnostic {
	matched := map[blockKey]bool{}
	for _, match := range matches {
		matched[match.Block.Key()] = true
	}
	var diagnostics []Diagnostic
	for _, b := range m.Blocks {
		if b.OneLine || matched[b.Key()] {
			continue
		}
		span := b.EndLine - b.Line + 1
		if span >= minLines || b.Depth >= minDepth {
			diagnostics = append(diagnostics, Diagnostic{
				Code: "E010", Severity: "error", Line: b.Line, Col: b.Col,
				Message: fmt.Sprintf("missing anchor for `%s` at line %d (block spans %d lines, depth %d)",
					b.Kind, b.Line, span, b.Depth),
				Hint: fmt.Sprintf("add `# end %s` after line %d (or run `pyforai fmt`)", b.Kind, b.EndLine),
			})
		}
	}
	return diagnostics
}
