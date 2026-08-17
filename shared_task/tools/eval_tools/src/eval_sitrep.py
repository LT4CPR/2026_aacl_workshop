"""Text-level SITREP evaluation utilities."""
from __future__ import annotations

import argparse
import csv
import importlib
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

from evaluation_scope import EvaluationScope, resolve_evaluation_scope
from runtime_env import apply_safe_hf_env, ensure_safe_hf_env_for_main

ensure_safe_hf_env_for_main(__name__)
apply_safe_hf_env()

try:
    from rouge_score import rouge_scorer
except ImportError:
    sys.exit("[evaluate] missing dependency. Run:\n"
             "    pip install -r requirements.txt   (or: pip install rouge-score)")

SCRIPT_DIR = Path(__file__).resolve().parent
RELEASE_ROOT = SCRIPT_DIR.parent

GOLD_DIR = RELEASE_ROOT / "data" / "gold-output"

# Dataset aliases for standalone Markdown compatibility helpers.
# The release runner uses structured JSON inputs and does not use this mapping.
GOLD_FILES = {
    "LA_shootings": "2013_LA_airport_shooting_consolidated_cluster_output_sitrep.md",
    "Manila_floods": "2013_Manila_floods_consolidated_cluster_output_sitrep.md",
}

# Section aliases for standalone Markdown-to-JSON section alignment.
SECTION_MAP = {
    "1": ["overview"],
    "2": ["timeline"],
    "3": ["casualties"],
    "4": ["airport operations", "transport and infrastructure"],
    "5": ["evacuation and displacement"],
    "7": ["emergency response"],
    "8": ["warnings and communications"],
    "11": ["public reaction"],
    "14": ["anticipated and unconfirmed reports"],
}
# Section IDs excluded only by the standalone Markdown compatibility path.
SUPPLEMENTARY = {"6", "12", "13", "15"}

ROUGE_TYPES = ["rouge1", "rouge2", "rougeL"]
SHORT = {"rouge1": "r1", "rouge2": "r2", "rougeL": "rl"}
_SCORER = rouge_scorer.RougeScorer(ROUGE_TYPES, use_stemmer=True)

CITATION_RE = re.compile(r"\[tweets?:[^\]]*\]", re.IGNORECASE)
SEP_ROW_RE = re.compile(r"^[\s|:-]+$")
WS_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    """Strip [tweets: ...] citations and collapse whitespace."""
    return WS_RE.sub(" ", CITATION_RE.sub("", text)).strip()


def parse_gold(md_path: Path) -> dict[str, dict]:
    """Parse a Markdown reference for standalone compatibility commands."""
    lines = md_path.read_text(encoding="utf-8").splitlines()
    sections: dict[str, dict] = {}
    cur_header: str | None = None
    cur_units: list[str] = []

    def flush() -> None:
        if cur_header is not None:
            key = cur_header.strip().lower()
            sections[key] = {
                "header": cur_header.strip(),
                "units": list(cur_units),
                "text": " ".join(cur_units).strip(),
            }

    for raw in lines:
        line = raw.rstrip()
        if line.startswith("## "):
            flush()
            cur_header = line[3:].strip()
            cur_units = []
            continue
        if cur_header is None:
            continue
        stripped = line.strip()
        if not stripped or stripped == "---":
            continue
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if SEP_ROW_RE.match(stripped):
                continue
            low = [c.lower() for c in cells]
            if "event" in low or any(c.startswith("time") for c in low):
                continue
            event = " ".join(cells[1:]) if len(cells) > 1 else cells[0]
            unit = _clean(event)
            if unit:
                cur_units.append(unit)
            continue
        if stripped.startswith(("- ", "* ")):
            unit = _clean(stripped[2:])
            if unit:
                cur_units.append(unit)
            continue
        unit = _clean(stripped)
        if unit:
            cur_units.append(unit)
    flush()
    return sections


def parse_ours(doc: dict) -> dict[str, dict]:
    """Parse structured SITREP JSON into section text."""
    out: dict[str, dict] = {}
    for sec in doc.get("sections", []) or []:
        sid = str(sec.get("id", "")).strip()
        if not sid:
            continue
        units: list[str] = []
        for sub in sec.get("subsections", []) or []:
            for b in sub.get("bullets", []) or []:
                t = (b.get("text") or "").strip()
                if t:
                    units.append(WS_RE.sub(" ", t))
        for b in sec.get("bullets", []) or []:
            t = (b.get("text") or "").strip()
            if t:
                units.append(WS_RE.sub(" ", t))
        out[sid] = {
            "title": sec.get("title", ""),
            "units": units,
            "text": " ".join(units).strip(),
        }
    return out


def score_pair(cand_text: str, ref_text: str) -> dict:
    """Compute ROUGE with the reference as target."""
    res = _SCORER.score(ref_text or "", cand_text or "")
    out = {}
    for rt in ROUGE_TYPES:
        s = res[rt]
        out[rt] = {
            "precision": round(s.precision, 4),
            "recall": round(s.recall, 4),
            "fmeasure": round(s.fmeasure, 4),
        }
    return out


METRIC_NAMES = ("rouge", "bertscore", "bleurt")
MODE_NAMES = {0: "disabled", 1: "document", 2: "section", 3: "subsection"}
DEFAULT_EVAL_CONFIG = RELEASE_ROOT / "config" / "evaluation.yaml"
_HF_METRICS: dict[tuple[str, str | None], object] = {}


def resolve_text_level_block(metrics: dict) -> dict:
    """Return text-level metric settings."""
    if isinstance(metrics.get("text_level"), dict):
        return metrics["text_level"]
    return {name: metrics.get(name, {}) for name in METRIC_NAMES}


def resolve_bullet_level_spec(metrics: dict) -> dict | None:
    """Return bullet-level settings."""
    if isinstance(metrics.get("bullet_level"), dict):
        spec = dict(metrics["bullet_level"])
    elif isinstance(metrics.get("weighted_alignment"), dict):
        spec = dict(metrics["weighted_alignment"])
    else:
        return None
    nested = spec.get("weighted_alignment")
    if isinstance(nested, dict):
        merged = dict(nested)
        merged.update({key: value for key, value in spec.items() if key != "weighted_alignment"})
        return merged
    return spec


