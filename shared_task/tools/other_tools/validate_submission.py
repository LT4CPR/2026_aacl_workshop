#!/usr/bin/env python3
"""
LT4CPR shared-task submission validator.

Validates a TEAM submission ZIP against the released TEST INPUT package.

Expected submission structure:

    <team_id>.zip
    └── <team_id>/
        ├── submission.json
        └── systems/
            ├── <system_id_1>/test/<crisis>/<cell>.report.json
            └── <system_id_2>/test/<crisis>/<cell>.report.json

Each system must provide exactly one report for every released
*.tweets.jsonl test input.

The validator checks:
  * ZIP safety and top-level layout
  * submission.json structure
  * team/system IDs and primary-system rule
  * manifest/system-directory agreement
  * exact report-file coverage against the released test inputs
  * report JSON structure
  * section/subsection/bullet IDs and hierarchy
  * binary confidence labels
  * tweet_ids validity against the paired input file
  * duplicate evidence IDs
  * obvious internal/organizer identifier leakage

Python standard library only.

Exit codes:
    0  VALID
    1  INVALID submission
    2  validator/configuration error
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Set, Tuple


SUBMISSION_FORMAT_VERSION = "1.0"
REPORT_SCHEMA_VERSION = "1.2"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SECTION_ID_RE = re.compile(r"^(?:[1-9]|1[01])$")
SUBSECTION_ID_RE = re.compile(r"^((?:[1-9]|1[01]))([a-z]+)$")
BULLET_ID_RE = re.compile(r"^((?:[1-9]|1[01])[a-z]+)\.([1-9][0-9]*)$")

SECTION_TITLES = {
    "1": "Situation overview",
    "2": "Timeline",
    "3": "Casualties and human impact",
    "4": "Infrastructure and service impact",
    "5": "Displacement and movement",
    "6": "Hazard assessment",
    "7": "Response actions",
    "8": "Communication and information",
    "9": "Aid and relief",
    "10": "Organizational and administrative activity",
    "11": "Social and community response",
}

ALLOWED_CONFIDENCE = {"confirmed", "unconfirmed"}

FORBIDDEN_KEY_NAMES = {
    "projection_signature",
    "canonical_links",
    "semantic_payload_hash",
    "source_plan",
    "source_plan_ids",
    "source_tweet_plan_id",
    "tweet_plan_id",
    "generation_method",
    "generation_valid",
    "projection_valid",
    "projection_warnings",
    "rewrite_status",
    "rewrite_candidate",
    "rewrite_model",
    "judge_status",
    "judge_verdict",
    "risk_level",
    "coverage",
    "bundle",
    "bundles",
    "canonical_entities",
    "events",
    "relations",
    "entities",
    "internal_id",
    "organizer",
    "organizer_metadata",
}

FORBIDDEN_VALUE_PATTERNS = [
    re.compile(r"\bSYN_\d{4,}\b"),
    re.compile(r"\bEV_CAN_[A-Za-z0-9_]+\b"),
    re.compile(r"\bE_CAN_[A-Za-z0-9_]+\b"),
    re.compile(r"\bTP_\d{3,}\b"),
]

EXPECTED_TOP_LEVEL_REPORT_KEYS = {"meta", "sections"}
EXPECTED_META_KEYS = {"schema_version"}
REQUIRED_BULLET_KEYS = {"id", "text", "confidence", "tweet_ids"}
ALLOWED_BULLET_KEYS = REQUIRED_BULLET_KEYS
REQUIRED_SECTION_KEYS = {"id", "title", "subsections"}
ALLOWED_SECTION_KEYS = REQUIRED_SECTION_KEYS
REQUIRED_SUBSECTION_KEYS = {"id", "title", "bullets"}
ALLOWED_SUBSECTION_KEYS = REQUIRED_SUBSECTION_KEYS


class ValidationFailure(Exception):
    pass


@dataclass(frozen=True)
class TestCell:
    crisis: str
    stem: str
    tweet_path: str
    tweet_ids: frozenset[int]


@dataclass
class Result:
    errors: List[str]
    warnings: List[str]

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


class SourceFS:
    """Read-only abstraction over a directory or ZIP archive."""

    def __init__(self, source: Path):
        self.source = source
        self._zip: Optional[zipfile.ZipFile] = None

        if source.is_dir():
            self.kind = "dir"
        elif source.is_file() and zipfile.is_zipfile(source):
            self.kind = "zip"
            self._zip = zipfile.ZipFile(source, "r")
        else:
            raise ValidationFailure(
                f"Test-data source is neither a directory nor a ZIP archive: {source}"
            )

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()

    def names(self) -> List[str]:
        if self.kind == "dir":
            out: List[str] = []
            for p in self.source.rglob("*"):
                if p.is_file():
                    out.append(p.relative_to(self.source).as_posix())
            return sorted(out)
        assert self._zip is not None
        return sorted(n for n in self._zip.namelist() if not n.endswith("/"))

    def read_text(self, name: str) -> str:
        if self.kind == "dir":
            return (self.source / PurePosixPath(name)).read_text(encoding="utf-8")
        assert self._zip is not None
        with self._zip.open(name, "r") as f:
            return f.read().decode("utf-8")


def is_safe_zip_member(name: str) -> bool:
    p = PurePosixPath(name)
    if p.is_absolute():
        return False
    if ".." in p.parts:
        return False
    if "\\" in name:
        return False
    return True


def json_loads_strict(text: str, where: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValidationFailure(
            f"{where}: invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}"
        ) from e


def expect_dict(obj: Any, where: str, result: Result) -> Optional[Dict[str, Any]]:
    if not isinstance(obj, dict):
        result.error(f"{where}: expected JSON object, got {type(obj).__name__}")
        return None
    return obj


def expect_list(obj: Any, where: str, result: Result) -> Optional[List[Any]]:
    if not isinstance(obj, list):
        result.error(f"{where}: expected JSON array, got {type(obj).__name__}")
        return None
    return obj


def check_exact_keys(
    obj: Mapping[str, Any],
    required: Set[str],
    allowed: Set[str],
    where: str,
    result: Result,
) -> None:
    missing = sorted(required - set(obj))
    extra = sorted(set(obj) - allowed)
    if missing:
        result.error(f"{where}: missing required keys: {', '.join(missing)}")
    if extra:
        result.error(f"{where}: unexpected keys: {', '.join(extra)}")


def scan_for_internal_leakage(obj: Any, where: str, result: Result) -> None:
    """Recursively reject obvious construction-time identifiers/metadata."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k) in FORBIDDEN_KEY_NAMES:
                result.error(f"{where}: forbidden internal key {k!r}")
            scan_for_internal_leakage(v, f"{where}.{k}", result)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            scan_for_internal_leakage(v, f"{where}[{i}]", result)
    elif isinstance(obj, str):
        for pat in FORBIDDEN_VALUE_PATTERNS:
            if pat.search(obj):
                result.error(
                    f"{where}: contains forbidden internal identifier matching {pat.pattern!r}"
                )


