"""Tests for L2 structural editing."""

from __future__ import annotations

import ast
import shutil
import tempfile
import tokenize
import unittest
from pathlib import Path

from pyforai import EditError, check_source
from pyforai.editor import fmt, move, replace_body, wrap


class EditorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="pyforai-test-"))
        self.addCleanup(shutil.rmtree, self.directory, True)

    def write(self, src: str, name: str = "m.py") -> Path:
        path = self.directory / name
        path.write_text(src, encoding="utf-8")
        return path

    def assert_parses(self, path: Path) -> None:
        # tokenize.open honours PEP 263 cookies and strips a UTF-8 BOM, which
        # plain Path.read_text() would leave as U+FEFF.
        with tokenize.open(path) as handle:
            text = handle.read()
        ast.parse(text)
        result = check_source(text, str(path))
        self.assertTrue(result.ok, [d.message for d in result.diagnostics])


class FmtTests(EditorTestCase):
    def test_inserts_nested_anchors_inner_first(self) -> None:
        path = self.write("def f():\n    if a:\n        for i in xs:\n            g(i)\n")
        result = fmt(path, all_blocks=True)
        self.assertTrue(result.changed)
        self.assertEqual(
            path.read_text(),
            "def f():\n"
            "    if a:\n"
            "        for i in xs:\n"
            "            g(i)\n"
            "        # end for\n"
            "    # end if\n"
            "# end def\n",
        )
        self.assert_parses(path)

    def test_idempotent(self) -> None:
        path = self.write("def f():\n    if a:\n        pass\n")
        fmt(path, all_blocks=True)
        second = fmt(path, all_blocks=True)
        self.assertFalse(second.changed)

    def test_skips_existing_anchors(self) -> None:
        path = self.write("def f():\n    if a:\n        pass\n    # end if\n")
        fmt(path, all_blocks=True)
        text = path.read_text()
        self.assertEqual(text.count("# end if"), 1)
        self.assertIn("# end def", text)

    def test_dry_run_does_not_write(self) -> None:
        source = "def f():\n    if a:\n        pass\n"
        path = self.write(source)
        result = fmt(path, all_blocks=True, dry_run=True)
        self.assertTrue(result.changed)
        self.assertIn("# end if", result.diff)
        self.assertEqual(path.read_text(), source)

    def test_refuses_invalid_existing_anchor(self) -> None:
        path = self.write("if a:\n    pass\n    # end if\n")
        with self.assertRaises(EditError):
            fmt(path, all_blocks=True)

    def test_preserves_missing_final_newline(self) -> None:
        path = self.write("if a:\n    pass")
        fmt(path, all_blocks=True)
        self.assertFalse(path.read_text().endswith("\n"))
        self.assertTrue(path.read_text().endswith("# end if"))

    def test_match(self) -> None:
        path = self.write(
            "def f(x):\n"
            "    match x:\n"
            "        case 1:\n"
            "            pass\n"
        )
        fmt(path, all_blocks=True)
        text = path.read_text()
        self.assertIn("    # end match\n", text)
        self.assertIn("# end def\n", text)
        self.assert_parses(path)

    def test_preserves_bom(self) -> None:
        path = self.directory / "bom.py"
        path.write_bytes(b"\xef\xbb\xbf" + b"if a:\n    pass\n")
        fmt(path, all_blocks=True)
        self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assert_parses(path)