def load_evaluation_config(path: Path) -> dict:
    """Load and validate the evaluation config."""
    try:
        yaml = importlib.import_module("yaml")
    except ImportError:
        sys.exit("[evaluate] configured metrics need PyYAML. Run:\n"
                 "    pip install -r requirements.txt")
    if not path.exists():
        sys.exit(f"[evaluate] evaluation config not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    metrics = raw.get("metrics")
    if not isinstance(metrics, dict):
        sys.exit(f"[evaluate] invalid config: {path} must contain a 'metrics' mapping")

    text_level = resolve_text_level_block(metrics)
    result = {}
    for name in METRIC_NAMES:
        spec = text_level.get(name, {}) or {}
        if not isinstance(spec, dict):
            sys.exit(f"[evaluate] invalid config: metrics.text_level.{name} must be a mapping")
        try:
            mode = int(spec.get("mode", 0))
        except (TypeError, ValueError):
            sys.exit(f"[evaluate] invalid config: metrics.text_level.{name}.mode must be 0..3")
        if mode not in MODE_NAMES:
            sys.exit(f"[evaluate] invalid config: metrics.text_level.{name}.mode must be 0..3")
        aggregation = str(spec.get("aggregation", "macro")).lower()
        if aggregation not in {"micro", "macro"}:
            sys.exit(
                f"[evaluate] invalid config: metrics.text_level.{name}.aggregation "
                "must be micro or macro"
            )
        denominator_policy = str(
            spec.get("denominator_policy", "matched_only")
        ).lower()
        if denominator_policy not in {"matched_only", "whole_gold"}:
            sys.exit(
                f"[evaluate] invalid config: metrics.text_level.{name}."
                "denominator_policy must be matched_only or whole_gold"
            )
        if spec.get("include_section_headers") or spec.get("include_subsection_headers"):
            sys.exit(
                f"[evaluate] invalid config: metrics.text_level.{name} headers "
                "are structural keys and cannot be included in scoring"
            )
        result[name] = {
            **spec,
            "mode": mode,
            "aggregation": aggregation,
            "denominator_policy": denominator_policy,
        }
    return result


def _tokenize_for_rouge(text: str) -> list[str]:
    return _SCORER._tokenizer.tokenize(text)


def _ngram_counter(tokens: list[str], n: int) -> Counter[tuple[str, ...]]:
    if len(tokens) < n:
        return Counter()
    return Counter(tuple(tokens[index:index + n]) for index in range(len(tokens) - n + 1))


def _lcs_length(left: list[str], right: list[str]) -> int:
    previous = [0] * (len(right) + 1)
    for left_token in left:
        current = [0]
        for index, right_token in enumerate(right, start=1):
            if left_token == right_token:
                current.append(previous[index - 1] + 1)
            else:
                current.append(max(previous[index], current[-1]))
        previous = current
    return previous[-1]


def _rouge_diagnostics(pairs: list[dict], denominator_policy: str = "matched_only") -> dict:
    active_rows = [
        row for row in pairs
        if row["candidate"].strip() or row["reference"].strip()
    ]
    matched_rows = [
        row for row in active_rows if row["status"] == "matched"
    ]
    whole_gold_rows = [row for row in active_rows if row["reference"].strip()]
    whole_system_rows = [row for row in active_rows if row["candidate"].strip()]
    skipped_both_empty = sum(
        1 for row in pairs
        if not row["candidate"].strip() and not row["reference"].strip()
    )
    diagnostics = {
        "gold_units": len(whole_gold_rows),
        "system_units": len(whole_system_rows),
        "matched_units": len(matched_rows),
        "scored_units": len(active_rows),
        "skipped_both_empty_units": skipped_both_empty,
        "denominator": denominator_policy,
        "denominator_policy": denominator_policy,
        "rouge1": {
            "gold_ngrams": 0,
            "matched_gold_ngrams": 0,
            "whole_gold_ngrams": 0,
            "system_ngrams": 0,
            "matched_system_ngrams": 0,
            "whole_system_ngrams": 0,
            "overlapping_ngrams": 0,
        },
        "rouge2": {
            "gold_ngrams": 0,
            "matched_gold_ngrams": 0,
            "whole_gold_ngrams": 0,
            "system_ngrams": 0,
            "matched_system_ngrams": 0,
            "whole_system_ngrams": 0,
            "overlapping_ngrams": 0,
        },
        "rougeL": {
            "gold_tokens": 0,
            "matched_gold_tokens": 0,
            "whole_gold_tokens": 0,
            "system_tokens": 0,
            "matched_system_tokens": 0,
            "whole_system_tokens": 0,
            "total_lcs_length": 0,
        },
    }
    for row in whole_gold_rows:
        gold_tokens = _tokenize_for_rouge(row["reference"])
        for n, key in ((1, "rouge1"), (2, "rouge2")):
            diagnostics[key]["whole_gold_ngrams"] += sum(
                _ngram_counter(gold_tokens, n).values()
            )
        diagnostics["rougeL"]["whole_gold_tokens"] += len(gold_tokens)
    for row in whole_system_rows:
        system_tokens = _tokenize_for_rouge(row["candidate"])
        for n, key in ((1, "rouge1"), (2, "rouge2")):
            diagnostics[key]["whole_system_ngrams"] += sum(
                _ngram_counter(system_tokens, n).values()
            )
        diagnostics["rougeL"]["whole_system_tokens"] += len(system_tokens)
    for row in matched_rows:
        system_tokens = _tokenize_for_rouge(row["candidate"])
        gold_tokens = _tokenize_for_rouge(row["reference"])
        for n, key in ((1, "rouge1"), (2, "rouge2")):
            gold_ngrams = _ngram_counter(gold_tokens, n)
            system_ngrams = _ngram_counter(system_tokens, n)
            diagnostics[key]["matched_gold_ngrams"] += sum(gold_ngrams.values())
            diagnostics[key]["matched_system_ngrams"] += sum(system_ngrams.values())
            diagnostics[key]["overlapping_ngrams"] += sum(
                (gold_ngrams & system_ngrams).values()
            )
        diagnostics["rougeL"]["matched_gold_tokens"] += len(gold_tokens)
        diagnostics["rougeL"]["matched_system_tokens"] += len(system_tokens)
        diagnostics["rougeL"]["total_lcs_length"] += _lcs_length(gold_tokens, system_tokens)
    for key in ("rouge1", "rouge2"):
        gold_denominator_key = (
            "whole_gold_ngrams" if denominator_policy == "whole_gold"
            else "matched_gold_ngrams"
        )
        system_denominator_key = (
            "whole_system_ngrams" if denominator_policy == "whole_gold"
            else "matched_system_ngrams"
        )
        diagnostics[key]["gold_ngrams"] = diagnostics[key][gold_denominator_key]
        diagnostics[key]["system_ngrams"] = diagnostics[key][system_denominator_key]
    rouge_l_denominator_key = (
        "whole_gold_tokens" if denominator_policy == "whole_gold"
        else "matched_gold_tokens"
    )
    rouge_l_system_denominator_key = (
        "whole_system_tokens" if denominator_policy == "whole_gold"
        else "matched_system_tokens"
    )
    diagnostics["rougeL"]["gold_tokens"] = diagnostics["rougeL"][rouge_l_denominator_key]
    diagnostics["rougeL"]["system_tokens"] = diagnostics["rougeL"][
        rouge_l_system_denominator_key
    ]
    return diagnostics


def _container_bullet_text(container: dict) -> list[str]:
    """Best-effort text extraction without inventing missing hierarchy IDs."""
    texts: list[str] = []
    bullets = container.get("bullets", []) or []
    if isinstance(bullets, list):
        for bullet in bullets:
            raw = bullet.get("text", "") if isinstance(bullet, dict) else bullet
            if isinstance(raw, str) and raw.strip():
                texts.append(WS_RE.sub(" ", raw.strip()))
    return texts


def _metric_hierarchy(path: Path) -> dict[str, object]:
    """Load an evaluation hierarchy and report its available scoring levels."""
    suffix = path.suffix.lower()
    is_json = suffix in (".json", ".jsn")
    if suffix not in (".json", ".jsn", ".md", ".markdown", ".txt"):
        first = path.read_text(encoding="utf-8").lstrip()[:1]
        is_json = bool(first) and first in "{["

    if not is_json:
        gold = parse_gold(path)
        out = {}
        for sid, aliases in SECTION_MAP.items():
            for hkey, sec in gold.items():
                if any(alias in hkey for alias in aliases):
                    out[sid] = {
                        "title": sec["header"], "own_text": sec["text"],
                        "subsections": {}, "kind": "markdown",
                    }
                    break
        return {
            "sections": out,
            "orphan_text": [],
            "availability": {1: True, 2: bool(out), 3: False},
            "warnings": [],
        }

    doc = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict] = {}
    orphan_text: list[str] = []
    warnings: list[dict] = []
    if not isinstance(doc, dict):
        raw = doc if isinstance(doc, str) else ""
        return {
            "sections": {},
            "orphan_text": [WS_RE.sub(" ", raw.strip())] if raw.strip() else [],
            "availability": {1: True, 2: False, 3: False},
            "warnings": [{
                "code": "missing_section_structure",
                "message": "JSON has document content but no section structure",
            }],
        }

    sections = doc.get("sections", []) or []
    if not isinstance(sections, list):
        sections = []
        warnings.append({
            "code": "invalid_sections_type",
            "message": "'sections' is not a list; only document-level evaluation is available",
        })

    for index, sec in enumerate(sections):
        if not isinstance(sec, dict):
            warnings.append({
                "code": "invalid_section_type",
                "message": f"section at index {index} is not an object and was ignored",
            })
            continue
        sid = str(sec.get("id", "")).strip()
        own = _container_bullet_text(sec)
        section_only_text = list(own)
        all_section_text = list(own)
        subsections = {}
        subs = sec.get("subsections", []) or []
        if not isinstance(subs, list):
            subs = []
            warnings.append({
                "code": "invalid_subsections_type",
                "message": f"section {sid or index!r} has non-list subsections",
            })
        for sub_index, sub in enumerate(subs):
            if not isinstance(sub, dict):
                warnings.append({
                    "code": "invalid_subsection_type",
                    "message": f"subsection at section {sid or index!r}, index {sub_index} was ignored",
                })
                continue
            subid = str(sub.get("id", "")).strip()
            texts = _container_bullet_text(sub)
            all_section_text.extend(texts)
            if sid and subid and texts:
                subsections[subid] = {
                    "title": sub.get("title", ""), "text": " ".join(texts).strip()
                }
            elif texts:
                section_only_text.extend(texts)
                warnings.append({
                    "code": "missing_subsection_id",
                    "message": "subsection text is usable only at document/section level because its id is missing",
                })
        if not sid:
            orphan_text.extend(all_section_text)
            if all_section_text:
                warnings.append({
                    "code": "missing_section_id",
                    "message": "section text is usable only at document level because its id is missing",
                })
            continue
        own_text = " ".join(section_only_text).strip()
        if not own_text and not subsections:
            continue
        out[sid] = {
            "title": sec.get("title", ""),
            "own_text": own_text,
            "subsections": subsections, "kind": "json",
        }

    if not sections:
        for key in ("text", "content", "summary", "output"):
            value = doc.get(key)
            if isinstance(value, str) and value.strip():
                orphan_text.append(WS_RE.sub(" ", value.strip()))
                break
    return {
        "sections": out,
        "orphan_text": orphan_text,
        "availability": {
            1: True,
            2: bool(out),
            3: any(sec["subsections"] for sec in out.values()),
        },
        "warnings": warnings,
    }


