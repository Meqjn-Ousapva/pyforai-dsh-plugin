package pyforai

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func writeTemp(t *testing.T, data string) string {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, "m.py")
	if err := os.WriteFile(path, []byte(data), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func readTemp(t *testing.T, path string) string {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

func TestFormatAll(t *testing.T) {
	path := writeTemp(t, "def f():\n    if a:\n        for i in xs:\n            g(i)\n")
	result, err := Format(path, FmtOptions{All: true})
	if err != nil {
		t.Fatal(err)
	}
	if !result.Changed {
		t.Fatal("expected change")
	}
	want := "def f():\n" +
		"    if a:\n" +
		"        for i in xs:\n" +
		"            g(i)\n" +
		"        # end for\n" +
		"    # end if\n" +
		"# end def\n"
	if got := readTemp(t, path); got != want {
		t.Fatalf("unexpected output:\n%s\nwant:\n%s", got, want)
	}
}

func TestFormatIdempotent(t *testing.T) {
	path := writeTemp(t, "def f():\n    if a:\n        pass\n")
	if _, err := Format(path, FmtOptions{All: true}); err != nil {
		t.Fatal(err)
	}
	second, err := Format(path, FmtOptions{All: true})
	if err != nil {
		t.Fatal(err)
	}
	if second.Changed {
		t.Fatal("second fmt should be a no-op")
	}
}

func TestWrapTry(t *testing.T) {
	path := writeTemp(t, "def f(xs):\n    for x in xs:\n        use(x)\n")
	if _, err := Wrap(path, WrapOptions{
		Header: 2, Kind: "try", ExceptClause: "Exception as e", Handler: "raise",
	}); err != nil {
		t.Fatal(err)
	}
	want := "def f(xs):\n" +
		"    try:\n" +
		"        for x in xs:\n" +
		"            use(x)\n" +
		"    except Exception as e:\n" +
		"        raise\n" +
		"    # end try\n"
	if got := readTemp(t, path); got != want {
		t.Fatalf("unexpected output:\n%s\nwant:\n%s", got, want)
	}
}

func TestWrapDecoratedDef(t *testing.T) {
	path := writeTemp(t, "@deco\ndef f():\n    pass\n")
	if _, err := Wrap(path, WrapOptions{Header: 2, Kind: "if", Condition: "flag"}); err != nil {
		t.Fatal(err)
	}
	want := "if flag:\n" +
		"    @deco\n" +
		"    def f():\n" +
		"        pass\n" +
		"# end if\n"
	if got := readTemp(t, path); got != want {
		t.Fatalf("unexpected output:\n%s\nwant:\n%s", got, want)
	}
}

func TestWrapMissingParam(t *testing.T) {
	path := writeTemp(t, "if a:\n    pass\n")
	if _, err := Wrap(path, WrapOptions{Header: 1, Kind: "if", Condition: ""}); err == nil {
		t.Fatal("expected an error for missing condition")
	}
}

func TestReplaceBody(t *testing.T) {
	path := writeTemp(t, "def f():\n    a = 1\n    return a\n")
	if _, err := ReplaceBody(path, ReplaceBodyOptions{Header: 1, Code: "return 42"}); err != nil {
		t.Fatal(err)
	}
	if got := readTemp(t, path); got != "def f():\n    return 42\n" {
		t.Fatalf("unexpected output: %q", got)
	}
}

func TestReplaceBodyKeepDocstring(t *testing.T) {
	path := writeTemp(t, "def f():\n    \"\"\"Doc.\"\"\"\n    return 1\n")
	if _, err := ReplaceBody(path, ReplaceBodyOptions{Header: 1, Code: "return 2", KeepDocstring: true}); err != nil {
		t.Fatal(err)
	}
	want := "def f():\n    \"\"\"Doc.\"\"\"\n    return 2\n"
	if got := readTemp(t, path); got != want {
		t.Fatalf("unexpected output: %q", got)
	}
}

func TestReplaceBodyRemovesDocstring(t *testing.T) {
	path := writeTemp(t, "def f():\n    \"\"\"Doc.\"\"\"\n    return 1\n")
	if _, err := ReplaceBody(path, ReplaceBodyOptions{Header: 1, Code: "return 2", KeepDocstring: false}); err != nil {
		t.Fatal(err)
	}
	if strings.Contains(readTemp(t, path), "Doc.") {
		t.Fatal("docstring should have been removed")
	}
}

func TestReplaceBodyInvalidAborts(t *testing.T) {
	src := "def f():\n    return 1\n"
	path := writeTemp(t, src)
	if _, err := ReplaceBody(path, ReplaceBodyOptions{Header: 1, Code: "if True:\n"}); err == nil {
		t.Fatal("expected an error for an empty block")
	}
	if got := readTemp(t, path); got != src {
		t.Fatal("file must be unchanged after a failed edit")
	}
}

func TestReplaceBodyPythonSyntaxAborts(t *testing.T) {
	src := "def f():\n    return 1\n"
	path := writeTemp(t, src)
	if _, err := ReplaceBody(path, ReplaceBodyOptions{
		Header: 1, Code: "return 1 +", PythonCheck: "on",
	}); err == nil {
		t.Fatal("expected a python syntax error")
	}
	if got := readTemp(t, path); got != src {
		t.Fatal("file must be unchanged after a python syntax error")
	}
}

func TestMoveBefore(t *testing.T) {
	path := writeTemp(t, "def a():\n    pass\n\n\ndef b():\n    pass\n")
	if _, err := Move(path, MoveOptions{Header: 5, BeforeLine: 1}); err != nil {
		t.Fatal(err)
	}
	text := readTemp(t, path)
	if strings.Index(text, "def b") > strings.Index(text, "def a") {
		t.Fatalf("b should be before a:\n%s", text)
	}
}

func TestMoveEmptyParent(t *testing.T) {
	src := "def outer():\n    if a:\n        pass\n"
	path := writeTemp(t, src)
	if _, err := Move(path, MoveOptions{Header: 2, BeforeLine: 1}); err == nil {
		t.Fatal("expected an error when the move empties a parent")
	}
	if got := readTemp(t, path); got != src {
		t.Fatal("file must be unchanged after a failed move")
	}
}

func TestPreservesBOM(t *testing.T) {
	path := filepath.Join(t.TempDir(), "bom.py")
	data := append([]byte{0xEF, 0xBB, 0xBF}, []byte("if a:\n    pass\n")...)
	if err := os.WriteFile(path, data, 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := Format(path, FmtOptions{All: true}); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if len(raw) < 3 || raw[0] != 0xEF || raw[1] != 0xBB || raw[2] != 0xBF {
		t.Fatal("UTF-8 BOM was not preserved")
	}
}

func TestPreservesCRLF(t *testing.T) {
	path := filepath.Join(t.TempDir(), "crlf.py")
	src := "def f(xs):\r\n    for x in xs:\r\n        use(x)\r\n"
	if err := os.WriteFile(path, []byte(src), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, err := Wrap(path, WrapOptions{Header: 2, Kind: "if", Condition: "xs"}); err != nil {
		t.Fatal(err)
	}
	raw := readTemp(t, path)
	if !strings.Contains(raw, "\r\n") || strings.Contains(strings.ReplaceAll(raw, "\r\n", ""), "\n") {
		t.Fatal("CRLF was not preserved")
	}
}
