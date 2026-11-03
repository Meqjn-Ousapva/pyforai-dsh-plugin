package pyforai

import (
	"testing"
)

func TestScanSmoke(t *testing.T) {
	src := `"""module"""


@deco
def f(xs):
    for x in xs:
        if x > 0:
            use(x)
        # end if
    # end for
# end def


async def g():
    async for x in xs:
        async with lock:
            use(x)
        # end with
    # end for
# end def


class C:
    def m(self):
        try:
            work()
        except Exception:
            recover()
        finally:
            cleanup()
        # end try
    # end def
# end class


match x:
    case 1:
        pass
    case _:
        pass
# end match

if a: pass
`
	m := Scan(src)
	if m.ScanErr != nil {
		t.Fatalf("scan error: %v", m.ScanErr)
	}
	for _, b := range m.Blocks {
		t.Logf("%s line=%d col=%d end=%d first=%d body=%d depth=%d one=%v clauses=%d",
			b.Kind, b.Line, b.Col, b.EndLine, b.FirstLine, b.BodyLine, b.Depth, b.OneLine, len(b.Clauses))
	}
	t.Logf("anchors=%d starts=%d", len(m.Anchors), len(m.Starts))
	if len(m.Blocks) < 10 {
		t.Fatalf("expected blocks, got %d", len(m.Blocks))
	}
}

func TestScanMultilineString(t *testing.T) {
	src := "def f():\n    s = \"\"\"\n# end if\nfor x in y:\n\"\"\"\n    return s\n# end def\n"
	m := Scan(src)
	if m.ScanErr != nil {
		t.Fatalf("scan error: %v", m.ScanErr)
	}
	if len(m.Anchors) != 1 || m.Anchors[0].Line != 7 {
		t.Fatalf("only the real `# end def` anchor should be found, got %v", m.Anchors)
	}
	if len(m.Blocks) != 1 || m.Blocks[0].Kind != "def" {
		t.Fatalf("unexpected blocks: %+v", m.Blocks)
	}
}
