package pyforai

import (
	"strings"
	"testing"
)

func codes(src string, strict bool, minLines, minDepth int) []string {
	model := Scan(src)
	result := CheckModel(model, strict, minLines, minDepth)
	out := make([]string, 0, len(result.Diagnostics))
	for _, d := range result.Diagnostics {
		out = append(out, d.Code)
	}
	return out
}

func hasCode(list []string, code string) bool {
	for _, item := range list {
		if item == code {
			return true
		}
	}
	return false
}

func TestCheckValidNested(t *testing.T) {
	src := "def f(xs):\n" +
		"    for x in xs:\n" +
		"        if x:\n" +
		"            use(x)\n" +
		"        # end if\n" +
		"    # end for\n"
	model := Scan(src)
	result := CheckModel(model, false, 5, 3)
	if !result.Ok {
		t.Fatalf("expected ok, got %+v", result.Diagnostics)
	}
	if len(result.Matches) != 2 {
		t.Fatalf("expected 2 matches, got %d", len(result.Matches))
	}
}

func TestCheckKindMismatch(t *testing.T) {
	src := "for x in xs:\n    if x:\n        pass\n# end if\n"
	if !hasCode(codes(src, false, 5, 3), "E001") {
		t.Fatalf("expected E001, got %v", codes(src, false, 5, 3))
	}
}

func TestCheckInsideElse(t *testing.T) {
	src := "if a:\n    f()\n# end if\nelse:\n    g()\n"
	if !hasCode(codes(src, false, 5, 3), "E003") {
		t.Fatalf("expected E003, got %v", codes(src, false, 5, 3))
	}
}

func TestCheckNotAdjacent(t *testing.T) {
	src := "if a:\n    f()\ng()\n# end if\n"
	if !hasCode(codes(src, false, 5, 3), "E004") {
		t.Fatalf("expected E004, got %v", codes(src, false, 5, 3))
	}
}

func TestCheckBadNesting(t *testing.T) {
	src := "if a:\n    for i in xs:\n        pass\n# end if\n    # end for\n"
	if !hasCode(codes(src, false, 5, 3), "E008") {
		t.Fatalf("expected E008, got %v", codes(src, false, 5, 3))
	}
}

func TestCheckTrailingAnchor(t *testing.T) {
	src := "if a:\n    pass  # end if\n"
	if !hasCode(codes(src, false, 5, 3), "E007") {
		t.Fatalf("expected E007, got %v", codes(src, false, 5, 3))
	}
}

func TestCheckStrict(t *testing.T) {
	src := "def f():\n    a = 1\n    b = 2\n    c = 3\n    return a + b + c\n"
	if !hasCode(codes(src, true, 3, 10), "E010") {
		t.Fatalf("expected E010, got %v", codes(src, true, 3, 10))
	}
	if hasCode(codes(src, true, 99, 99), "E010") {
		t.Fatalf("expected no E010 with high thresholds")
	}
}

func TestCheckAnchorsInStringsIgnored(t *testing.T) {
	src := "s = \"\"\"\n# end if\nfor x in y:\n\"\"\"\n"
	if got := codes(src, false, 5, 3); len(got) != 0 {
		t.Fatalf("expected no diagnostics, got %v", got)
	}
}

func TestCheckEdgeFile(t *testing.T) {
	src := `"""edge"""
@deco
def f(x):
    if x:
        return x
    # end if
# end def

async def g(items):
    async for item in items:
        async with lock:
            use(item)
        # end with
    # end for
# end def

def classify(v):
    match v:
        case 1:
            return "one"
        case _:
            return "other"
    # end match
# end def
`
	model := Scan(src)
	if model.ScanErr != nil {
		t.Fatalf("scan error: %v", model.ScanErr)
	}
	result := CheckModel(model, false, 5, 3)
	if !result.Ok {
		var messages []string
		for _, d := range result.Diagnostics {
			messages = append(messages, d.Code+" "+d.Message)
		}
		t.Fatalf("edge file failed: %s", strings.Join(messages, "; "))
	}
}
