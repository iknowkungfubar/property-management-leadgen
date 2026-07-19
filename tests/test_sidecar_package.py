"""Verify the src/sidecar package scaffold produced by arch-extract.

The previously-monolithic src/main.py (522 lines) was split into a
src/sidecar/ package. This test proves the scaffold exists and that every
symbol previously importable from ``src.main`` is still re-exported, so the
``project.scripts`` entry point (``src.main:main``) and the existing
``tests/test_main.py`` patches (``patch("src.main.X")``) keep working.
"""

from __future__ import annotations

import importlib

import pytest

# Symbols that must remain importable from the public src.main surface after
# the extraction, so existing tests and the console-script entry point hold.
REQUIRED_MAIN_SYMBOLS = (
    "main",
    "_db_conn",
    "_start_time",
    "POLL_INTERVAL",
    "ERR_AUTH",
    "ERR_RATELIMIT",
    "ERR_NOT_FOUND",
    "ERR_INTERNAL",
    "ERR_VALIDATION",
    "ERR_UNKNOWN_METHOD",
    "_error_response",
    "_success_response",
    "_handle_command",
    "_get_dnc_config",
    "_poll_parent",
    "_start_parent_watchdog",
    "_handle_signal",
    "_register_signal_handlers",
)

# Submodules the package scaffold must contain.
REQUIRED_SIDECAR_MODULES = (
    "src.sidecar.watchdog",
    "src.sidecar.responses",
    "src.sidecar.dispatch",
    "src.sidecar.signals",
    "src.sidecar",
)


@pytest.mark.parametrize("module_name", REQUIRED_SIDECAR_MODULES)
def test_sidecar_package_modules_importable(module_name: str) -> None:
    """Each package submodule imports cleanly."""
    importlib.import_module(module_name)


def test_src_main_re_exports_all_symbols() -> None:
    """src.main still exposes every symbol the rest of the codebase patches."""
    import src.main as main_mod

    missing = [name for name in REQUIRED_MAIN_SYMBOLS if not hasattr(main_mod, name)]
    assert not missing, f"src.main missing re-exported symbols: {missing}"


def test_main_function_identical_to_sidecar_handler() -> None:
    """src.main._handle_command is the same callable as src.sidecar._handle_command.

    Confirms the extracted package is what src.main dispatches through, not a
    copy.
    """
    import src.main as main_mod
    import src.sidecar as sidecar_mod

    assert main_mod._handle_command is sidecar_mod._handle_command


def test_sidecar_submodules_below_threshold() -> None:
    """No extracted submodule exceeds the 400-line threshold that triggered the split."""
    import inspect

    import src.sidecar as sidecar_mod

    offenders = []
    for name in ("watchdog", "responses", "dispatch", "signals"):
        mod = getattr(sidecar_mod, name)
        source = inspect.getsource(mod)
        line_count = source.count("\n") + 1
        if line_count > 400:
            offenders.append((name, line_count))
    assert not offenders, f"Submodules still over 400 lines: {offenders}"