def _render_section(sec: dict) -> str:
    parts = [sec.get("own_text", "")]
    for sub in sec.get("subsections", {}).values():
        parts.append(sub.get("text", ""))
    return " ".join(p for p in parts if p).strip()


def _filter_metric_hierarchy(
    loaded: dict[str, object],
    selected_sections: tuple[str, ...] | None,
) -> dict[str, object]:
    """Return a hierarchy limited to selected section IDs."""
    if selected_sections is None:
        return loaded
    sections = loaded["sections"]
    selected = set(selected_sections)
    filtered = {
        section_id: section
        for section_id, section in sections.items()
        if section_id in selected
    }
    missing = [section_id for section_id in selected_sections if section_id not in sections]
    warnings = list(loaded["warnings"])
    if missing:
        warnings.append({
            "code": "selected_sections_not_found",
            "message": "requested section IDs were not found in the document",
            "sections": missing,
        })
    return {**loaded, "sections": filtered, "warnings": warnings}


def _configured_pairs(
    candidate: Path,
    reference: Path,
    spec: dict,
    selected_sections: tuple[str, ...] | None = None,
) -> list[dict]:
    """Build text pairs at the configured granularity."""
    cand_doc = _filter_metric_hierarchy(
        _metric_hierarchy(candidate), selected_sections,
    )
    ref_doc = _filter_metric_hierarchy(
        _metric_hierarchy(reference), selected_sections,
    )
    cand = cand_doc["sections"]
    ref = ref_doc["sections"]
    mode = spec["mode"]
    input_warnings = [
        {"side": side, **warning}
        for side, loaded in (("system", cand_doc), ("reference", ref_doc))
        for warning in loaded["warnings"]
    ]
    if mode == 1:
        def render_doc(loaded: dict[str, object]) -> str:
            doc = loaded["sections"]
            parts = []
            for sec in doc.values():
                parts.append(_render_section(sec))
            parts.extend(loaded["orphan_text"])
            return " ".join(p for p in parts if p).strip()
        return [{"unit_id": "document", "status": "matched",
                 "candidate": render_doc(cand_doc), "reference": render_doc(ref_doc),
                 "input_warnings": input_warnings}]

    level = MODE_NAMES[mode]
    unavailable = []
    if not cand_doc["availability"][mode]:
        unavailable.append("system")
    if not ref_doc["availability"][mode]:
        unavailable.append("reference")
    if unavailable:
        return [{
            "unit_id": level,
            "status": "unavailable",
            "candidate": "",
            "reference": "",
            "warning": {
                "code": f"missing_{level}_structure",
                "message": (
                    f"{level}-level evaluation skipped because "
                    f"{', '.join(unavailable)} lacks usable {level} IDs"
                ),
                "sides": unavailable,
            },
            "input_warnings": input_warnings,
        }]

    if mode == 2:
        rows = []
        for sid in sorted(set(cand) | set(ref), key=lambda x: (len(x), x)):
            csec, rsec = cand.get(sid), ref.get(sid)
            status = "matched" if csec and rsec else ("candidate_only" if csec else "reference_only")
            ctext = _render_section(csec) if csec else ""
            rtext = _render_section(rsec) if rsec else ""
            rows.append({"unit_id": f"section:{sid}", "status": status,
                         "candidate": ctext, "reference": rtext})
        if rows:
            rows[0]["input_warnings"] = input_warnings
        return rows

    if any(sec.get("kind") != "json" for sec in (*cand.values(), *ref.values())):
        sys.exit("[evaluate] subsection mode (3) requires two structured JSON inputs; "
                 "the gold markdown has no subsection IDs to align")
    rows = []
    for sid in sorted(set(cand) | set(ref), key=lambda x: (len(x), x)):
        csubs = (cand.get(sid) or {}).get("subsections", {})
        rsubs = (ref.get(sid) or {}).get("subsections", {})
        for subid in sorted(set(csubs) | set(rsubs)):
            csub, rsub = csubs.get(subid), rsubs.get(subid)
            status = "matched" if csub and rsub else ("candidate_only" if csub else "reference_only")
            ctext, rtext = (csub or {}).get("text", ""), (rsub or {}).get("text", "")
            rows.append({"unit_id": f"subsection:{sid}/{subid}", "status": status,
                         "candidate": ctext, "reference": rtext})
    if rows:
        rows[0]["input_warnings"] = input_warnings
    return rows


