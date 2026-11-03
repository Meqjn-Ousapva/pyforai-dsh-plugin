"""The E1 drift corpus.

Twenty real Python files: twelve from the CPython standard library and eight
from this repository.  They are vendored under ``corpus/files`` so a result can
be reproduced without depending on the host interpreter or a package install.

Run ``python -m bench.e1.corpus build`` after adding a file.  Run
``python -m bench.e1.corpus verify`` to check hashes.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .common import E1, build_model, sha256_file, write_json

CORPUS = E1 / "corpus"
FILES = CORPUS / "files"
MANIFEST = CORPUS / "MANIFEST.json"

# id -> (origin, license, note)
ORIGINS: dict[str, tuple[str, str, str]] = {
    "stdlib_argparse_py": ("CPython 3.12 Lib/argparse.py", "PSF-2.0", "large, branch-heavy"),
    "stdlib_configparser_py": ("CPython 3.12 Lib/configparser.py", "PSF-2.0", "classes + long methods"),
    "stdlib_dataclasses_py": ("CPython 3.12 Lib/dataclasses.py", "PSF-2.0", "decorators + nested funcs"),
    "stdlib_textwrap_py": ("CPython 3.12 Lib/textwrap.py", "PSF-2.0", "small, loops"),
    "stdlib_csv_py": ("CPython 3.12 Lib/csv.py", "PSF-2.0", "small, classes"),
    "stdlib_pathlib_py": ("CPython 3.12 Lib/pathlib.py", "PSF-2.0", "large, nested methods"),
    "stdlib_json_encoder_py": ("CPython 3.12 Lib/json/encoder.py", "PSF-2.0", "small, if/else chains"),
    "stdlib_unittest_case_py": ("CPython 3.12 Lib/unittest/case.py", "PSF-2.0", "large, deep nesting"),
    "stdlib_contextlib_py": ("CPython 3.12 Lib/contextlib.py", "PSF-2.0", "try/finally heavy"),
    "stdlib_functools_py": ("CPython 3.12 Lib/functools.py", "PSF-2.0", "decorators + closures"),
    "stdlib_shutil_py": ("CPython 3.12 Lib/shutil.py", "PSF-2.0", "many small blocks"),
    "stdlib_tempfile_py": ("CPython 3.12 Lib/tempfile.py", "PSF-2.0", "classes + context managers"),
    "repo_pyforai_checker_py": ("pyforai/checker.py", "MIT", "the checker itself"),
    "repo_pyforai_editor_py": ("pyforai/editor.py", "MIT", "the editor itself"),
    "repo_pyforai_anchors_py": ("pyforai/anchors.py", "MIT", "block model"),
    "repo_pyforai_cli_py": ("pyforai/cli.py", "MIT", "CLI"),
    "repo_bench_harness_py": ("former bench/harness.py (removed in E1 cleanup)", "MIT", "old E2E harness"),
    "repo_bench_calibrate_generate_t_py": ("former bench/calibrate/generate_t.py (removed in E1 cleanup)", "MIT", "task generator"),
    "repo_bench_calibrate_generate_py": ("former bench/calibrate/generate.py (removed in E1 cleanup)", "MIT", "task generator"),
    "repo_tests_test_checker_py": ("tests/test_checker.py", "MIT", "checker tests"),
}


@dataclass(frozen=True)
class CorpusFile:
    id: str
    path: Path
    origin: str
    license: str
    sha256: str
    lines: int
    blocks: int

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")


def build_manifest() -> dict:
    files = []
    for file_id in sorted(ORIGINS):
        path = FILES / f"{file_id}.py"
        if not path.exists():
            raise SystemExit(f"missing corpus file: {path}")
        text = path.read_text(encoding="utf-8")
        model = build_model(text)
        origin, license_name, _note = ORIGINS[file_id]
        files.append(
            {
                "id": file_id,
                "path": str(path.relative_to(E1)),
                "origin": origin,
                "license": license_name,
                "sha256": sha256_file(path),
                "lines": text.count("\n") + (0 if text.endswith("\n") else 1),
                "blocks": len(model.blocks),
            }
        )
    return {
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "python": sys.version.split()[0],
        "files": files,
    }


def load_corpus() -> list[CorpusFile]:
    import json

    if not MANIFEST.exists():
        write_json(MANIFEST, build_manifest())
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    result = []
    for entry in data["files"]:
        path = E1 / entry["path"]
        if not path.exists():
            raise SystemExit(f"missing corpus file: {path}")
        result.append(
            CorpusFile(
                id=entry["id"],
                path=path,
                origin=entry["origin"],
                license=entry["license"],
                sha256=entry["sha256"],
                lines=entry["lines"],
                blocks=entry["blocks"],
            )
        )
    return result


def verify_corpus() -> int:
    bad = 0
    for entry in load_corpus():
        actual = sha256_file(entry.path)
        if actual != entry.sha256:
            print(f"CHANGED {entry.id}: {entry.sha256} -> {actual}")
            bad += 1
    print(f"{'FAIL' if bad else 'OK'}: {len(load_corpus())} files, {bad} changed")
    return 1 if bad else 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "verify"
    if command == "build":
        write_json(MANIFEST, build_manifest())
        print(f"wrote {MANIFEST}")
        return 0
    if command == "verify":
        return verify_corpus()
    raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