def parse_test_cells(test_source: Path) -> Dict[Tuple[str, str], TestCell]:
    fs = SourceFS(test_source)
    try:
        names = fs.names()
        tweet_files = [
            n
            for n in names
            if n.endswith(".tweets.jsonl")
            and "/test/" in f"/{n}"
        ]

        # Also accept a package rooted directly at test/.
        if not tweet_files:
            tweet_files = [n for n in names if n.startswith("test/") and n.endswith(".tweets.jsonl")]

        if not tweet_files:
            raise ValidationFailure(
                "No test/*.tweets.jsonl files found in the provided test-data source."
            )

        cells: Dict[Tuple[str, str], TestCell] = {}

        for name in sorted(tweet_files):
            parts = PurePosixPath(name).parts
            try:
                test_idx = parts.index("test")
            except ValueError:
                continue

            if len(parts) != test_idx + 3:
                raise ValidationFailure(
                    f"Unexpected test input path {name!r}; expected test/<crisis>/<cell>.tweets.jsonl"
                )

            crisis = parts[test_idx + 1]
            filename = parts[test_idx + 2]
            stem = filename[: -len(".tweets.jsonl")]

            tweet_ids: Set[int] = set()
            text = fs.read_text(name)

            for lineno, raw in enumerate(text.splitlines(), start=1):
                if not raw.strip():
                    continue
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError as e:
                    raise ValidationFailure(
                        f"{name}:{lineno}: invalid JSONL record: {e.msg}"
                    ) from e

                if not isinstance(rec, dict):
                    raise ValidationFailure(
                        f"{name}:{lineno}: expected JSON object record"
                    )

                # Tweet records are participant records with id/text/source/timestamp.
                if "id" in rec and "text" in rec and "timestamp" in rec:
                    tid = rec["id"]
                    if isinstance(tid, bool) or not isinstance(tid, int) or tid <= 0:
                        raise ValidationFailure(
                            f"{name}:{lineno}: tweet id must be a positive integer, got {tid!r}"
                        )
                    if tid in tweet_ids:
                        raise ValidationFailure(
                            f"{name}:{lineno}: duplicate tweet id {tid}"
                        )
                    tweet_ids.add(tid)

            if not tweet_ids:
                raise ValidationFailure(f"{name}: no tweet records found")

            key = (crisis, stem)
            if key in cells:
                raise ValidationFailure(
                    f"Duplicate test cell identity {crisis}/{stem}"
                )

            cells[key] = TestCell(
                crisis=crisis,
                stem=stem,
                tweet_path=name,
                tweet_ids=frozenset(tweet_ids),
            )

        return cells
    finally:
        fs.close()


