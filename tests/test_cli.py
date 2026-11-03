"""End-to-end tests for the command-line interface."""

from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from pyforai.cli import main


def run(args: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


class CLITestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = Path(tempfile.mkdtemp(prefix="pyforai-cli-"))
        self.addCleanup(shutil.rmtree, self.directory, True)

    def write(self, src: str, name: str = "m.py") -> Path:
        path = self.directory / name
        path.write_text(src, encoding="utf-8")
        return path


class CheckTests(CLITestCase):
    def test_ok(self) -> None:
        path = self.write("if a:\n    pass\n# end if\n")
        code, out, _ = run(["check", str(path)])
        self.assertEqual(code, 0)
        self.assertIn("0 error(s)", out)

    def test_bad(self) -> None:
        path = self.write("for x in xs:\n    if x:\n        pass\n# end if\n")
        code, out, _ = run(["check", str(path)])
        self.assertEqual(code, 1)
        self.assertIn("E001", out)

    def test_json(self) -> None:
        path = self.write("x = 1\n# end if\n")
        code, out, _ = run(["check", "--json", str(path)])
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["files"][0]["diagnostics"][0]["code"], "E002")

    def test_json_ok(self) -> None:
        path = self.write("if a:\n    pass\n# end if\n")
        code, out, _ = run(["check", "--json", str(path)])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["files"][0]["anchors"], 1)

    def test_directory_expansion_skips_venv(self) -> None:
        self.write("if a:\n    pass\n# end if\n", "a.py")
        venv = self.directory / ".venv"
        venv.mkdir()
        (venv / "b.py").write_text("x = 1\n# end if\n", encoding="utf-8")
        code, out, _ = run(["check", str(self.directory)])
        self.assertEqual(code, 0)
        self.assertIn("checked 1 file(s)", out)

    def test_strict(self) -> None:
        path = self.write("def f():\n    a = 1\n    b = 2\n    c = 3\n")
        code, out, _ = run(["check", "--strict", "--min-lines", "3", str(path)])
        self.assertEqual(code, 1)
        self.assertIn("E010", out)

    def test_missing_path(self) -> None:
        with self.assertRaises(SystemExit):
            run(["check", str(self.directory / "nope.py")])


class FmtTests(CLITestCase):
    def test_fmt_all(self) -> None:
        path = self.write("def f():\n    if a:\n        pass\n")
        code, out, _ = run(["fmt", "--all", str(path)])
        self.assertEqual(code, 0)
        self.assertIn("# end if", path.read_text())
        self.assertIn("# end def", path.read_text())

    def test_fmt_dry_run_json(self) -> None:
        source = "def f():\n    pass\n"
        path = self.write(source)
        code, out, _ = run(["fmt", "--all", "--dry-run", "--json", str(path)])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        self.assertEqual(path.read_text(), source)


class EditCommandTests(CLITestCase):
    def test_wrap_json(self) -> None:
        path = self.write("def f(xs):\n    for x in xs:\n        use(x)\n")
        code, out, _ = run(
            [
                "wrap",
                str(path),
                "--header",
                "2",
                "--kind",
                "try",
                "--except",
                "Exception",
                "--handler",
                "pass",
                "--json",
            ]
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["changed"])
        self.assertIn("# end try", path.read_text())

    def test_replace_body_json(self) -> None:
        path = self.write("def f():\n    return 1\n")
        code, out, _ = run(
            ["replace-body", str(path), "--header", "1", "--code", "return 2", "--json"]
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["changed"])
        self.assertIn("return 2", path.read_text())

    def test_move_json(self) -> None:
        path = self.write("def a():\n    pass\n\n\ndef b():\n    pass\n")
        code, out, _ = run(
            ["move", str(path), "--header", "5", "--before-line", "1", "--json"]
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertTrue(payload["changed"])

    def test_failure_is_reported_as_json(self) -> None:
        path = self.write("def f(xs):\n    for x in xs:\n        use(x)\n")
        code, out, err = run(
            [
                "wrap",
                str(path),
                "--header",
                "2",
                "--kind",
                "if",
                "--json",
            ]
        )
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertFalse(payload["ok"])
        self.assertIn("condition", payload["error"])
        self.assertEqual(err, "")

    def test_bad_anchor_argument(self) -> None:
        path = self.write("if a:\n    pass\n")
        with self.assertRaises(SystemExit):
            run(
                [
                    "wrap",
                    str(path),
                    "--anchor",
                    "not-a-position",
                    "--kind",
                    "if",
                    "--condition",
                    "a",
                ]
            )


if __name__ == "__main__":
    unittest.main()