def _load_hf_evaluate_library():
    """Import Hugging Face Evaluate without local-module shadowing."""

    existing = sys.modules.get("evaluate")
    if existing is not None and hasattr(existing, "load"):
        return existing

    script_dir = SCRIPT_DIR.resolve()
    shadow = sys.modules.pop("evaluate", None)
    original_path = sys.path[:]
    sys.path = [
        entry for entry in sys.path
        if Path(entry).resolve() != script_dir
    ]
    try:
        evaluate_lib = importlib.import_module("evaluate")
    except ImportError as exc:
        sys.path = original_path
        if shadow is not None:
            sys.modules["evaluate"] = shadow
        raise SystemExit("[evaluate] BERTScore/BLEURT need optional dependencies. Run:\n"
                         "    pip install -r requirements.txt") from exc
    finally:
        sys.path = original_path

    if not hasattr(evaluate_lib, "load"):
        sys.modules.pop("evaluate", None)
        if shadow is not None:
            sys.modules["evaluate"] = shadow
        sys.exit("[evaluate] HuggingFace evaluate is unavailable; a local evaluate "
                 "module is shadowing the package. Run:\n"
                 "    pip install -r requirements.txt")

    return evaluate_lib


def _apply_bertscore_tokenizer_compat() -> None:
    """Cap tokenizer lengths that exceed BERTScore model limits."""

    try:
        utils_module = importlib.import_module("bert_score.utils")
    except ImportError:
        return

    def cap_tokenizer(tokenizer: object) -> object:
        max_length = getattr(tokenizer, "model_max_length", 512)
        try:
            needs_cap = int(max_length) > 1_000_000
        except (TypeError, OverflowError, ValueError):
            needs_cap = True
        if needs_cap:
            tokenizer.model_max_length = 512
            init_kwargs = getattr(tokenizer, "init_kwargs", None)
            if isinstance(init_kwargs, dict):
                init_kwargs["model_max_length"] = 512
        return tokenizer

    if not getattr(utils_module, "_lt4cpr_get_tokenizer_patched", False):
        original_get_tokenizer = utils_module.get_tokenizer

        def compatible_get_tokenizer(*args: object, **kwargs: object):
            return cap_tokenizer(original_get_tokenizer(*args, **kwargs))

        compatible_get_tokenizer._lt4cpr_patched = True  # type: ignore[attr-defined]
        utils_module.get_tokenizer = compatible_get_tokenizer
        utils_module._lt4cpr_get_tokenizer_patched = True
        utils_module._lt4cpr_patched = True

        for mod_name in ("bert_score.score", "bert_score.scorer"):
            mod = sys.modules.get(mod_name)
            if mod is not None and hasattr(mod, "get_tokenizer"):
                mod.get_tokenizer = compatible_get_tokenizer

    if not getattr(utils_module, "_lt4cpr_sent_encode_patched", False):
        original_sent_encode = utils_module.sent_encode

        def compatible_sent_encode(tokenizer: object, sent: str):
            return original_sent_encode(cap_tokenizer(tokenizer), sent)

        compatible_sent_encode._lt4cpr_patched = True  # type: ignore[attr-defined]
        utils_module.sent_encode = compatible_sent_encode
        utils_module._lt4cpr_sent_encode_patched = True

        for mod_name in ("bert_score.score", "bert_score.scorer"):
            mod = sys.modules.get(mod_name)
            if mod is not None and hasattr(mod, "sent_encode"):
                mod.sent_encode = compatible_sent_encode


def _find_cached_bleurt_checkpoint(config_name: str) -> Path | None:
    """Return an extracted BLEURT checkpoint from the Hugging Face metric cache."""

    cache_root = (
        Path.home()
        / ".cache" / "huggingface" / "metrics" / "bleurt"
        / config_name / "downloads" / "extracted"
    )
    if not cache_root.is_dir():
        return None
    checkpoint_names = [config_name, config_name.lower(), config_name.upper()]
    candidates = []
    for checkpoint_name in dict.fromkeys(checkpoint_names):
        candidates.extend(cache_root.glob(f"*/{checkpoint_name}"))
    for candidate in sorted(candidates):
        if (candidate / "saved_model.pb").is_file():
            return candidate
    return None


def _score_bleurt(
    references: list[str], predictions: list[str], config_name: str
) -> list[float]:
    checkpoint = _find_cached_bleurt_checkpoint(config_name)
    if checkpoint is not None:
        try:
            from bleurt import score
        except ImportError as exc:
            raise SystemExit(
                "BLEURT is enabled but the bleurt package is not installed. Run:\n"
                "    pip install git+https://github.com/google-research/bleurt.git"
            ) from exc
        scorer = score.BleurtScorer(str(checkpoint))
        return [
            float(value)
            for value in scorer.score(references=references, candidates=predictions)
        ]

    result = _load_hf_metric("bleurt", config_name).compute(
        references=references, predictions=predictions)
    return [float(value) for value in result["scores"]]


def _load_hf_metric(name: str, config_name: str | None = None):
    key = (name, config_name)
    if key in _HF_METRICS:
        return _HF_METRICS[key]
    if name == "bertscore":
        _apply_bertscore_tokenizer_compat()
    evaluate_lib = _load_hf_evaluate_library()
    try:
        metric = evaluate_lib.load(name, config_name=config_name) if config_name else evaluate_lib.load(name)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"[evaluate] could not load {name}: {exc}")
    _HF_METRICS[key] = metric
    return metric