def validate_manifest(
    manifest: Any,
    top_team_dir: str,
    result: Result,
) -> Tuple[Optional[str], Dict[str, Dict[str, Any]]]:
    m = expect_dict(manifest, "submission.json", result)
    if m is None:
        return None, {}

    allowed_top = {"submission_format_version", "team", "systems"}
    check_exact_keys(m, allowed_top, allowed_top, "submission.json", result)

    if m.get("submission_format_version") != SUBMISSION_FORMAT_VERSION:
        result.error(
            "submission.json: submission_format_version must be "
            f"{SUBMISSION_FORMAT_VERSION!r}"
        )

    team = expect_dict(m.get("team"), "submission.json.team", result)
    team_id: Optional[str] = None
    if team is not None:
        check_exact_keys(
            team, {"id", "name"}, {"id", "name"}, "submission.json.team", result
        )
        raw_id = team.get("id")
        raw_name = team.get("name")

        if not isinstance(raw_id, str) or not ID_RE.fullmatch(raw_id):
            result.error(
                "submission.json.team.id: must match "
                r"[a-z0-9][a-z0-9_-]*"
            )
        else:
            team_id = raw_id
            if team_id != top_team_dir:
                result.error(
                    "submission.json.team.id does not match top-level directory: "
                    f"{team_id!r} != {top_team_dir!r}"
                )

        if not isinstance(raw_name, str) or not raw_name.strip():
            result.error("submission.json.team.name: must be a non-empty string")

    systems_raw = expect_list(m.get("systems"), "submission.json.systems", result)
    systems: Dict[str, Dict[str, Any]] = {}

    if systems_raw is not None:
        if len(systems_raw) == 0:
            result.error("submission.json.systems: at least one system is required")

        primary_count = 0
        for i, item in enumerate(systems_raw):
            where = f"submission.json.systems[{i}]"
            s = expect_dict(item, where, result)
            if s is None:
                continue

            check_exact_keys(
                s,
                {"id", "name", "primary"},
                {"id", "name", "primary"},
                where,
                result,
            )

            sid = s.get("id")
            name = s.get("name")
            primary = s.get("primary")

            if not isinstance(sid, str) or not ID_RE.fullmatch(sid):
                result.error(f"{where}.id: must match [a-z0-9][a-z0-9_-]*")
                continue

            if sid in systems:
                result.error(f"{where}.id: duplicate system id {sid!r}")
            else:
                systems[sid] = s

            if not isinstance(name, str) or not name.strip():
                result.error(f"{where}.name: must be a non-empty string")

            if not isinstance(primary, bool):
                result.error(f"{where}.primary: must be true or false")
            elif primary:
                primary_count += 1

        if primary_count != 1:
            result.error(
                "submission.json.systems: exactly one system must have primary=true; "
                f"found {primary_count}"
            )

    return team_id, systems