class WrapTests(EditorTestCase):
    def test_wrap_try(self) -> None:
        path = self.write("def f(xs):\n    for x in xs:\n        use(x)\n")
        wrap(path, header=2, kind="try", except_clause="Exception as e", handler="raise")
        self.assertEqual(
            path.read_text(),
            "def f(xs):\n"
            "    try:\n"
            "        for x in xs:\n"
            "            use(x)\n"
            "    except Exception as e:\n"
            "        raise\n"
            "    # end try\n",
        )
        self.assert_parses(path)

    def test_wrap_if(self) -> None:
        path = self.write("def f(xs):\n    for x in xs:\n        use(x)\n")
        wrap(path, header=2, kind="if", condition="xs")
        self.assertIn("    if xs:\n", path.read_text())
        self.assertIn("    # end if\n", path.read_text())
        self.assert_parses(path)

    def test_wrap_with(self) -> None:
        path = self.write("def f():\n    do()\n")
        wrap(path, header=1, kind="with", context="lock")
        self.assertIn("with lock:\n", path.read_text())
        self.assert_parses(path)

    def test_wrap_for(self) -> None:
        path = self.write("def f():\n    do()\n")
        wrap(path, header=1, kind="for", loop_target="x", iterable="xs")
        self.assertIn("for x in xs:\n", path.read_text())
        self.assert_parses(path)

    def test_wrap_while(self) -> None:
        path = self.write("def f():\n    do()\n")
        wrap(path, header=1, kind="while", condition="ready")
        self.assertIn("while ready:\n", path.read_text())
        self.assert_parses(path)

    def test_wrap_decorated_definition(self) -> None:
        path = self.write("@deco\ndef f():\n    pass\n")
        wrap(path, header=2, kind="if", condition="flag")
        self.assertEqual(
            path.read_text(),
            "if flag:\n"
            "    @deco\n"
            "    def f():\n"
            "        pass\n"
            "# end if\n",
        )
        self.assert_parses(path)

    def test_wrap_preserves_multiline_string(self) -> None:
        source = (
            "def f(x):\n"
            "    if x:\n"
            '        s = """\n'
            "line one\n"
            "line two\n"
            '"""\n'
            "        use(s)\n"
            "    # end if\n"
        )
        path = self.write(source)
        wrap(path, header=2, kind="try", except_clause="Exception", handler="pass")
        text = path.read_text()
        self.assertIn('s = """\nline one\nline two\n"""', text)
        self.assert_parses(path)

    def test_wrap_preserves_crlf(self) -> None:
        source = "def f(xs):\r\n    for x in xs:\r\n        use(x)\r\n"
        path = self.directory / "crlf.py"
        path.write_bytes(source.encode("utf-8"))
        wrap(path, header=2, kind="if", condition="xs")
        raw = path.read_bytes()
        self.assertIn(b"\r\n", raw)
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assert_parses(path)

    def test_wrap_missing_parameter_is_rejected(self) -> None:
        path = self.write("if a:\n    pass\n")
        with self.assertRaises(EditError):
            wrap(path, header=1, kind="if", condition="")


class ReplaceBodyTests(EditorTestCase):
    def test_replace_body(self) -> None:
        path = self.write("def f():\n    a = 1\n    return a\n")
        replace_body(path, header=1, code="return 42")
        self.assertEqual(path.read_text(), "def f():\n    return 42\n")

    def test_keeps_docstring(self) -> None:
        path = self.write('def f():\n    """Doc."""\n    return 1\n')
        replace_body(path, header=1, code="return 2", keep_docstring=True)
        self.assertEqual(
            path.read_text(), 'def f():\n    """Doc."""\n    return 2\n'
        )

    def test_removes_docstring(self) -> None:
        path = self.write('def f():\n    """Doc."""\n    return 1\n')
        result = replace_body(path, header=1, code="return 2", keep_docstring=False)
        self.assertNotIn("Doc.", path.read_text())
        self.assertIn("docstring removed", result.detail)

    def test_dedents_input(self) -> None:
        path = self.write("def f():\n    pass\n")
        replace_body(path, header=1, code="    a = 1\n    if a:\n        return 1\n    return 0")
        self.assertIn("    a = 1\n    if a:\n        return 1\n    return 0\n", path.read_text())
        self.assert_parses(path)

    def test_empty_code_becomes_pass(self) -> None:
        path = self.write("def f():\n    a = 1\n")
        replace_body(path, header=1, code="")
        self.assertEqual(path.read_text(), "def f():\n    pass\n")

    def test_one_line_block_rejected(self) -> None:
        path = self.write("if a: pass\n")
        with self.assertRaises(EditError):
            replace_body(path, header=1, code="pass")

    def test_invalid_code_aborts_without_writing(self) -> None:
        source = "def f():\n    return 1\n"
        path = self.write(source)
        with self.assertRaises(EditError):
            replace_body(path, header=1, code="def broken(:")
        self.assertEqual(path.read_text(), source)

    def test_preserves_else_clause(self) -> None:
        path = self.write(
            "def f(x):\n"
            "    if x:\n"
            "        return 1\n"
            "    else:\n"
            "        return 2\n"
        )
        replace_body(path, header=2, code="return 3")
        self.assertEqual(
            path.read_text(),
            "def f(x):\n"
            "    if x:\n"
            "        return 3\n"
            "    else:\n"
            "        return 2\n",
        )
        self.assert_parses(path)

    def test_preserves_except_clause(self) -> None:
        path = self.write(
            "def f():\n"
            "    try:\n"
            "        work()\n"
            "    except Exception:\n"
            "        handle()\n"
        )
        replace_body(path, header=2, code="work2()")
        self.assertEqual(
            path.read_text(),
            "def f():\n"
            "    try:\n"
            "        work2()\n"
            "    except Exception:\n"
            "        handle()\n",
        )
        self.assert_parses(path)

    def test_keeps_anchor_after_body_in_for(self) -> None:
        path = self.write(
            "def f(xs):\n"
            "    for x in xs:\n"
            "        use(x)\n"
            "    # end for\n"
        )
        replace_body(path, header=2, code="pass")
        self.assertEqual(
            path.read_text(),
            "def f(xs):\n"
            "    for x in xs:\n"
            "        pass\n"
            "    # end for\n",
        )
        self.assert_parses(path)


