# Corpus notices

`files/` contains vendored source files used only as inputs to the E1 drift
injector. They are not imported, packaged, or redistributed as part of pyforai.

## CPython standard library

`stdlib_*.py` are excerpts/copies of files from CPython 3.12's `Lib/` directory.
They are licensed under the Python Software Foundation License 2.0 (PSF-2.0).
See <https://docs.python.org/3/license.html> for the full license text.

## This repository

`repo_*.py` are copies of files from this repository and are MIT-licensed, the
same as the rest of pyforai.

The manifest (`MANIFEST.json`) records the origin, license, and SHA-256 of every
file. Run `python -m bench.e1.corpus verify` to detect accidental edits.