def validate_report(
    report: Any,
    cell: TestCell,
    where: str,
    result: Result,
) -> None:
    obj = expect_dict(report, where, result)
    if obj is None:
        return

    check_exact_keys(
        obj,
        EXPECTED_TOP_LEVEL_REPORT_KEYS,
        EXPECTED_TOP_LEVEL_REPORT_KEYS,
        where,
        result,
    )

    scan_for_internal_leakage(obj, where, result)

    meta = expect_dict(obj.get("meta"), f"{where}.meta", result)
    if meta is not None:
        check_exact_keys(
            meta,
            EXPECTED_META_KEYS,
            EXPECTED_META_KEYS,
            f"{where}.meta",
            result,
        )
        if meta.get("schema_version") != REPORT_SCHEMA_VERSION:
            result.error(
                f"{where}.meta.schema_version: must be {REPORT_SCHEMA_VERSION!r}"
            )

    sections = expect_list(obj.get("sections"), f"{where}.sections", result)
    if sections is None:
        return

    seen_section_ids: Set[str] = set()
    seen_bullet_ids: Set[str] = set()
    previous_section_num = 0

    for si, sec_raw in enumerate(sections):
        sec_where = f"{where}.sections[{si}]"
        sec = expect_dict(sec_raw, sec_where, result)
        if sec is None:
            continue

        check_exact_keys(
            sec,
            REQUIRED_SECTION_KEYS,
            ALLOWED_SECTION_KEYS,
            sec_where,
            result,
        )

        sec_id = sec.get("id")
        title = sec.get("title")

        if not isinstance(sec_id, str) or not SECTION_ID_RE.fullmatch(sec_id):
            result.error(f"{sec_where}.id: expected string section id '1'..'11'")
            continue

        if sec_id in seen_section_ids:
            result.error(f"{sec_where}.id: duplicate section id {sec_id!r}")
        seen_section_ids.add(sec_id)

        sec_num = int(sec_id)
        if sec_num <= previous_section_num:
            result.error(
                f"{sec_where}.id: sections must appear in increasing numeric order"
            )
        previous_section_num = sec_num

        expected_title = SECTION_TITLES.get(sec_id)
        if title != expected_title:
            result.error(
                f"{sec_where}.title: expected {expected_title!r}, got {title!r}"
            )

        subsections = expect_list(
            sec.get("subsections"), f"{sec_where}.subsections", result
        )
        if subsections is None:
            continue

        seen_sub_ids: Set[str] = set()

        for subi, sub_raw in enumerate(subsections):
            sub_where = f"{sec_where}.subsections[{subi}]"
            sub = expect_dict(sub_raw, sub_where, result)
            if sub is None:
                continue

            check_exact_keys(
                sub,
                REQUIRED_SUBSECTION_KEYS,
                ALLOWED_SUBSECTION_KEYS,
                sub_where,
                result,
            )

            sub_id = sub.get("id")
            sub_title = sub.get("title")

            if not isinstance(sub_id, str):
                result.error(f"{sub_where}.id: must be a string")
                continue

            m = SUBSECTION_ID_RE.fullmatch(sub_id)
            if not m:
                result.error(
                    f"{sub_where}.id: expected subsection id such as '3a' or '10b'"
                )
                continue

            if m.group(1) != sec_id:
                result.error(
                    f"{sub_where}.id: subsection {sub_id!r} does not belong to section {sec_id!r}"
                )

            if sub_id in seen_sub_ids:
                result.error(f"{sub_where}.id: duplicate subsection id {sub_id!r}")
            seen_sub_ids.add(sub_id)

            if not isinstance(sub_title, str) or not sub_title.strip():
                result.error(f"{sub_where}.title: must be a non-empty string")

            bullets = expect_list(sub.get("bullets"), f"{sub_where}.bullets", result)
            if bullets is None:
                continue

            for bi, bullet_raw in enumerate(bullets):
                b_where = f"{sub_where}.bullets[{bi}]"
                bullet = expect_dict(bullet_raw, b_where, result)
                if bullet is None:
                    continue

                check_exact_keys(
                    bullet,
                    REQUIRED_BULLET_KEYS,
                    ALLOWED_BULLET_KEYS,
                    b_where,
                    result,
                )

                bid = bullet.get("id")
                btext = bullet.get("text")
                confidence = bullet.get("confidence")
                tids = bullet.get("tweet_ids")

                if not isinstance(bid, str):
                    result.error(f"{b_where}.id: must be a string")
                else:
                    bm = BULLET_ID_RE.fullmatch(bid)
                    if not bm:
                        result.error(
                            f"{b_where}.id: expected bullet id such as '3b.1'"
                        )
                    elif bm.group(1) != sub_id:
                        result.error(
                            f"{b_where}.id: bullet {bid!r} does not belong to subsection {sub_id!r}"
                        )

                    if bid in seen_bullet_ids:
                        result.error(f"{b_where}.id: duplicate report bullet id {bid!r}")
                    seen_bullet_ids.add(bid)

                if not isinstance(btext, str) or not btext.strip():
                    result.error(f"{b_where}.text: must be a non-empty string")

                if confidence not in ALLOWED_CONFIDENCE:
                    result.error(
                        f"{b_where}.confidence: expected 'confirmed' or 'unconfirmed', "
                        f"got {confidence!r}"
                    )

                tids_list = expect_list(tids, f"{b_where}.tweet_ids", result)
                if tids_list is None:
                    continue

                seen_tids: Set[int] = set()
                for ti, tid in enumerate(tids_list):
                    tid_where = f"{b_where}.tweet_ids[{ti}]"

                    if isinstance(tid, bool) or not isinstance(tid, int):
                        result.error(
                            f"{tid_where}: must be an integer tweet id from the paired input"
                        )
                        continue

                    if tid <= 0:
                        result.error(f"{tid_where}: must be a positive integer")

                    if tid in seen_tids:
                        result.error(
                            f"{tid_where}: duplicate tweet id {tid} in the same evidence list"
                        )
                    seen_tids.add(tid)

                    if tid not in cell.tweet_ids:
                        result.error(
                            f"{tid_where}: tweet id {tid} does not exist in "
                            f"{cell.crisis}/{cell.stem}.tweets.jsonl"
                        )