class MoveTests(EditorTestCase):
    def test_move_before(self) -> None:
        path = self.write("def a():\n    pass\n\n\ndef b():\n    pass\n")
        move(path, header=5, before_line=1)
        text = path.read_text()
        self.assertLess(text.index("def b"), text.index("def a"))
        self.assert_parses(path)

    def test_move_after(self) -> None:
        path = self.write("def a():\n    pass\n\n\ndef b():\n    pass\n")
        # Target the *block* starting at line 5 so the destination indent is
        # `def b`'s own indent, not its body indent.
        move(path, header=1, after_line=5)
        text = path.read_text()
        self.assertLess(text.index("def b"), text.index("def a"))
        self.assert_parses(path)

    def test_move_into_reindents(self) -> None:
        path = self.write(
            "def outer():\n"
            "    x = 1\n"
            "\n"
            "\n"
            "def inner():\n"
            "    y = 2\n"
        )
        move(path, header=5, into_line=1)
        text = path.read_text()
        self.assertIn("    def inner():\n        y = 2\n", text)
        self.assert_parses(path)

    def test_move_anchor_reindents(self) -> None:
        path = self.write(
            "def outer():\n"
            "    x = 1\n"
            "\n"
            "\n"
            "def inner():\n"
            "    for i in xs:\n"
            "        use(i)\n"
            "    # end for\n"
        )
        move(path, header=5, into_line=1)
        self.assertIn("        # end for\n", path.read_text())
        self.assert_parses(path)

    def test_move_into_self_rejected(self) -> None:
        path = self.write("def outer():\n    if a:\n        pass\n")
        with self.assertRaises(EditError):
            move(path, header=2, into_line=1)

    def test_move_empties_parent_rejected(self) -> None:
        source = "def outer():\n    if a:\n        pass\n"
        path = self.write(source)
        with self.assertRaises(EditError):
            move(path, header=2, before_line=1)
        self.assertEqual(path.read_text(), source)

    def test_move_decorated_before(self) -> None:
        path = self.write("def a():\n    pass\n\n\n@deco\ndef b():\n    pass\n")
        move(path, header=6, before_line=1)
        text = path.read_text()
        self.assertTrue(text.startswith("@deco\ndef b()"))
        self.assert_parses(path)

    def test_move_by_anchor(self) -> None:
        path = self.write(
            "def outer():\n"
            "    x = 1\n"
            "\n"
            "\n"
            "def inner():\n"
            "    y = 0\n"
            "    for i in xs:\n"
            "        use(i)\n"
            "    # end for\n"
        )
        # The `# end for` anchor is at line 9, column 4.  Moving the `for`
        # leaves `y = 0` behind, so `inner` still has a body.
        move(path, anchor=(9, 4), into_line=1)
        self.assertIn("    for i in xs:\n", path.read_text())
        self.assertIn("    y = 0\n", path.read_text())
        self.assert_parses(path)


if __name__ == "__main__":
    unittest.main()
