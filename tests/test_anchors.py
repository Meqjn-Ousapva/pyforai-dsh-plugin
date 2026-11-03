"""Tests for the anchor/block model."""

from __future__ import annotations

import unittest

from pyforai.anchors import (
    ANCHOR_RE,
    Block,
    build_model,
    contains_block,
    detect_newline,
    find_anchors,
    logical_starts,
    string_interior_lines,
)

ALL_KINDS = '''\
if a:
    pass
# end if

for i in xs:
    pass
# end for

while a:
    pass
# end while

try:
    pass
except Exception:
    pass
# end try

with lock:
    pass
# end with

def f():
    pass
# end def

class C:
    pass
# end class

match x:
    case 1:
        pass
# end match
'''


class KindTests(unittest.TestCase):
    def test_all_kinds(self) -> None:
        model = build_model(ALL_KINDS)
        kinds = {block.kind for block in model.blocks}
        self.assertEqual(kinds, {"if", "for", "while", "try", "with", "def", "class", "match"})

    def test_decorated_function_first_line(self) -> None:
        model = build_model("@deco\ndef f():\n    pass\n")
        function = next(b for b in model.blocks if b.kind == "def")
        self.assertEqual(function.lineno, 2)
        self.assertEqual(function.first_line, 1)

    def test_async_normalised(self) -> None:
        model = build_model(
            "async def f():\n"
            "    async for i in xs:\n"
            "        pass\n"
            "    # end for\n"
            "# end def\n"
        )
        self.assertEqual([b.kind for b in model.blocks], ["def", "for"])

    def test_contains_block(self) -> None:
        model = build_model("if a:\n    for i in xs:\n        pass\n")
        outer, inner = model.blocks
        self.assertTrue(contains_block(outer, inner))
        self.assertFalse(contains_block(inner, outer))


class AnchorTests(unittest.TestCase):
    def test_anchor_regex(self) -> None:
        self.assertTrue(ANCHOR_RE.match("# end if"))
        self.assertTrue(ANCHOR_RE.match("# end if  # note"))
        self.assertTrue(ANCHOR_RE.match("#end for"))
        self.assertFalse(ANCHOR_RE.match("# end of file"))
        self.assertFalse(ANCHOR_RE.match("# end iffy"))
        self.assertFalse(ANCHOR_RE.match("# end if you like"))

    def test_anchor_inside_string_is_ignored(self) -> None:
        src = 's = """\n# end if\n"""\n'
        self.assertEqual(find_anchors(src), [])

    def test_anchor_with_note_is_found(self) -> None:
        anchors = find_anchors("# end if  # optional note\n")
        self.assertEqual(len(anchors), 1)
        self.assertEqual(anchors[0].kind, "if")


class TokenTests(unittest.TestCase):
    def test_logical_starts_skip_continuations(self) -> None:
        src = "x = (1 +\n     2)\ny = 3\n"
        starts = logical_starts(src)
        self.assertIn((1, 0), starts)
        self.assertIn((3, 0), starts)
        self.assertNotIn((2, 5), starts)

    def test_string_interior_lines(self) -> None:
        src = 'x = """a\nb\nc"""\n'
        self.assertEqual(string_interior_lines(src), {2, 3})

    def test_detect_newline(self) -> None:
        self.assertEqual(detect_newline("a\r\nb\r\n"), "\r\n")
        self.assertEqual(detect_newline("a\nb\n"), "\n")
        self.assertEqual(detect_newline("a\r\nb\nc\n"), "\r\n")


class BomTests(unittest.TestCase):
    def test_build_model_strips_bom(self) -> None:
        model = build_model("\ufeffif a:\n    pass\n# end if\n")
        self.assertEqual(len(model.blocks), 1)
        self.assertEqual(len(model.anchors), 1)


class BlockTests(unittest.TestCase):
    def test_key_and_one_line(self) -> None:
        model = build_model("if a: pass\n")
        block = model.blocks[0]
        self.assertTrue(block.is_one_line)
        self.assertEqual(block.key, ("if", 1, 0, 1))


if __name__ == "__main__":
    unittest.main()
