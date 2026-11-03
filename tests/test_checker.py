"""Tests for L1 anchor validation."""

from __future__ import annotations

import unittest

from pyforai.checker import check_source


def codes(src: str, **kwargs) -> list[str]:
    return [d.code for d in check_source(src, **kwargs).diagnostics]


class ValidAnchors(unittest.TestCase):
    def test_nested(self) -> None:
        src = (
            "def f(xs):\n"
            "    for x in xs:\n"
            "        if x:\n"
            "            use(x)\n"
            "        # end if\n"
            "    # end for\n"
        )
        result = check_source(src)
        self.assertTrue(result.ok, [d.message for d in result.diagnostics])
        self.assertEqual(len(result.matches), 2)

    def test_sparse_outer_only(self) -> None:
        src = (
            "if a:\n"
            "    for i in xs:\n"
            "        pass\n"
            "# end if\n"
        )
        self.assertTrue(check_source(src).ok)

    def test_comment_between_block_and_anchor(self) -> None:
        src = "if a:\n    pass\n    # trailing note\n# end if\n"
        self.assertTrue(check_source(src).ok)

    def test_blank_lines_between(self) -> None:
        src = "if a:\n    pass\n\n# end if\n"
        self.assertTrue(check_source(src).ok)

    def test_anchor_with_note(self) -> None:
        src = "if a:\n    pass\n# end if  # note\n"
        self.assertTrue(check_source(src).ok)

    def test_nested_same_end_line(self) -> None:
        src = (
            "if a:\n"
            "    for i in xs:\n"
            "        pass\n"
            "    # end for\n"
            "# end if\n"
        )
        result = check_source(src)
        self.assertTrue(result.ok, [d.message for d in result.diagnostics])
        self.assertEqual(len(result.matches), 2)

    def test_try_with_finally(self) -> None:
        src = (
            "try:\n"
            "    f()\n"
            "except Exception:\n"
            "    pass\n"
            "finally:\n"
            "    g()\n"
            "# end try\n"
        )
        self.assertTrue(check_source(src).ok)

    def test_match_and_async(self) -> None:
        src = (
            "async def f(xs):\n"
            "    async for x in xs:\n"
            "        match x:\n"
            "            case 1:\n"
            "                pass\n"
            "        # end match\n"
            "    # end for\n"
            "# end def\n"
        )
        result = check_source(src)
        self.assertTrue(result.ok, [d.message for d in result.diagnostics])
        self.assertEqual(len(result.matches), 3)

    def test_anchor_in_comment_after_code_is_not_anchor(self) -> None:
        src = "if a:\n    pass\n# end if\n"
        self.assertTrue(check_source(src).ok)


class InvalidAnchors(unittest.TestCase):
    def test_kind_mismatch(self) -> None:
        src = (
            "for x in xs:\n"
            "    if x:\n"
            "        pass\n"
            "# end if\n"
        )
        self.assertIn("E001", codes(src))

    def test_no_block_at_col(self) -> None:
        src = "if a:\n    pass\n    # end if\n"
        self.assertIn("E002", codes(src))

    def test_inside_else(self) -> None:
        src = (
            "if a:\n"
            "    f()\n"
            "# end if\n"
            "else:\n"
            "    g()\n"
        )
        self.assertIn("E003", codes(src))

    def test_not_adjacent(self) -> None:
        src = (
            "if a:\n"
            "    f()\n"
            "g()\n"
            "# end if\n"
        )
        self.assertIn("E004", codes(src))

    def test_duplicate(self) -> None:
        src = "if a:\n    pass\n# end if\n# end if\n"
        self.assertIn("E005", codes(src))

    def test_trailing_anchor(self) -> None:
        src = "if a:\n    pass  # end if\n"
        self.assertIn("E007", codes(src))

    def test_bad_nesting(self) -> None:
        src = (
            "if a:\n"
            "    for i in xs:\n"
            "        pass\n"
            "# end if\n"
            "    # end for\n"
        )
        self.assertIn("E008", codes(src))

    def test_syntax_error(self) -> None:
        self.assertIn("E100", codes("def f(:\n    pass\n"))

    def test_stale_anchor(self) -> None:
        src = "x = 1\n# end if\n"
        self.assertIn("E002", codes(src))


class StrictMode(unittest.TestCase):
    def test_missing_anchor(self) -> None:
        src = (
            "def f():\n"
            "    a = 1\n"
            "    b = 2\n"
            "    c = 3\n"
            "    return a + b + c\n"
        )
        self.assertIn("E010", codes(src, strict=True, min_lines=3, min_depth=10))
        self.assertNotIn("E010", codes(src, strict=True, min_lines=99, min_depth=99))

    def test_deep_block(self) -> None:
        src = (
            "if a:\n"
            "    if b:\n"
            "        if c:\n"
            "            if d:\n"
            "                pass\n"
        )
        self.assertIn("E010", codes(src, strict=True, min_lines=99, min_depth=3))


class ResultShape(unittest.TestCase):
    def test_model_present(self) -> None:
        result = check_source("if a:\n    pass\n# end if\n")
        self.assertIsNotNone(result.model)
        self.assertEqual(result.model.filename, "<string>")

    def test_diagnostic_dict(self) -> None:
        result = check_source("x = 1\n# end if\n")
        payload = result.diagnostics[0].as_dict()
        self.assertEqual(payload["code"], "E002")
        self.assertIn("line", payload)
        self.assertIn("hint", payload)


if __name__ == "__main__":
    unittest.main()
