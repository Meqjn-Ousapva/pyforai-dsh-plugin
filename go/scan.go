package pyforai

import (
	"fmt"
	"regexp"
	"strings"
)

// ScanError is a structural/syntax problem found while scanning Python source.
type ScanError struct {
	Line int
	Col  int
	Msg  string
}

func (e *ScanError) Error() string {
	return fmt.Sprintf("line %d:%d: %s", e.Line, e.Col, e.Msg)
}

// Comment is a '#' comment token (never inside a string).
type Comment struct {
	Line int
	Col  int
	Text string
}

// LogicalLine is the first token of a Python logical line plus the positions
// the block parser needs.
type LogicalLine struct {
	Line        int
	EndLine     int
	Col         int
	Indent      string
	First       string
	Second      string
	Colon       int
	HasBody     bool
	IsDecorator bool
}

// Clause is one suite of a compound statement (the initial body, elif/else,
// except/finally, ...).  Line numbers are 1-based; BodyStart/BodyEnd are
// 1-based inclusive line numbers, or 0 when the clause has no recorded body.
type Clause struct {
	Kind      string
	Line      int
	EndLine   int
	BodyStart int
	BodyEnd   int
	BodyCol   int
}

// Block is a compound statement.
type Block struct {
	Kind      string
	Line      int
	Col       int
	EndLine   int
	FirstLine int
	BodyLine  int
	BodyCol   int
	OneLine   bool
	Depth     int
	Clauses   []Clause
}

type blockKey struct {
	Kind    string
	Line    int
	Col     int
	EndLine int
}

func (b Block) Key() blockKey {
	return blockKey{b.Kind, b.Line, b.Col, b.EndLine}
}

// Anchor is a parsed "# end <kind>" comment.
type Anchor struct {
	Kind string
	Line int
	Col  int
	Text string
}

// Model is everything the checker and editor need about one source text.
type Model struct {
	Src            string
	Lines          []string
	Newline        string
	FinalNewline   bool
	Blocks         []Block
	Anchors        []Anchor
	Starts         []LogicalLine
	Comments       []Comment
	StringInterior map[int]bool
	ScanErr        *ScanError
}

// Scan lexes src and builds the anchor/block model.  It does not raise on
// invalid Python; the problem is reported in Model.ScanErr.
func Scan(src string) *Model {
	m := &Model{
		Src:            src,
		Lines:          splitLines(src),
		Newline:        detectNewline(src),
		FinalNewline:   strings.HasSuffix(src, "\n") || strings.HasSuffix(src, "\r"),
		StringInterior: map[int]bool{},
	}
	l := &lexer{src: src, line: 1, stringInterior: m.StringInterior}
	l.run()
	m.Starts = l.starts
	m.Comments = l.comments
	m.Anchors = findAnchors(l.comments)
	m.ScanErr = l.err
	if l.err == nil {
		blocks, err := parseBlocks(l.starts)
		m.Blocks = blocks
		if err != nil {
			m.ScanErr = err
		}
	}
	return m
}

func splitLines(src string) []string {
	normalized := strings.ReplaceAll(src, "\r\n", "\n")
	if normalized == "" {
		return nil
	}
	parts := strings.Split(normalized, "\n")
	if len(parts) > 0 && parts[len(parts)-1] == "" {
		parts = parts[:len(parts)-1]
	}
	return parts
}

func detectNewline(src string) string {
	idx := strings.IndexByte(src, '\n')
	if idx > 0 && src[idx-1] == '\r' {
		return "\r\n"
	}
	return "\n"
}

var anchorRE = regexp.MustCompile(`^#[ \t]*end[ \t]+(if|for|while|try|with|def|class|match)[ \t]*(#.*)?$`)

func findAnchors(comments []Comment) []Anchor {
	var anchors []Anchor
	for _, c := range comments {
		m := anchorRE.FindStringSubmatch(c.Text)
		if m != nil {
			anchors = append(anchors, Anchor{Kind: m[1], Line: c.Line, Col: c.Col, Text: c.Text})
		}
	}
	return anchors
}

// ---------------------------------------------------------------------------
// lexer

type lexer struct {
	src            string
	pos            int
	line           int
	col            int
	bracketDepth   int
	current        *LogicalLine
	starts         []LogicalLine
	comments       []Comment
	stringInterior map[int]bool
	err            *ScanError
}