def submission_file_map(zf: zipfile.ZipFile, result: Result) -> Tuple[str, Set[str]]:
    members = zf.infolist()
    file_names: Set[str] = set()
    top_dirs: Set[str] = set()

    for info in members:
        name = info.filename

        if not is_safe_zip_member(name):
            result.error(f"ZIP contains unsafe path: {name!r}")
            continue

        p = PurePosixPath(name)
        if not p.parts:
            continue

        # Reject symlinks (Unix external attributes).
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            result.error(f"ZIP contains symbolic link, which is not allowed: {name!r}")
            continue

        top_dirs.add(p.parts[0])

        if not info.is_dir():
            if name in file_names:
                result.error(f"ZIP contains duplicate file entry: {name!r}")
            file_names.add(name)

    if len(top_dirs) != 1:
        result.error(
            "ZIP must contain exactly one top-level team directory; found: "
            + ", ".join(sorted(top_dirs))
        )
        return "", file_names

    return next(iter(top_dirs)), file_names


def validate_submission(submission_zip: Path, test_source: Path) -> Result:
    result = Result(errors=[], warnings=[])

    if not submission_zip.is_file() or not zipfile.is_zipfile(submission_zip):
        result.error(f"Submission is not a readable ZIP archive: {submission_zip}")
        return result

    try:
        test_cells = parse_test_cells(test_source)
    except ValidationFailure as e:
        raise

    expected_cell_keys = set(test_cells)

    with zipfile.ZipFile(submission_zip, "r") as zf:
        top_team_dir, files = submission_file_map(zf, result)
        if not top_team_dir:
            return result

        if not ID_RE.fullmatch(top_team_dir):
            result.error(
                f"Top-level directory {top_team_dir!r} is not a valid machine-readable team ID"
            )

        manifest_path = f"{top_team_dir}/submission.json"
        if manifest_path not in files:
            result.error(f"Missing required file: {manifest_path}")
            return result

        try:
            manifest_text = zf.read(manifest_path).decode("utf-8")
        except UnicodeDecodeError:
            result.error(f"{manifest_path}: must be UTF-8")
            return result

        try:
            manifest = json_loads_strict(manifest_text, manifest_path)
        except ValidationFailure as e:
            result.error(str(e))
            return result

        team_id, systems = validate_manifest(manifest, top_team_dir, result)

        systems_prefix = f"{top_team_dir}/systems/"
        actual_system_dirs: Set[str] = set()

        for name in files:
            if not name.startswith(systems_prefix):
                continue
            rest = name[len(systems_prefix):]
            parts = PurePosixPath(rest).parts
            if parts:
                actual_system_dirs.add(parts[0])

        declared_system_dirs = set(systems)

        missing_system_dirs = sorted(declared_system_dirs - actual_system_dirs)
        extra_system_dirs = sorted(actual_system_dirs - declared_system_dirs)

        for sid in missing_system_dirs:
            result.error(f"Declared system has no directory: {sid!r}")
        for sid in extra_system_dirs:
            result.error(f"Undeclared system directory present: {sid!r}")

        # Reject unexpected team-level files/directories.
        allowed_prefixes = {
            manifest_path,
        }
        for name in sorted(files):
            if name == manifest_path:
                continue
            if name.startswith(systems_prefix):
                continue
            result.error(f"Unexpected file outside systems/: {name!r}")

        for sid in sorted(declared_system_dirs):
            sys_prefix = f"{top_team_dir}/systems/{sid}/"

            legacy_test_prefix = f"{sys_prefix}test/"
            legacy_test_files = sorted(
                name for name in files if name.startswith(legacy_test_prefix)
            )
            if legacy_test_files:
                result.error(
                    f"system {sid!r}: obsolete 'test/' directory is not allowed; "
                    f"place crisis directories directly under the system directory "
                    f"(for example {sys_prefix}tornado/...)."
                )

            expected_report_paths: Dict[str, Tuple[str, str]] = {}
            for crisis, stem in sorted(expected_cell_keys):
                rel = f"{crisis}/{stem}.report.json"
                expected_report_paths[sys_prefix + rel] = (crisis, stem)

            actual_report_paths = {
                name
                for name in files
                if name.startswith(sys_prefix) and name.endswith(".report.json")
            }

            expected_paths_set = set(expected_report_paths)

            missing = sorted(expected_paths_set - actual_report_paths)
            extra_reports = sorted(actual_report_paths - expected_paths_set)

            if missing:
                result.error(
                    f"system {sid!r}: missing {len(missing)} report file(s); "
                    f"first: {missing[0]!r}"
                )

            if extra_reports:
                result.error(
                    f"system {sid!r}: has {len(extra_reports)} unexpected report file(s); "
                    f"first: {extra_reports[0]!r}"
                )

            # Reject non-report files anywhere inside the system directory.
            extra_nonreports = sorted(
                name
                for name in files
                if name.startswith(sys_prefix)
                and not name.endswith(".report.json")
            )
            for name in extra_nonreports:
                result.error(f"system {sid!r}: unexpected non-report file: {name!r}")

            for report_path in sorted(actual_report_paths & expected_paths_set):
                crisis, stem = expected_report_paths[report_path]
                cell = test_cells[(crisis, stem)]

                try:
                    raw = zf.read(report_path)
                except Exception as e:
                    result.error(f"{report_path}: could not read file: {e}")
                    continue

                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    result.error(f"{report_path}: must be UTF-8")
                    continue

                try:
                    report = json_loads_strict(text, report_path)
                except ValidationFailure as e:
                    result.error(str(e))
                    continue

                validate_report(report, cell, report_path, result)

    return result