def _score_configured_metric(name: str, pairs: list[dict], spec: dict) -> dict:
    aggregation = str(spec.get("aggregation", "macro")).lower()
    denominator_policy = str(spec.get("denominator_policy", "matched_only")).lower()
    diagnostics = (
        _rouge_diagnostics(pairs, denominator_policy)
        if name == "rouge" else None
    )
    input_warnings = [
        warning
        for row in pairs
        for warning in row.get("input_warnings", [])
    ]
    availability_warnings = [
        row["warning"] for row in pairs
        if row.get("status") == "unavailable" and row.get("warning")
    ]
    if availability_warnings:
        return {
            "mode": MODE_NAMES[spec["mode"]],
            "status": "skipped",
            "reason": availability_warnings[0]["code"],
            "warnings": [*input_warnings, *availability_warnings],
            "aggregation": aggregation,
            "n_scored": 0,
            "n_skipped_both_empty": 0,
            "items": [],
            "aggregates": {"macro": None, "micro": None},
            "overall": None,
            **({"diagnostics": diagnostics} if diagnostics is not None else {}),
        }
    items: list[dict] = []
    active_entries: list[tuple[dict, dict, str]] = []
    compared_rows: list[dict] = []
    zero_items: list[dict] = []
    skipped_both_empty = 0
    for row in pairs:
        item = {"unit_id": row["unit_id"], "status": row["status"]}
        candidate_present = bool(row["candidate"].strip())
        reference_present = bool(row["reference"].strip())
        both_empty = not candidate_present and not reference_present
        if both_empty:
            item["excluded_from_aggregates"] = "both_empty"
            skipped_both_empty += 1
        elif row["status"] == "matched" and candidate_present and reference_present:
            active_entries.append((row, item, "compared"))
            compared_rows.append(row)
        else:
            if row["status"] == "reference_only":
                zero_reason = "missing_system_unit"
            elif row["status"] == "candidate_only":
                zero_reason = "system_only_unit"
            elif not candidate_present:
                zero_reason = "empty_system_text"
            else:
                zero_reason = "empty_reference_text"
            item["zero_score_reason"] = zero_reason
            active_entries.append((row, item, "zero"))
            zero_items.append(item)
        items.append(item)
    if not active_entries:
        reason = "no_scorable_text"
        warnings = [*input_warnings, {
            "code": reason,
            "message": f"{MODE_NAMES[spec['mode']]}-level evaluation produced no scorable pairs",
        }]
        return {
            "mode": MODE_NAMES[spec["mode"]],
            "status": "skipped",
            "reason": reason,
            "warnings": warnings,
            "aggregation": aggregation,
            "n_scored": 0,
            "n_skipped_both_empty": skipped_both_empty,
            "items": items,
            "aggregates": {"macro": None, "micro": None},
            "overall": None,
            **({"diagnostics": diagnostics} if diagnostics is not None else {}),
        }

    refs = [row["reference"] for row in compared_rows]
    preds = [row["candidate"] for row in compared_rows]

    def token_count(text: str) -> int:
        return len(WS_RE.findall(text.strip())) + 1 if text.strip() else 0

    def weighted_mean(values: list[float], weights: list[int]) -> float:
        denominator = sum(weights)
        return (sum(value * weight for value, weight in zip(values, weights))
                / denominator if denominator else 0.0)

    def harmonic_f1(precision: float, recall: float) -> float:
        return (2 * precision * recall / (precision + recall)
                if precision + recall else 0.0)

    candidate_token_counts = [
        token_count(row["candidate"]) for row, _, _ in active_entries
    ]
    reference_token_counts = [
        token_count(row["reference"]) for row, _, _ in active_entries
    ]

    if name == "rouge":
        raw_results = [_SCORER.score(ref, pred) for pred, ref in zip(preds, refs)]
        compared_scores = [{
            rt: {
                "precision": round(result[rt].precision, 4),
                "recall": round(result[rt].recall, 4),
                "fmeasure": round(result[rt].fmeasure, 4),
            }
            for rt in ROUGE_TYPES
        } for result in raw_results]
        zero_score = {
            rt: {"precision": 0.0, "recall": 0.0, "fmeasure": 0.0}
            for rt in ROUGE_TYPES
        }
        compared_score_iter = iter(compared_scores)
        all_scores = []
        for _, item, score_kind in active_entries:
            score = next(compared_score_iter) if score_kind == "compared" else zero_score
            item["scores"] = score
            all_scores.append(score)
        macro = {
            rt: {flav: round(statistics.mean(score[rt][flav]
                                             for score in all_scores), 4)
                 for flav in ("precision", "recall", "fmeasure")}
            for rt in ROUGE_TYPES
        }
        micro = {}
        for rt in ROUGE_TYPES:
            counts = (diagnostics or {}).get(rt) or {}
            if rt == "rougeL":
                system_denominator = counts.get("system_tokens", 0)
                gold_denominator = counts.get("gold_tokens", 0)
                overlap = counts.get("total_lcs_length", 0)
            else:
                system_denominator = counts.get("system_ngrams", 0)
                gold_denominator = counts.get("gold_ngrams", 0)
                overlap = counts.get("overlapping_ngrams", 0)
            precision = overlap / system_denominator if system_denominator else 0.0
            recall = overlap / gold_denominator if gold_denominator else 0.0
            micro[rt] = {
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "fmeasure": round(harmonic_f1(precision, recall), 4),
            }
        for aggregate in (macro, micro):
            aggregate["denominator_policy"] = denominator_policy
    elif name == "bertscore":
        model_type = spec.get("model_type", "microsoft/deberta-xlarge-mnli")
        if compared_rows:
            kwargs = {
                "references": refs,
                "predictions": preds,
                "model_type": model_type,
                "batch_size": int(spec.get("batch_size", 1)),
            }
            _apply_bertscore_tokenizer_compat()
            result = _load_hf_metric("bertscore").compute(**kwargs)
        else:
            result = {"precision": [], "recall": [], "f1": []}
        compared_scores = [
            {k: round(float(result[k][i]), 6) for k in ("precision", "recall", "f1")}
            for i in range(len(compared_rows))
        ]
        zero_score = {"precision": 0.0, "recall": 0.0, "f1": 0.0}
        compared_score_iter = iter(compared_scores)
        all_scores = []
        for _, item, score_kind in active_entries:
            score = next(compared_score_iter) if score_kind == "compared" else zero_score
            item["scores"] = score
            all_scores.append(score)
        macro = {
            k: round(statistics.mean(score[k] for score in all_scores), 6)
            for k in ("precision", "recall", "f1")
        }
        precision = weighted_mean(
            [score["precision"] for score in all_scores], candidate_token_counts)
        recall = weighted_mean(
            [score["recall"] for score in all_scores], reference_token_counts)
        micro = {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(harmonic_f1(precision, recall), 6),
        }
        for aggregate in (macro, micro):
            aggregate["model_type"] = model_type
        if result.get("hashcode"):
            macro["hashcode"] = result["hashcode"]
            micro["hashcode"] = result["hashcode"]
    else:
        config_name = spec.get("config_name", "BLEURT-20")
        raw_scores = _score_bleurt(refs, preds, config_name) if compared_rows else []
        compared_scores = [round(value, 6) for value in raw_scores]
        compared_score_iter = iter(compared_scores)
        all_scores = []
        for _, item, score_kind in active_entries:
            score = next(compared_score_iter) if score_kind == "compared" else 0.0
            item["score"] = score
            all_scores.append(score)
        macro = {"score": round(statistics.mean(all_scores), 6),
                 "config_name": config_name}
        scalar_weights = [reference or candidate for reference, candidate
                          in zip(reference_token_counts, candidate_token_counts)]
        micro = {"score": round(weighted_mean(all_scores, scalar_weights), 6),
                 "config_name": config_name}

    aggregates = {"macro": macro, "micro": micro}
    return {
        "mode": MODE_NAMES[spec["mode"]],
        "status": "scored",
        "warnings": input_warnings,
        "aggregation": aggregation,
        "n_scored": len(active_entries),
        "n_compared": len(compared_rows),
        "n_zero_scored": len(zero_items),
        "n_skipped_both_empty": skipped_both_empty,
        "items": items,
        "aggregates": aggregates,
        "overall": aggregates[aggregation],
        **({"diagnostics": diagnostics} if diagnostics is not None else {}),
    }
def evaluate_configured_pair(
    candidate: Path,
    reference: Path,
    config_path: Path,
    evaluation_scope: EvaluationScope | None = None,
) -> dict:
    config = load_evaluation_config(config_path)
    scope = evaluation_scope or resolve_evaluation_scope(config_path)
    results = {}
    for name, spec in config.items():
        if spec["mode"] == 0:
            results[name] = {"mode": "disabled"}
            continue
        try:
            pairs = _configured_pairs(
                candidate, reference, spec, scope.section_ids,
            )
            results[name] = _score_configured_metric(name, pairs, spec)
        except (OSError, json.JSONDecodeError, TypeError, AttributeError) as exc:
            results[name] = {
                "mode": MODE_NAMES[spec["mode"]],
                "status": "skipped",
                "reason": "invalid_input_json",
                "error": str(exc),
                "warnings": [{
                    "code": "invalid_input_json",
                    "message": f"evaluation skipped because an input could not be parsed: {exc}",
                }],
                "n_scored": 0,
                "n_skipped_both_empty": 0,
                "aggregates": {"macro": None, "micro": None},
                "overall": None,
            }
    return {
        "candidate": str(candidate), "reference": str(reference),
        "config": str(config_path), "evaluation_scope": scope.as_dict(),
        "metrics": results,
    }


def evaluate_metric_pair(
    candidate: Path,
    reference: Path,
    metric_name: str,
    spec: dict,
    selected_sections: tuple[str, ...] | None = None,
) -> dict:
    """Score one configured text metric."""
    if spec["mode"] == 0:
        return {"mode": "disabled"}
    pairs = _configured_pairs(candidate, reference, spec, selected_sections)
    return _score_configured_metric(metric_name, pairs, spec)