func (l *lexer) run() {
	for l.pos < len(l.src) {
		if l.current == nil {
			if !l.beginLine() {
				continue
			}
		}
		if l.current == nil {
			continue
		}
		l.scanToken()
		if l.err != nil {
			return
		}
	}
	if l.current != nil {
		l.current.EndLine = l.line
		l.starts = append(l.starts, *l.current)
		l.current = nil
	}
	if l.bracketDepth != 0 {
		l.err = &ScanError{l.line, l.col, "unclosed bracket"}
	}
}

func (l *lexer) beginLine() bool {
	startLine := l.line
	startPos := l.pos
	for l.pos < len(l.src) {
		c := l.src[l.pos]
		if c == ' ' || c == '\t' || c == '\f' {
			l.pos++
			l.col++
			continue
		}
		break
	}
	indent := l.src[startPos:l.pos]
	if l.pos >= len(l.src) {
		return false
	}
	c := l.src[l.pos]
	if c == '\r' || c == '\n' {
		l.consumeNewline()
		return false
	}
	if c == '#' {
		l.readComment()
		l.handleNewline()
		return false
	}
	l.current = &LogicalLine{
		Line:    startLine,
		EndLine: startLine,
		Col:     l.col,
		Indent:  indent,
		Colon:   -1,
	}
	return true
}

func (l *lexer) scanToken() {
	c := l.src[l.pos]
	switch {
	case c == ' ' || c == '\t' || c == '\f':
		l.pos++
		l.col++
	case c == '#':
		l.readComment()
		l.handleNewline()
	case c == '\r' || c == '\n':
		l.handleNewline()
	case c == '\\':
		j := l.pos + 1
		for j < len(l.src) && (l.src[j] == ' ' || l.src[j] == '\t') {
			j++
		}
		if j < len(l.src) && (l.src[j] == '\n' || l.src[j] == '\r') {
			l.pos = j
			if l.current != nil {
				l.current.EndLine = l.line
			}
			l.consumeNewline()
		} else {
			l.pos++
			l.col++
		}
	case c == '\'' || c == '"':
		l.scanString(c)
	case isIdentStart(c):
		l.scanIdent()
	case c >= '0' && c <= '9':
		l.scanNumber()
	default:
		l.scanOperator(c)
	}
}

func (l *lexer) handleNewline() {
	if l.pos >= len(l.src) {
		if l.current != nil {
			l.current.EndLine = l.line
			l.starts = append(l.starts, *l.current)
			l.current = nil
		}
		return
	}
	if l.bracketDepth > 0 {
		if l.current != nil {
			l.current.EndLine = l.line
		}
		l.consumeNewline()
		return
	}
	if l.current != nil {
		l.current.EndLine = l.line
		l.starts = append(l.starts, *l.current)
		l.current = nil
	}
	l.consumeNewline()
}

func (l *lexer) consumeNewline() {
	if l.pos >= len(l.src) {
		return
	}
	if l.src[l.pos] == '\r' {
		l.pos++
		if l.pos < len(l.src) && l.src[l.pos] == '\n' {
			l.pos++
		}
	} else if l.src[l.pos] == '\n' {
		l.pos++
	}
	l.line++
	l.col = 0
}

func (l *lexer) readComment() {
	startCol := l.col
	start := l.pos
	for l.pos < len(l.src) && l.src[l.pos] != '\n' && l.src[l.pos] != '\r' {
		l.pos++
		l.col++
	}
	l.comments = append(l.comments, Comment{Line: l.line, Col: startCol, Text: l.src[start:l.pos]})
}

func (l *lexer) scanString(quote byte) {
	startLine := l.line
	if l.current != nil && l.current.Colon >= 0 {
		l.current.HasBody = true
	}
	triple := l.pos+2 < len(l.src) && l.src[l.pos+1] == quote && l.src[l.pos+2] == quote
	if triple {
		l.advance(3)
		for l.pos < len(l.src) {
			c := l.src[l.pos]
			if c == '\\' {
				l.advance(1)
				if l.pos < len(l.src) {
					if l.src[l.pos] == '\n' || l.src[l.pos] == '\r' {
						l.consumeNewline()
					} else {
						l.advance(1)
					}
				}
				continue
			}
			if c == quote && l.pos+2 < len(l.src) && l.src[l.pos+1] == quote && l.src[l.pos+2] == quote {
				l.advance(3)
				l.markInterior(startLine, l.line)
				return
			}
			if c == '\n' || c == '\r' {
				l.consumeNewline()
				continue
			}
			l.advance(1)
		}
		l.err = &ScanError{startLine, 0, "unterminated triple-quoted string"}
		return
	}

	l.advance(1)
	for l.pos < len(l.src) {
		c := l.src[l.pos]
		if c == '\\' {
			l.advance(1)
			if l.pos < len(l.src) {
				if l.src[l.pos] == '\n' || l.src[l.pos] == '\r' {
					l.consumeNewline()
				} else {
					l.advance(1)
				}
			}
			continue
		}
		if c == quote {
			l.advance(1)
			l.markInterior(startLine, l.line)
			return
		}
		if c == '\n' || c == '\r' {
			l.err = &ScanError{l.line, l.col, "unterminated string literal"}
			return
		}
		l.advance(1)
	}
	l.err = &ScanError{startLine, 0, "unterminated string literal"}
}

