#!/usr/bin/env python3
"""Fail a public release on likely private data, secrets, or biological payloads.

This is a conservative release-hygiene scanner, not a complete data-loss
prevention system. It never follows symbolic links and treats non-text content
as a finding rather than silently exempting it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

EXCLUDED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
}
EXCLUDED_FILES = {".coverage", ".DS_Store"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}
RISKY_BIOLOGICAL_SUFFIXES = {
    ".bam",
    ".bcf",
    ".cram",
    ".fa",
    ".fasta",
    ".fastq",
    ".fq",
    ".gb",
    ".gbk",
    ".pdb",
    ".sam",
    ".vcf",
}
MAX_TEXT_BYTES = 5_000_000
ALLOWED_CONTROLS = {9, 10, 13}


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    path: str
    line: int
    excerpt: str


def _patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    backslash = re.escape(chr(92))
    user_dir = "Us" + "ers"
    posix_private = (
        r"(?<![A-Za-z0-9])/(?:"
        + user_dir
        + r"|home|root|workspace|tmp|private|var|Volumes|mnt)"
        + r"(?:/[^\s\"'<>]+)?(?=$|[\s\"'<>])"
    )
    # One or more backslashes allow direct Windows paths and their JSON-escaped form.
    windows_private = r"\b[A-Za-z]:(?:/|" + backslash + r"+)[^\s\"'<>]+"
    unc_private = (
        r"(?:" + backslash + r"+){2}[^" + backslash + r"\s\"'<>]+(?:" + backslash + r"+)[^\s\"'<>]+"
    )
    file_uri = "fi" + r"le://[^\s\"'<>]+"
    archive_id = (
        r"\b(?:S" + r"RR|ERR|DRR)\d{5,}\b|\bPRJ(?:NA|EB|DB)\d{4,}\b|"
        r"\bSAM(?:N|E|D)\d{5,}\b|\b(?:GCF|GCA)_\d{6,}(?:\.\d+)?\b"
    )
    github_token = r"\b(?:gh" + r"[psoru]_|github_pat_)[A-Za-z0-9_]{16,}\b"
    openai_token = r"\bsk" + r"-[A-Za-z0-9_-]{16,}\b"
    slack_token = r"\bxox" + r"[baprs]-[A-Za-z0-9-]{16,}\b"
    aws_access_key = r"\b(?:AK" + r"IA|ASIA)[0-9A-Z]{16}\b"
    private_key = r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE" + r" KEY-----"
    assigned_secret = (
        r"[\"']?\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|"
        r"client[_-]?secret|private[_-]?key|session[_-]?token)\b[\"']?\s*[:=]\s*"
        r"[\"']?[^\s,;}{\"']{4,}"
    )
    aws_assignment = (
        r"\bAWS_(?:ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)\s*[:=]\s*"
        r"[\"']?[A-Za-z0-9/+=_-]{4,}"
    )
    bearer = r"\bBearer[ \t]+[A-Za-z0-9._~+/=-]{12,}"
    jwt = r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{8,}\b"
    return (
        ("absolute-private-path", re.compile(posix_private)),
        ("windows-private-path", re.compile(windows_private, re.IGNORECASE)),
        ("unc-private-path", re.compile(unc_private, re.IGNORECASE)),
        ("file-uri", re.compile(file_uri, re.IGNORECASE)),
        ("archive-accession", re.compile(archive_id)),
        ("github-token", re.compile(github_token)),
        ("openai-token", re.compile(openai_token)),
        ("slack-token", re.compile(slack_token)),
        ("aws-access-key", re.compile(aws_access_key)),
        ("private-key", re.compile(private_key)),
        ("assigned-secret", re.compile(assigned_secret, re.IGNORECASE)),
        ("aws-secret-assignment", re.compile(aws_assignment, re.IGNORECASE)),
        ("bearer-token", re.compile(bearer, re.IGNORECASE)),
        ("jwt-token", re.compile(jwt)),
    )


URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
SECRET_QUERY_NAMES = {
    "access_key",
    "access_key_id",
    "access_token",
    "api_key",
    "apikey",
    "auth_token",
    "client_secret",
    "code",
    "credential",
    "credentials",
    "jwt",
    "key",
    "oauth_code",
    "oauth_token",
    "password",
    "passwd",
    "private_key",
    "session",
    "session_id",
    "session_token",
    "sig",
    "signature",
    "token",
}
KNOWN_SHA256_VALUE = re.compile(
    r"(?P<prefix>(?i:(?:[A-Za-z0-9_-]*sha(?:-?256)?))[\"']?\s*[:=]\s*[\"'`]?)"
    r"(?P<digest>[0-9a-f]{64})(?=$|[\"'`\s,}\]])"
)


def _safe_excerpt(line: str, start: int, end: int) -> str:
    """Report context without echoing a complete suspected secret or path."""

    del line, start, end
    return "<redacted>"


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _credential_url(text: str) -> Iterator[tuple[int, int]]:
    for match in URL_PATTERN.finditer(text):
        candidate = match.group(0).rstrip(".,);]}")
        try:
            parsed = urlsplit(candidate)
        except ValueError:
            yield match.span()
            continue
        unsafe = parsed.username is not None or parsed.password is not None
        if not unsafe:
            for raw_name, value in parse_qsl(parsed.query, keep_blank_values=True):
                name = raw_name.casefold().replace("-", "_").replace(".", "_")
                if value and (name.startswith(("x_amz_", "x_goog_")) or name in SECRET_QUERY_NAMES):
                    unsafe = True
                    break
        if unsafe:
            yield match.span()


def _sequence_like(value: str, minimum: int = 40) -> bool:
    text = KNOWN_SHA256_VALUE.sub(lambda match: match.group("prefix") + ("0" * 64), value)
    if text.lstrip().startswith(">"):
        return True
    if re.search(r"[^A-Za-z*\s\d-]", text):
        return False
    compact = re.sub(r"[\s\d-]", "", text)
    if len(compact) < minimum or not re.fullmatch(
        r"[ACDEFGHIKLMNPQRSTVWYBXZJUO*]+", compact.upper()
    ):
        return False
    if re.fullmatch(r"[ACGTUN]+", compact.upper()):
        return True
    letters = re.sub(r"[^A-Za-z]", "", text)
    if not letters:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    groups = re.findall(r"[A-Za-z*]+", text)
    if not (letters.isupper() or letters.islower()):
        wrapped_lines = (
            len(lines) >= 2
            and all(not re.search(r"[ \t]", line) for line in lines)
            and min(map(len, lines)) >= 15
        )
        grouped_wrap = (
            len(groups) >= 2
            and min(map(len, groups)) >= 15
            and max(map(len, groups)) - min(map(len, groups)) <= 1
        )
        return wrapped_lines or grouped_wrap
    if lines and all(not re.search(r"[ \t]", line) for line in lines):
        return True
    if len(groups) < 4:
        return False
    width = len(groups[0])
    return (
        width >= 4
        and all(len(group) == width for group in groups[:-1])
        and 1 <= len(groups[-1]) <= width
    )


def _sequence_spans(text: str) -> Iterator[tuple[int, int]]:
    masked = KNOWN_SHA256_VALUE.sub(lambda match: match.group("prefix") + ("0" * 64), text)
    if _sequence_like(masked):
        yield (0, len(text))
        return
    contiguous = re.finditer(r"(?<![A-Za-z*])[A-Za-z*]{40,}(?![A-Za-z*])", masked)
    for match in contiguous:
        if _sequence_like(match.group(0)):
            yield match.span()
    candidates = re.finditer(
        r"(?<![A-Za-z*])(?:[A-Za-z*]{4,}(?:[ \t\d-]+|\r?\n)){1,}"
        r"[A-Za-z*]{1,}(?![A-Za-z*])",
        masked,
    )
    for match in candidates:
        if _sequence_like(match.group(0)):
            yield match.span()


def _absolute_without_resolving(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _display_path(path: Path, root: Path, *, root_is_file: bool) -> str:
    return path.name if root_is_file else path.relative_to(root).as_posix()


def _candidates(root: Path) -> Iterator[Path]:
    if root.is_symlink() or not root.is_dir():
        yield root
        return
    for current, directories, names in os.walk(root, followlinks=False):
        base = Path(current)
        kept: list[str] = []
        for name in sorted(directories):
            if name in EXCLUDED_DIRECTORIES:
                continue
            candidate = base / name
            if candidate.is_symlink():
                yield candidate
            else:
                kept.append(name)
        directories[:] = kept
        for name in sorted(names):
            path = base / name
            if name in EXCLUDED_FILES or path.suffix.casefold() in EXCLUDED_SUFFIXES:
                continue
            yield path


def _owned_bytes(path: Path) -> tuple[bytes | None, str | None]:
    try:
        named_before = os.stat(path, follow_symlinks=False)
    except OSError:
        return None, "file-open-failed"
    if not stat.S_ISREG(named_before.st_mode):
        return None, "non-regular-file"
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None, "file-open-failed"
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            return None, "non-regular-file"
        if before.st_size > MAX_TEXT_BYTES:
            return None, "file-too-large"
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1 << 20, MAX_TEXT_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_TEXT_BYTES:
                return None, "file-too-large"
        after = os.fstat(descriptor)
        try:
            named = os.stat(path, follow_symlinks=False)
        except OSError:
            return None, "file-changed-during-scan"
        identity = lambda item: (item.st_dev, item.st_ino)  # noqa: E731
        if (
            identity(named_before) != identity(before)
            or identity(before) != identity(after)
            or identity(after) != identity(named)
        ):
            return None, "file-changed-during-scan"
        data = b"".join(chunks)
        if len(data) != after.st_size:
            return None, "file-changed-during-scan"
        return data, None
    finally:
        os.close(descriptor)


def _scan_text(
    text: str,
    *,
    path: str,
    rules: tuple[tuple[str, re.Pattern[str]], ...],
) -> list[Finding]:
    # JSON may legally escape solidus characters. Normalizing them for scanning
    # preserves length/offsets while exposing signed URLs to the ordinary rules.
    text = text.replace("\\/", "/")
    for escaped_whitespace in ("\\n", "\\r", "\\t"):
        text = text.replace(escaped_whitespace, "  ")
    findings: list[Finding] = []
    for rule_name, pattern in rules:
        for match in pattern.finditer(text):
            findings.append(
                Finding(
                    rule=rule_name,
                    path=path,
                    line=_line_number(text, match.start()),
                    excerpt=_safe_excerpt(text, match.start(), match.end()),
                )
            )
    for start, end in _credential_url(text):
        findings.append(
            Finding(
                rule="credential-url",
                path=path,
                line=_line_number(text, start),
                excerpt=_safe_excerpt(text, start, end),
            )
        )
    for start, end in _sequence_spans(text):
        findings.append(
            Finding(
                rule="raw-biological-sequence",
                path=path,
                line=_line_number(text, start),
                excerpt=_safe_excerpt(text, start, end),
            )
        )
    return findings


def scan(root: Path, forbidden_terms: Iterable[str] = ()) -> list[Finding]:
    root = _absolute_without_resolving(root)
    base_rules = list(_patterns())
    for index, term in enumerate(forbidden_terms, start=1):
        if term:
            base_rules.append(
                (f"forbidden-term-{index}", re.compile(re.escape(term), re.IGNORECASE))
            )
    rules = tuple(base_rules)
    findings: list[Finding] = []
    root_is_file = not root.is_dir() or root.is_symlink()
    for path in _candidates(root):
        display = _display_path(path, root, root_is_file=root_is_file)
        path_findings = _scan_text(display, path="<redacted-path>", rules=rules)
        safe_display = "<redacted-path>" if path_findings else display
        findings.extend(
            Finding(f"path-{item.rule}", "<redacted-path>", 0, "<redacted>")
            for item in path_findings
        )
        if path.is_symlink():
            findings.append(Finding("symbolic-link", safe_display, 0, "<redacted>"))
            try:
                target = os.readlink(path)
            except OSError:
                findings.append(
                    Finding("symlink-target-unavailable", safe_display, 0, "<redacted>")
                )
                continue
            target_findings = _scan_text(target, path=safe_display, rules=rules)
            findings.extend(
                Finding(f"symlink-target-{item.rule}", safe_display, 0, item.excerpt)
                for item in target_findings
            )
            continue
        if path.suffix.casefold() in RISKY_BIOLOGICAL_SUFFIXES:
            findings.append(Finding("biological-file-extension", safe_display, 0, "<redacted>"))
            continue
        data, error = _owned_bytes(path)
        if error is not None:
            findings.append(Finding(error, safe_display, 0, "<redacted>"))
            continue
        assert data is not None
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            findings.append(Finding("content-not-utf8", safe_display, 0, "<redacted>"))
            continue
        if any(
            (ord(character) < 32 and ord(character) not in ALLOWED_CONTROLS)
            or 127 <= ord(character) <= 159
            for character in text
        ):
            findings.append(Finding("binary-control-content", safe_display, 0, "<redacted>"))
            continue
        findings.extend(_scan_text(text, path=safe_display, rules=rules))
    return findings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Scan a public-release tree for private paths, accessions, sequences, "
            "credentials, symbolic links, and binary content."
        )
    )
    parser.add_argument("path", nargs="?", default=".", help="File or directory to scan.")
    parser.add_argument(
        "--forbidden-term",
        action="append",
        default=[],
        help="Additional case-insensitive internal term to reject; repeat as needed.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    path = Path(arguments.path)
    if not path.exists() and not path.is_symlink():
        print("privacy scan failed: path does not exist", file=sys.stderr)
        return 2
    findings = scan(path, arguments.forbidden_term)
    if arguments.json:
        print(json.dumps([asdict(item) for item in findings], indent=2, sort_keys=True))
    elif findings:
        for item in findings:
            print(f"{item.path}:{item.line}: {item.rule}: {item.excerpt}")
    else:
        print("privacy scan passed: no blocked patterns found")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
