"""Command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .capsule import compile_capsule, validate_capsule
from .io import load_json
from .models import Study, ValidationError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="phytoparalog",
        description="Compile plant paralog identifiability evidence without selecting targets.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate a closed-schema study JSON")
    validate.add_argument("input", type=Path)
    compile_command = subparsers.add_parser("compile", help="compile a deterministic capsule")
    compile_command.add_argument("input", type=Path)
    compile_command.add_argument("output", type=Path)
    validate_capsule_command = subparsers.add_parser(
        "validate-capsule", help="verify a compiled capsule"
    )
    validate_capsule_command.add_argument("capsule", type=Path)
    anchor = validate_capsule_command.add_mutually_exclusive_group()
    anchor.add_argument("--study", type=Path, help="recompute from the original study")
    anchor.add_argument("--expected-digest", help="externally anchored capsule digest")
    subparsers.add_parser("version", help="print the installed version")
    return parser


def _print(value: object) -> None:
    print(json.dumps(value, allow_nan=False, sort_keys=True))


def _invalid(command: str, *, io_error: bool) -> dict[str, str]:
    if command == "validate":
        code = "STUDY_IO_ERROR" if io_error else "STUDY_INVALID"
        message = "Study input could not be read." if io_error else "Study input is invalid."
    elif command == "compile":
        code = "CAPSULE_COMPILE_IO_ERROR" if io_error else "CAPSULE_COMPILE_INVALID"
        message = (
            "Study input or capsule destination could not be accessed."
            if io_error
            else "Capsule compilation failed."
        )
    else:
        code = "CAPSULE_IO_ERROR" if io_error else "CAPSULE_INVALID"
        message = "Capsule input could not be read." if io_error else "Capsule validation failed."
    return {"error": message, "error_code": code, "status": "INVALID"}


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "version":
            print(__version__)
            return 0
        if args.command == "validate":
            study = Study.from_dict(load_json(args.input))
            _print(
                {
                    "schema_version": study.schema_version,
                    "status": "VALID",
                    "study_id": study.study_id,
                    "target_selection": {"allowed": False, "status": "PROHIBITED"},
                }
            )
            return 0
        if args.command == "compile":
            _print(compile_capsule(Study.from_dict(load_json(args.input)), args.output))
            return 0
        if args.command == "validate-capsule":
            study = Study.from_dict(load_json(args.study)) if args.study is not None else None
            _print(
                validate_capsule(
                    args.capsule,
                    study=study,
                    expected_capsule_digest=args.expected_digest,
                )
            )
            return 0
    except ValidationError:
        _print(_invalid(args.command, io_error=False))
        return 2
    except OSError:
        _print(_invalid(args.command, io_error=True))
        return 2
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