def print_result(result: Result, expected_cells: Optional[int] = None) -> None:
    if result.warnings:
        print(f"WARNINGS ({len(result.warnings)}):")
        for w in result.warnings:
            print(f"  - {w}")

    if result.errors:
        print(f"INVALID — {len(result.errors)} error(s)")
        for e in result.errors:
            print(f"  - {e}")
    else:
        suffix = f" against {expected_cells} test cells" if expected_cells is not None else ""
        print(f"VALID — submission passed all checks{suffix}.")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Validate an LT4CPR team submission ZIP."
    )
    p.add_argument(
        "--submission",
        required=True,
        type=Path,
        help="Path to <team_id>.zip",
    )
    p.add_argument(
        "--test-data",
        required=True,
        type=Path,
        help=(
            "Path to the released test-data directory or ZIP. "
            "Used to derive the exact expected cells and valid tweet IDs."
        ),
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    try:
        cells = parse_test_cells(args.test_data)
    except ValidationFailure as e:
        print(f"VALIDATOR ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"VALIDATOR ERROR: failed to read test data: {e}", file=sys.stderr)
        return 2

    # Avoid reparsing test data inside validate_submission by temporarily using
    # the public function's normal path. This second pass is intentional and
    # keeps validate_submission independently callable.
    try:
        result = validate_submission(args.submission, args.test_data)
    except ValidationFailure as e:
        print(f"VALIDATOR ERROR: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"VALIDATOR ERROR: unexpected validator failure: {e}", file=sys.stderr)
        return 2

    print_result(result, expected_cells=len(cells))
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