METRICS_SUMMARY_HEADER = [
    "level", "model", "dataset", "candidate", "reference",
    "rouge_mode", "rouge_n_scored",
    "r1_p", "r1_r", "r1_f", "r2_p", "r2_r", "r2_f", "rl_p", "rl_r", "rl_f",
    "bertscore_mode", "bertscore_n_scored", "bertscore_precision",
    "bertscore_recall", "bertscore_f1",
    "bleurt_mode", "bleurt_n_scored", "bleurt",
    "rouge_aggregation", "rouge_n_skipped_both_empty",
    *[f"rouge_{aggregation}_{SHORT[metric]}_{flavour}"
      for aggregation in ("macro", "micro")
      for metric in ROUGE_TYPES for flavour in ("p", "r", "f")],
    "bertscore_aggregation", "bertscore_n_skipped_both_empty",
    *[f"bertscore_{aggregation}_{flavour}"
      for aggregation in ("macro", "micro")
      for flavour in ("precision", "recall", "f1")],
    "bleurt_aggregation", "bleurt_n_skipped_both_empty",
    "bleurt_macro", "bleurt_micro",
]


def _configured_summary_row(result: dict, name: dict) -> list:
    metrics = result["metrics"]
    rouge = metrics["rouge"]
    bert = metrics["bertscore"]
    bleurt = metrics["bleurt"]
    ro = rouge.get("overall") or {}
    bo = bert.get("overall") or {}
    blo = bleurt.get("overall") or {}
    rouge_aggregates = rouge.get("aggregates") or {}
    bert_aggregates = bert.get("aggregates") or {}
    bleurt_aggregates = bleurt.get("aggregates") or {}

    def rouge_value(metric: str, flavour: str):
        return (ro.get(metric) or {}).get(flavour, "")

    return [
        name.get("level", ""), name.get("model", ""), name.get("dataset", ""),
        Path(result["candidate"]).name, Path(result["reference"]).name,
        rouge.get("mode", ""), rouge.get("n_scored", ""),
        rouge_value("rouge1", "precision"), rouge_value("rouge1", "recall"),
        rouge_value("rouge1", "fmeasure"), rouge_value("rouge2", "precision"),
        rouge_value("rouge2", "recall"), rouge_value("rouge2", "fmeasure"),
        rouge_value("rougeL", "precision"), rouge_value("rougeL", "recall"),
        rouge_value("rougeL", "fmeasure"),
        bert.get("mode", ""), bert.get("n_scored", ""), bo.get("precision", ""),
        bo.get("recall", ""), bo.get("f1", ""),
        bleurt.get("mode", ""), bleurt.get("n_scored", ""), blo.get("score", ""),
        rouge.get("aggregation", ""), rouge.get("n_skipped_both_empty", ""),
        *[
            ((rouge_aggregates.get(aggregation) or {}).get(metric) or {}).get(
                {"p": "precision", "r": "recall", "f": "fmeasure"}[flavour], ""
            )
            for aggregation in ("macro", "micro")
            for metric in ROUGE_TYPES for flavour in ("p", "r", "f")
        ],
        bert.get("aggregation", ""), bert.get("n_skipped_both_empty", ""),
        *[
            (bert_aggregates.get(aggregation) or {}).get(flavour, "")
            for aggregation in ("macro", "micro")
            for flavour in ("precision", "recall", "f1")
        ],
        bleurt.get("aggregation", ""), bleurt.get("n_skipped_both_empty", ""),
        (bleurt_aggregates.get("macro") or {}).get("score", ""),
        (bleurt_aggregates.get("micro") or {}).get("score", ""),
    ]


def configured_metrics_tree(run_dir: Path, config_path: Path, quiet: bool = False) -> int:
    """Evaluate the standalone compatibility tree layout and write summaries."""
    if not run_dir.is_dir():
        sys.exit(f"[evaluate] tree directory not found: {run_dir}")
    rows = []
    count = 0
    for sub in sorted(path for path in run_dir.iterdir() if path.is_dir()):
        for candidate in sorted(sub.glob("*__sitrep.json")):
            doc = json.loads(candidate.read_text(encoding="utf-8"))
            name = parse_name(candidate)
            dataset = name["dataset"] or detect_dataset(doc, candidate)
            if dataset not in GOLD_FILES:
                sys.exit(f"[evaluate] could not resolve gold dataset for {candidate}")
            name["dataset"] = dataset
            reference = GOLD_DIR / GOLD_FILES[dataset]
            result = evaluate_configured_pair(candidate, reference, config_path)
            result["meta"] = name

            out = sub / "metrics" / f"{candidate.stem}__metrics.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            rows.append(_configured_summary_row(result, name))
            count += 1
            if not quiet:
                enabled = [metric for metric, value in result["metrics"].items()
                           if value.get("mode") != "disabled"]
                print(f"  {name['level']}/{name['model']}/{dataset}: {', '.join(enabled)} -> {out}")

    if not rows:
        print(f"[evaluate] no *__sitrep.json found under immediate children of {run_dir}")
        return 0
    summary = run_dir / "metrics_summary.csv"
    with summary.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(METRICS_SUMMARY_HEADER)
        writer.writerows(rows)
    print(f"[evaluate] evaluated {count} sitreps")
    print(f"[evaluate] wrote {summary}")
    return 0


def load_as_sections(path: Path) -> tuple[dict[str, dict], str]:
    """Load section text for standalone JSON or Markdown comparison."""
    suffix = path.suffix.lower()
    if suffix in (".json", ".jsn"):
        kind = "json"
    elif suffix in (".md", ".markdown", ".txt"):
        kind = "md"
    else:
        head = path.read_text(encoding="utf-8").lstrip()[:1]
        kind = "json" if head in "{[" else "md"

    if kind == "json":
        doc = json.loads(path.read_text(encoding="utf-8"))
        secs = parse_ours(doc)
        return ({sid: {"title": v["title"], "text": v["text"]}
                 for sid, v in secs.items()}, "json")

    gold = parse_gold(path)
    out: dict[str, dict] = {}
    for sid, aliases in SECTION_MAP.items():
        for hkey, sec in gold.items():
            if any(a in hkey for a in aliases):
                out[sid] = {"title": sec["header"], "text": sec["text"]}
                break
    return out, "md"


def compare_pair(cand: dict[str, dict], ref: dict[str, dict]) -> dict:
    """Align sections by ID for standalone ROUGE reporting."""
    sections = []
    for sid in sorted(set(cand) | set(ref), key=lambda x: (len(x), x)):
        c = cand.get(sid)
        r = ref.get(sid)
        c_text = c["text"] if c else ""
        r_text = r["text"] if r else ""
        if c and r:
            status = "matched"
            scores = score_pair(c_text, r_text)
        elif c:
            status = "candidate_only"
            scores = None
        else:
            status = "reference_only"
            scores = None
        sections.append({
            "section_id": sid,
            "title": (c or r or {}).get("title", ""),
            "status": status,
            "cand_chars": len(c_text),
            "ref_chars": len(r_text),
            "scores": scores,
        })

    overall = {}
    for rt in ROUGE_TYPES:
        for flav in ("precision", "recall", "fmeasure"):
            vals = [s["scores"][rt][flav] for s in sections if s["scores"]]
            overall.setdefault(rt, {})[flav] = (
                round(statistics.mean(vals), 4) if vals else None)
    return {
        "n_matched": sum(1 for s in sections if s["scores"]),
        "sections": sections,
        "overall": overall,
    }