func (l *lexer) markInterior(startLine, endLine int) {
	for ln := startLine + 1; ln <= endLine; ln++ {
		l.stringInterior[ln] = true
	}
}

func (l *lexer) advance(n int) {
	l.pos += n
	l.col += n
}

func (l *lexer) scanIdent() {
	start := l.pos
	for l.pos < len(l.src) && isIdentPart(l.src[l.pos]) {
		l.pos++
		l.col++
	}
	name := l.src[start:l.pos]
	if l.current == nil {
		return
	}
	if l.current.First == "" {
		l.current.First = name
	} else if l.current.First == "async" && l.current.Second == "" {
		l.current.Second = name
	}
	if l.current.Colon >= 0 {
		l.current.HasBody = true
	}
}

func (l *lexer) scanNumber() {
	if l.current != nil && l.current.First == "" {
		l.current.First = "0"
	}
	for l.pos < len(l.src) {
		c := l.src[l.pos]
		if isIdentPart(c) || c == '.' || c == '_' {
			l.pos++
			l.col++
			continue
		}
		break
	}
	if l.current != nil && l.current.Colon >= 0 {
		l.current.HasBody = true
	}
}

func (l *lexer) scanOperator(c byte) {
	switch c {
	case '(', '[', '{':
		l.bracketDepth++
	case ')', ']', '}':
		if l.bracketDepth == 0 {
			l.err = &ScanError{l.line, l.col, "unmatched closing bracket"}
			return
		}
		l.bracketDepth--
	case ':':
		if l.bracketDepth == 0 && l.current != nil && l.current.Colon < 0 {
			l.current.Colon = l.col
			l.pos++
			l.col++
			return
		}
	case '@':
		if l.current != nil && l.current.First == "" {
			l.current.First = "@"
			l.current.IsDecorator = true
		}
	}
	if l.current != nil && l.current.First == "" {
		l.current.First = string(c)
	}
	l.pos++
	l.col++
	if l.current != nil && l.current.Colon >= 0 {
		l.current.HasBody = true
	}
}

func isIdentStart(c byte) bool {
	return c == '_' || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c >= 0x80
}

func isIdentPart(c byte) bool {
	return isIdentStart(c) || (c >= '0' && c <= '9')
}

// ---------------------------------------------------------------------------
// block parser

type parser struct {
	blocks      []Block
	stack       []*Block
	pendingLine int
	pendingCol  int
	err         *ScanError
}

func parseBlocks(starts []LogicalLine) ([]Block, *ScanError) {
	p := &parser{}
	for _, ln := range starts {
		if err := p.line(ln); err != nil {
			return p.blocks, err
		}
	}
	for len(p.stack) > 0 {
		p.finalize(p.stack[len(p.stack)-1])
		p.stack = p.stack[:len(p.stack)-1]
	}
	return p.blocks, p.err
}

func (p *parser) finalize(b *Block) {
	if b.BodyLine == 0 && !b.OneLine {
		// An empty suite is a syntax error and also the signal that an edit
		// would have emptied a parent.  Record it so Commit refuses to write.
		if p.err == nil {
			p.err = &ScanError{b.Line, b.Col, "empty block"}
		}
		return
	}
	for _, c := range b.Clauses {
		if c.BodyStart == 0 {
			if p.err == nil {
				p.err = &ScanError{c.Line, b.Col, "empty clause"}
			}
			return
		}
	}
	p.blocks = append(p.blocks, *b)
}

