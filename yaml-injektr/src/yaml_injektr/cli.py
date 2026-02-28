"""CLI for bulk front matter replacement in Obsidian vaults."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import sys
import tempfile
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .core import normalize_payload_text, transform_markdown

DEFAULT_EXCLUDE_DIRS = (".obsidian", ".trash", ".git", "node_modules")


class CLIUsageError(Exception):
    """Raised when command-line usage/input is invalid."""


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CLIUsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="yaml-injektr")
    parser.add_argument("--target", required=True, help="Target markdown file or directory")
    parser.add_argument("--payload", required=True, help="YAML payload file path")
    parser.add_argument("--apply", action="store_true", help="Apply in-place changes (default: dry-run)")
    parser.add_argument(
        "--glob",
        default="**/*.md",
        help="Glob pattern when --target is a directory (default: **/*.md)",
    )
    parser.add_argument(
        "--exclude-dir",
        action="append",
        default=[],
        help="Directory name to exclude; repeatable. Adds to the default excludes unless --no-default-excludes is set.",
    )
    parser.add_argument(
        "--no-default-excludes",
        action="store_true",
        help="Do not apply default excluded directories (e.g., .obsidian, .trash, .git, node_modules).",
    )
    parser.add_argument("--no-json", action="store_true", help="Disable JSONL per-file output")
    parser.add_argument("--no-summary", action="store_true", help="Disable human summary output")
    parser.add_argument("--verbose", action="store_true", help="Include per-file details in summary")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except CLIUsageError as exc:
        parser.print_usage(sys.stderr)
        print(f"{parser.prog}: error: {exc}", file=sys.stderr)
        return 1

    target_path = Path(args.target)
    payload_path = Path(args.payload)

    if not payload_path.is_file():
        print(f"{parser.prog}: error: payload file not found: {payload_path}", file=sys.stderr)
        return 1

    if not target_path.exists() or (not target_path.is_file() and not target_path.is_dir()):
        print(f"{parser.prog}: error: target must be a file or directory: {target_path}", file=sys.stderr)
        return 1

    try:
        payload_text = payload_path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"{parser.prog}: error: failed to read payload: {exc}", file=sys.stderr)
        return 1

    try:
        payload_text = normalize_payload_text(payload_text)
    except ValueError as exc:
        print(f"{parser.prog}: error: invalid payload: {exc}", file=sys.stderr)
        return 1

    exclude_dirs = set(args.exclude_dir)
    if not args.no_default_excludes:
        exclude_dirs |= set(DEFAULT_EXCLUDE_DIRS)

    try:
        files, skipped_dirs = collect_target_files(target_path, args.glob, exclude_dirs)
    except CLIUsageError as exc:
        print(f"{parser.prog}: error: {exc}", file=sys.stderr)
        return 1

    # Emit JSONL records for skipped directories (excluded via --exclude-dir/default excludes).
    # We keep these separate from per-file processing records so "scanned" continues
    # to mean "files considered", while still providing a complete JSONL stream.
    if skipped_dirs and not args.no_json:
        for dir_path in skipped_dirs:
            skip_record: Dict[str, object] = {
                "path": str(dir_path),
                "status": "skipped",
                "had_frontmatter": False,
                "preserved_uuid": False,
                "generated_uuid": False,
                "reason": "excluded_dir",
                "is_dir": True,
            }
            print(json.dumps(skip_record, ensure_ascii=False))

    records: List[Dict[str, object]] = []
    for file_path in files:
        record = process_file(file_path, payload_text, apply=args.apply)
        records.append(record)
        if not args.no_json:
            print(json.dumps(record, ensure_ascii=False))

    if not args.no_summary:
        print_summary(records, skipped_dirs=skipped_dirs, verbose=args.verbose, apply=args.apply)

    return 2 if any(rec["status"] == "error" for rec in records) else 0


def collect_target_files(target: Path, pattern: str, exclude_dirs: Set[str]) -> Tuple[List[Path], List[Path]]:
    """Collect markdown files under a target.

    Returns (files, skipped_dirs). Skipped directories are those pruned due to excludes.

    We intentionally prune excluded directories while walking to avoid expensive traversal
    (e.g., node_modules), but still surface what was skipped in the output stream.
    """

    if target.is_file():
        return [target], []

    # Normalize pattern to POSIX separators for matching.
    pattern_posix = pattern.replace("\\", "/")
    recursive_md = pattern_posix == "**/*.md"
    basename_only = "/" not in pattern_posix

    case_insensitive = os.name == "nt"
    exclude_norm = {
        (name.casefold() if case_insensitive else name): name for name in exclude_dirs
    }

    files: List[Path] = []
    skipped_dirs: List[Path] = []

    for dirpath_str, dirnames, filenames in os.walk(target):
        dirpath = Path(dirpath_str)

        # Prune excluded directories.
        kept_dirnames: List[str] = []
        for dname in dirnames:
            key = dname.casefold() if case_insensitive else dname
            if key in exclude_norm:
                skipped_dirs.append(dirpath / dname)
            else:
                kept_dirnames.append(dname)
        dirnames[:] = kept_dirnames

        for fname in filenames:
            candidate = dirpath / fname
            if not candidate.is_file():
                continue

            rel = candidate.relative_to(target)
            rel_posix = rel.as_posix()
            rel_pp = PurePosixPath(rel_posix)

            if recursive_md:
                if not (rel_pp.match("**/*.md") or rel_pp.match("*.md")):
                    continue
            elif basename_only:
                # Basename-only patterns are root-only.
                if len(rel.parts) != 1:
                    continue
                if not fnmatch.fnmatch(rel_pp.name, pattern_posix):
                    continue
            else:
                patterns = [pattern_posix]
                if pattern_posix.startswith("**/"):
                    patterns.append(pattern_posix[3:])

                if not any(rel_pp.match(pat) for pat in patterns):
                    continue

            files.append(candidate)

    files.sort(key=lambda path: str(path))
    skipped_dirs.sort(key=lambda path: str(path))
    return files, skipped_dirs


def process_file(path: Path, payload_text: str, *, apply: bool) -> Dict[str, object]:
    record: Dict[str, object] = {
        "path": str(path),
        "status": "error",
        "had_frontmatter": False,
        "preserved_uuid": False,
        "generated_uuid": False,
        "reason": "",
    }

    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        record["reason"] = f"read_failed: {exc}"
        return record

    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        record["reason"] = f"decode_failed: {exc}"
        return record

    try:
        new_text, info = transform_markdown(text, payload_text, preserve_uuid=True)
    except Exception as exc:  # pragma: no cover - defensive catch for unexpected exceptions.
        record["reason"] = f"transform_failed: {exc}"
        return record

    record["had_frontmatter"] = bool(info.get("had_frontmatter", False))
    record["preserved_uuid"] = bool(info.get("preserved_uuid", False))
    record["generated_uuid"] = bool(info.get("generated_uuid", False))

    if bool(info.get("error", False)):
        record["status"] = "error"
        record["reason"] = str(info.get("reason") or "transform_error")
        return record

    new_bytes = new_text.encode("utf-8")
    if new_bytes == raw_bytes:
        record["status"] = "unchanged"
        record["reason"] = ""
        return record

    if not apply:
        record["status"] = "changed"
        record["reason"] = "dry_run"
        return record

    try:
        atomic_write(path, new_bytes)
    except OSError as exc:
        record["status"] = "error"
        record["reason"] = f"write_failed: {exc}"
        return record

    record["status"] = "changed"
    record["reason"] = ""
    return record


def atomic_write(path: Path, content: bytes) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)

    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def print_summary(
    records: List[Dict[str, object]],
    *,
    skipped_dirs: Sequence[Path],
    verbose: bool,
    apply: bool,
) -> None:
    changed = sum(1 for rec in records if rec["status"] == "changed")
    unchanged = sum(1 for rec in records if rec["status"] == "unchanged")
    skipped = len(skipped_dirs)
    errors = sum(1 for rec in records if rec["status"] == "error")

    scanned = len(records)
    mode = "apply" if apply else "dry-run"
    lines = [
        f"mode: {mode}",
        f"scanned: {scanned}",
        f"changed: {changed}",
        f"unchanged: {unchanged}",
        f"skipped: {skipped}",
        f"errors: {errors}",
    ]

    if verbose:
        for rec in records:
            reason = f" ({rec['reason']})" if rec.get("reason") else ""
            lines.append(f"{rec['status']}: {rec['path']}{reason}")
        for dir_path in skipped_dirs:
            lines.append(f"skipped: {dir_path} (excluded_dir)")

    print("\n".join(lines), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
