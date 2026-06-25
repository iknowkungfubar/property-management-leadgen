# Dead End Ledger

## 2026-06-24 — PyInstaller `--onefile` with mypyc
- **Attempted:** `pyinstaller --onefile` to create a single sidecar binary
- **Why it failed:** Compression error on `mypyc.cpython-311-x86_64-linux-gnu.so` — `decompression resulted in return code -1!`. The file is pulled in by pydantic (through uv/hermes venv) and cannot be excluded even with `--exclude-module mypy`.
- **Evidence:** `[PYI-1130580:ERROR] Failed to extract 81d243bd2c585b0f4821__mypyc.cpython-311-x86_64-linux-gnu.so`
- **Lesson:** Use `--onedir` mode instead of `--onefile`. The `--onedir` output can be bundled by Tauri's `externalBin` which can point to a directory containing the binary. For truly single-file distribution, investigate UPX or Nuitka as an alternative.

## 2026-06-24 — `datas=[]` approach for src module inclusion
- **Attempted:** Adding `src/` as a data directory via `datas=[(path, 'src')]` in the spec
- **Why it failed:** PyInstaller's import mechanism (`pyimod02_importers.py`) doesn't know about data-directory modules. Python files added as data are not registered with the module importer.
- **Lesson:** Use `--collect-all src` or explicitly list all modules in `hiddenimports`. The `--collect-all` flag properly registers modules with PyInstaller's import graph.