func (p *parser) line(ln LogicalLine) *ScanError {
	for len(p.stack) > 0 {
		top := p.stack[len(p.stack)-1]
		if ln.Col > top.Col {
			break
		}
		if ln.Col == top.Col && isClauseFor(top.Kind, ln.First) {
			break
		}
		p.finalize(top)
		p.stack = p.stack[:len(p.stack)-1]
	}

	if len(p.stack) > 0 {
		top := p.stack[len(p.stack)-1]
		if ln.Col == top.Col && isClauseFor(top.Kind, ln.First) {
			p.updateAncestors(ln)
			p.addClause(top, ln)
			return nil
		}
	}

	if ln.IsDecorator {
		p.updateOpen(ln)
		if p.pendingLine == 0 {
			p.pendingLine = ln.Line
			p.pendingCol = ln.Col
		}
		return nil
	}

	kind := headerKind(ln)
	if kind != "" {
		p.updateOpen(ln)
		firstLine := ln.Line
		if (kind == "def" || kind == "class") && p.pendingLine != 0 && p.pendingCol == ln.Col {
			firstLine = p.pendingLine
		}
		p.pendingLine, p.pendingCol = 0, 0
		b := &Block{
			Kind:      kind,
			Line:      ln.Line,
			Col:       ln.Col,
			EndLine:   ln.EndLine,
			FirstLine: firstLine,
			Depth:     len(p.stack),
		}
		if ln.HasBody {
			b.OneLine = true
			b.BodyLine = ln.Line
			b.BodyCol = ln.Col
			b.Clauses = []Clause{{
				Kind:      "body",
				Line:      ln.Line,
				EndLine:   ln.EndLine,
				BodyStart: ln.Line,
				BodyEnd:   ln.EndLine,
				BodyCol:   ln.Col,
			}}
			p.blocks = append(p.blocks, *b)
		} else {
			b.Clauses = []Clause{{Kind: "body", Line: ln.Line, EndLine: ln.EndLine}}
			p.stack = append(p.stack, b)
		}
		return nil
	}

	p.pendingLine, p.pendingCol = 0, 0
	p.updateOpen(ln)
	return nil
}

func (p *parser) updateOpen(ln LogicalLine) {
	for _, b := range p.stack {
		p.updateBlock(b, ln)
	}
}

func (p *parser) updateAncestors(ln LogicalLine) {
	for i := 0; i < len(p.stack)-1; i++ {
		p.updateBlock(p.stack[i], ln)
	}
}

func (p *parser) updateBlock(b *Block, ln LogicalLine) {
	b.EndLine = maxInt(b.EndLine, ln.EndLine)
	if len(b.Clauses) == 0 {
		return
	}
	c := &b.Clauses[len(b.Clauses)-1]
	c.EndLine = maxInt(c.EndLine, ln.EndLine)
	if c.BodyStart == 0 {
		c.BodyStart = ln.Line
		c.BodyCol = ln.Col
		if b.BodyLine == 0 {
			b.BodyLine = ln.Line
			b.BodyCol = ln.Col
		}
	}
	c.BodyEnd = maxInt(c.BodyEnd, ln.EndLine)
}

func (p *parser) addClause(b *Block, ln LogicalLine) {
	b.EndLine = maxInt(b.EndLine, ln.EndLine)
	kind := ln.First
	if kind == "except" {
		kind = "except"
	}
	b.Clauses = append(b.Clauses, Clause{Kind: kind, Line: ln.Line, EndLine: ln.EndLine})
	if ln.HasBody {
		c := &b.Clauses[len(b.Clauses)-1]
		c.BodyStart = ln.Line
		c.BodyEnd = ln.EndLine
		c.BodyCol = ln.Col
	}
}

func isClauseFor(kind, first string) bool {
	switch kind {
	case "if":
		return first == "elif" || first == "else"
	case "for", "while":
		return first == "else"
	case "try":
		return first == "except" || first == "else" || first == "finally"
	}
	return false
}

func headerKind(ln LogicalLine) string {
	if ln.Colon < 0 {
		return ""
	}
	switch ln.First {
	case "if", "for", "while", "try", "with", "def", "class", "match":
		return ln.First
	case "async":
		switch ln.Second {
		case "def":
			return "def"
		case "for":
			return "for"
		case "with":
			return "with"
		}
	}
	return ""
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}

// leadingWS returns the spaces/tabs at the start of line.
func leadingWS(line string) string {
	i := 0
	for i < len(line) && (line[i] == ' ' || line[i] == '\t') {
		i++
	}
	return line[:i]
}

func isBlankLine(line string) bool {
	return strings.TrimSpace(line) == ""
}