def print_pair_report(result: dict, cand_path: Path, ref_path: Path) -> None:
    print(f"\nCANDIDATE : {cand_path.name}")
    print(f"REFERENCE : {ref_path.name}")
    print(f"matched sections: {result['n_matched']}\n")
    hdr = f"{'sec':>4}  {'status':<15} {'R1-f':>6} {'R2-f':>6} {'RL-f':>6}  {'R1-rec':>6} {'R1-prc':>6}"
    print(hdr)
    print("-" * len(hdr))
    for s in result["sections"]:
        if s["scores"]:
            r1, r2, rl = s["scores"]["rouge1"], s["scores"]["rouge2"], s["scores"]["rougeL"]
            print(f"{s['section_id']:>4}  {s['status']:<15} "
                  f"{r1['fmeasure']:>6.3f} {r2['fmeasure']:>6.3f} {rl['fmeasure']:>6.3f}  "
                  f"{r1['recall']:>6.3f} {r1['precision']:>6.3f}")
        else:
            print(f"{s['section_id']:>4}  {s['status']:<15} {'-':>6} {'-':>6} {'-':>6}  {'-':>6} {'-':>6}")
    o = result["overall"]

    def g(rt, fl):
        v = o[rt][fl]
        return "   n/a" if v is None else f"{v:6.3f}"
    print("-" * len(hdr))
    print(f"{'ALL':>4}  {'mean(matched)':<15} "
          f"{g('rouge1','fmeasure')} {g('rouge2','fmeasure')} {g('rougeL','fmeasure')}  "
          f"{g('rouge1','recall')} {g('rouge1','precision')}")
    print()


def write_pair_csv(result: dict, path: Path, cand_name: str, ref_name: str) -> None:
    header = (["candidate", "reference", "section_id", "title", "status",
               "cand_chars", "ref_chars"]
              + [f"{SHORT[rt]}_{fl}" for rt in ROUGE_TYPES for fl in ("p", "r", "f")])
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for s in result["sections"]:
            row = [cand_name, ref_name, s["section_id"], s["title"], s["status"],
                   s["cand_chars"], s["ref_chars"]]
            if s["scores"]:
                for rt in ROUGE_TYPES:
                    sc = s["scores"][rt]
                    row += [sc["precision"], sc["recall"], sc["fmeasure"]]
            else:
                row += [""] * 9
            w.writerow(row)
        o = result["overall"]
        orow = [cand_name, ref_name, "ALL", "mean(matched)", "overall", "", ""]
        for rt in ROUGE_TYPES:
            orow += [o[rt]["precision"], o[rt]["recall"], o[rt]["fmeasure"]]
        w.writerow(orow)
    print(f"[evaluate] wrote {path}")


def _match_gold(aliases: list[str], gold: dict[str, dict]) -> dict | None:
    for key, sec in gold.items():
        for alias in aliases:
            if alias in key:
                return sec
    return None


def align(doc: dict, gold: dict[str, dict], meta_extra: dict) -> dict:
    ours = parse_ours(doc)
    pairs = []
    used_gold_headers: set[str] = set()

    for sid, aliases in SECTION_MAP.items():
        oursec = ours.get(sid)
        gmatch = _match_gold(aliases, gold)
        if gmatch:
            used_gold_headers.add(gmatch["header"].strip().lower())
        our_text = oursec["text"] if oursec else ""
        our_title = oursec["title"] if oursec else ""
        gold_text = gmatch["text"] if gmatch else ""
        if oursec is None and gmatch is None:
            status = "absent_both"
        elif gmatch is None:
            status = "no_gold"
        elif oursec is None:
            status = "missing_ours"
        else:
            status = "matched"
        pairs.append({
            "section_id": sid,
            "our_title": our_title,
            "gold_header": gmatch["header"] if gmatch else None,
            "status": status,
            "our_text": our_text,
            "gold_text": gold_text,
            "our_units": oursec["units"] if oursec else [],
            "gold_units": gmatch["units"] if gmatch else [],
            "our_chars": len(our_text),
            "gold_chars": len(gold_text),
        })

    gold_unmatched = [
        sec["header"] for key, sec in gold.items()
        if key not in used_gold_headers
    ]
    return {
        "meta": meta_extra,
        "pairs": pairs,
        "gold_unmatched": gold_unmatched,
        "supplementary_our_sections": sorted(SUPPLEMENTARY),
    }


def alignment_to_markdown(alignment: dict) -> str:
    """Render a standalone section-alignment report as Markdown."""
    m = alignment["meta"]
    lines = [
        f"# Alignment: {m.get('our_file', '')}",
        "",
        f"- gold: `{m.get('gold_file', '')}`",
        f"- dataset: {m.get('dataset', '')}  |  level: {m.get('level', '')}  "
        f"|  model: {m.get('model', '')}",
        "",
    ]
    for p in alignment["pairs"]:
        lines.append(f"## §{p['section_id']} {p['our_title']}  "
                     f"[{p['status']}]  (gold: {p['gold_header']})")
        lines.append("")
        lines.append(f"**ours ({p['our_chars']} chars):** {p['our_text'] or '_(empty)_'}")
        lines.append("")
        lines.append(f"**gold ({p['gold_chars']} chars):** {p['gold_text'] or '_(empty)_'}")
        lines.append("")
    if alignment["gold_unmatched"]:
        lines.append(f"> gold sections not mapped: {alignment['gold_unmatched']}")
    return "\n".join(lines) + "\n"


def score_alignment(alignment: dict) -> dict:
    """Score matched pairs from a standalone section alignment with ROUGE."""
    sections = []
    for p in alignment["pairs"]:
        row = {
            "section_id": p["section_id"],
            "our_title": p["our_title"],
            "gold_header": p["gold_header"],
            "status": p["status"],
            "our_chars": p["our_chars"],
            "gold_chars": p["gold_chars"],
        }
        if p["status"] == "matched":
            row["scores"] = score_pair(p["our_text"], p["gold_text"])
        else:
            row["scores"] = None
        sections.append(row)

    overall = {}
    for rt in ROUGE_TYPES:
        for flav in ("precision", "recall", "fmeasure"):
            vals = [s["scores"][rt][flav] for s in sections if s["scores"]]
            overall.setdefault(rt, {})[flav] = (
                round(statistics.mean(vals), 4) if vals else None
            )
    return {
        "meta": alignment["meta"],
        "n_matched": sum(1 for s in sections if s["scores"]),
        "sections": sections,
        "overall": overall,
    }


def parse_name(json_path: Path) -> dict:
    """Parse metadata from a standalone compatibility-tree filename."""
    m = re.match(r"^([A-E])__(.+?)__(.+?)__sitrep\.json$", json_path.name)
    if m:
        return {"level": m.group(1), "model": m.group(2), "dataset": m.group(3)}
    return {"level": "", "model": "", "dataset": ""}


def detect_dataset(doc: dict, json_path: Path) -> str | None:
    ds = (doc.get("meta") or {}).get("dataset")
    if ds in GOLD_FILES:
        return ds
    for cand in GOLD_FILES:
        if cand in json_path.name:
            return cand
    return None


