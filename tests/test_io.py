from __future__ import annotations

import os
from pathlib import Path

import pytest

import phytoparalog.io as io_module
from phytoparalog.io import MAX_JSON_INTEGER_DIGITS, load_json
from phytoparalog.models import ValidationError


def test_oversized_integer_is_validation_error(tmp_path: Path) -> None:
    source = tmp_path / "oversized-integer.json"
    source.write_text(
        '{"probe":' + ("9" * 5_000) + "}\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValidationError,
        match=rf"integer exceeds {MAX_JSON_INTEGER_DIGITS} digit limit",
    ):
        load_json(source)


def test_extreme_json_nesting_is_validation_error(tmp_path: Path) -> None:
    source = tmp_path / "nested.json"
    source.write_text(("[" * 100_000) + ("]" * 100_000), encoding="utf-8")

    with pytest.raises(ValidationError, match="JSON nesting exceeds parser limit"):
        load_json(source)


def test_lone_surrogate_is_validation_error(tmp_path: Path) -> None:
    source = tmp_path / "surrogate.json"
    source.write_text('{"probe":"\\ud800"}\n', encoding="utf-8")

    with pytest.raises(ValidationError, match="non-Unicode-scalar"):
        load_json(source)


def test_symbolic_link_input_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text('{"outside":true}\n', encoding="utf-8")
    source = tmp_path / "input.json"
    try:
        source.symlink_to(outside)
    except OSError as exc:  # pragma: no cover - platform policy may deny symlinks.
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(ValidationError, match="symbolic-link"):
        load_json(source)


def test_symlink_swap_is_rejected_before_external_bytes_are_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "input.json"
    source.write_text('{"owned":true}\n', encoding="utf-8")
    outside = tmp_path / "outside.json"
    outside.write_text('{"outside":true}\n', encoding="utf-8")
    original_open = os.open
    swapped = False

    def swap_then_open(path: str | bytes | os.PathLike[str], flags: int, mode: int = 0o777) -> int:
        nonlocal swapped
        if Path(path) == source and not swapped:
            swapped = True
            source.unlink()
            source.symlink_to(outside)
        return original_open(path, flags, mode)

    monkeypatch.setattr(io_module.os, "open", swap_then_open)
    with pytest.raises(ValidationError, match=r"cannot be opened safely|identity changed"):
        load_json(source)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_fifo_input_is_rejected_before_open(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    os.mkfifo(source)

    with pytest.raises(ValidationError, match="single-link regular file"):
        load_json(source)


def test_hardlinked_input_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "input.json"
    source.write_text("{}\n", encoding="utf-8")
    alias = tmp_path / "alias.json"
    alias.hardlink_to(source)

    with pytest.raises(ValidationError, match="single-link regular file"):
        load_json(source)