def align_and_score_one(json_path: Path, align_json: Path, align_md: Path,
                        rouge_json: Path) -> dict:
    """Run standalone Markdown-reference alignment and write ROUGE outputs."""
    doc = json.loads(json_path.read_text(encoding="utf-8"))
    name = parse_name(json_path)
    dataset = name["dataset"] or detect_dataset(doc, json_path)
    gold_path = GOLD_DIR / GOLD_FILES[dataset] if dataset in GOLD_FILES else None
    if gold_path is None or not gold_path.exists():
        sys.exit(f"[evaluate] gold not found for dataset={dataset!r} "
                 f"(looked for {gold_path})")
    gold = parse_gold(gold_path)
    meta_extra = {
        "our_file": json_path.name,
        "gold_file": gold_path.name,
        "dataset": dataset,
        "level": name["level"],
        "model": name["model"],
    }
    alignment = align(doc, gold, meta_extra)
    align_json.parent.mkdir(parents=True, exist_ok=True)
    align_json.write_text(json.dumps(alignment, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    align_md.write_text(alignment_to_markdown(alignment), encoding="utf-8")

    scored = score_alignment(alignment)
    rouge_json.parent.mkdir(parents=True, exist_ok=True)
    rouge_json.write_text(json.dumps(scored, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    return scored


ROUGE_CSV_HEADER = (
    ["level", "model", "dataset", "section_id", "our_title", "gold_header",
     "status", "our_chars", "gold_chars"]
    + [f"{SHORT[rt]}_{flav}" for rt in ROUGE_TYPES for flav in ("p", "r", "f")]
)


def _rouge_csv_rows(scored: dict) -> list[list]:
    m = scored["meta"]
    rows = []
    for s in scored["sections"]:
        base = [m.get("level"), m.get("model"), m.get("dataset"),
                s["section_id"], s["our_title"], s["gold_header"],
                s["status"], s["our_chars"], s["gold_chars"]]
        if s["scores"]:
            for rt in ROUGE_TYPES:
                sc = s["scores"][rt]
                base += [sc["precision"], sc["recall"], sc["fmeasure"]]
        else:
            base += [""] * 9
        rows.append(base)
    return rows


def _rouge_summary_line(scored: dict) -> str:
    m = scored["meta"]
    o = scored["overall"]
    tag = f"{m.get('level')}/{m.get('model')}/{m.get('dataset')}"

    def g(rt):
        v = o[rt]["fmeasure"]
        return "  n/a" if v is None else f"{v:.3f}"
    return (f"  {tag:42} matched={scored['n_matched']:>2}  "
            f"R1f={g('rouge1')}  R2f={g('rouge2')}  RLf={g('rougeL')}")


def rouge_tree(run_dir: Path) -> int:
    all_rows: list[list] = []
    summaries: list[dict] = []
    for sub in sorted(s for s in run_dir.iterdir() if s.is_dir()):
        for jf in sorted(sub.glob("*__sitrep.json")):
            stem = jf.stem
            scored = align_and_score_one(
                jf,
                sub / "align" / (stem + "__align.json"),
                sub / "align" / (stem + "__align.md"),
                sub / "rouge" / (stem + "__rouge.json"),
            )
            all_rows.extend(_rouge_csv_rows(scored))
            summaries.append(scored)
            print(_rouge_summary_line(scored))
    if not summaries:
        print(f"[evaluate] no *__sitrep.json found under {run_dir}")
        return 0
    csv_path = run_dir / "rouge_scores.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(ROUGE_CSV_HEADER)
        w.writerows(all_rows)
    sum_path = run_dir / "rouge_summary.csv"
    with sum_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["level", "model", "dataset", "n_matched",
                    "r1_f", "r2_f", "rl_f",
                    "r1_r", "r2_r", "rl_r", "r1_p", "r2_p", "rl_p"])
        for sc in summaries:
            m, o = sc["meta"], sc["overall"]
            w.writerow([
                m.get("level"), m.get("model"), m.get("dataset"), sc["n_matched"],
                o["rouge1"]["fmeasure"], o["rouge2"]["fmeasure"], o["rougeL"]["fmeasure"],
                o["rouge1"]["recall"], o["rouge2"]["recall"], o["rougeL"]["recall"],
                o["rouge1"]["precision"], o["rouge2"]["precision"], o["rougeL"]["precision"],
            ])
    print(f"\n[evaluate] wrote {csv_path}")
    print(f"[evaluate] wrote {sum_path}")
    return 0


def cmd_rouge(args: argparse.Namespace) -> int:
    if args.tree:
        return rouge_tree(args.tree)
    if not (args.candidate and args.reference):
        sys.exit("[evaluate] rouge needs CANDIDATE and REFERENCE, or --tree DIR")
    for f in (args.candidate, args.reference):
        if not f.exists():
            sys.exit(f"[evaluate] file not found: {f}")
    cand, _ = load_as_sections(args.candidate)
    ref, _ = load_as_sections(args.reference)
    result = compare_pair(cand, ref)
    if not args.quiet:
        print_pair_report(result, args.candidate, args.reference)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        payload = {"candidate": args.candidate.name,
                   "reference": args.reference.name, **result}
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"[evaluate] wrote {args.out}")
    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        write_pair_csv(result, args.csv, args.candidate.name, args.reference.name)
    if result["n_matched"] == 0:
        print("[evaluate] WARNING: no sections matched between the two files - "
              "check they use the same section ids / schema.", file=sys.stderr)
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    if args.tree:
        if args.candidate or args.reference:
            sys.exit("[evaluate] metrics accepts either CANDIDATE REFERENCE or --tree DIR")
        return configured_metrics_tree(args.tree, args.config, args.quiet)
    if not (args.candidate and args.reference):
        sys.exit("[evaluate] metrics needs CANDIDATE and REFERENCE, or --tree DIR")
    for path in (args.candidate, args.reference):
        if not path.exists():
            sys.exit(f"[evaluate] file not found: {path}")
    result = evaluate_configured_pair(args.candidate, args.reference, args.config)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
        print(f"[evaluate] wrote {args.out}")
    if not args.quiet:
        print(rendered)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Standalone text-level SITREP evaluation utilities.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("rouge", help="ROUGE-1/2/L word-overlap scoring.")
    r.add_argument("candidate", nargs="?", type=Path,
                   help="System SITREP (.json or .md). Omit with --tree.")
    r.add_argument("reference", nargs="?", type=Path,
                   help="Reference SITREP (.json or .md). Omit with --tree.")
    r.add_argument("--tree", type=Path, default=None,
                   help="Standalone compatibility-tree directory: align each "
                        "*__sitrep.json file and write alignment and ROUGE reports.")
    r.add_argument("--out", type=Path, default=None,
                   help="Single-pair mode: write the full per-section result JSON here.")
    r.add_argument("--csv", type=Path, default=None,
                   help="Single-pair mode: write a per-section CSV here.")
    r.add_argument("--quiet", action="store_true",
                   help="Single-pair mode: suppress the printed table.")
    r.set_defaults(func=cmd_rouge)

    m = sub.add_parser(
        "metrics", help="Run enabled ROUGE/BERTScore/BLEURT metrics from evaluation.yaml.")
    m.add_argument("candidate", nargs="?", type=Path,
                   help="System SITREP (.json or .md). Omit with --tree.")
    m.add_argument("reference", nargs="?", type=Path,
                   help="Gold or reference SITREP (.json or .md). Omit with --tree.")
    m.add_argument("--tree", type=Path, default=None,
                   help="Standalone compatibility-tree directory whose immediate "
                        "children contain *__sitrep.json files.")
    m.add_argument("--config", type=Path, default=DEFAULT_EVAL_CONFIG,
                   help=f"Metric policy (default: {DEFAULT_EVAL_CONFIG}).")
    m.add_argument("--out", type=Path, default=None,
                   help="Single-pair mode: write result JSON here.")
    m.add_argument("--quiet", action="store_true",
                   help="Suppress per-file output (summary paths are still printed).")
    m.set_defaults(func=cmd_metrics)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
