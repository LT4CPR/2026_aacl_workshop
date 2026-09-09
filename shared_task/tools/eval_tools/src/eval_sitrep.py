"""Compute configured text-level metrics for SITREP reports."""
from __future__ import annotations

import importlib
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

from evaluation_scope import EvaluationScope, resolve_evaluation_scope
from runtime_env import apply_safe_hf_env
from subsection_alignment import (
    DEFAULT_SUBSECTION_ALIGNMENT_METHOD,
    display_subsection_alignment_key,
    resolve_subsection_alignment_method,
    subsection_alignment_key,
)

apply_safe_hf_env()

try:
    from rouge_score import rouge_scorer
except ImportError:
    sys.exit("[evaluate] missing dependency. Run:\n"
             "    pip install -r requirements.txt   (or: pip install rouge-score)")

SCRIPT_DIR = Path(__file__).resolve().parent
RELEASE_ROOT = SCRIPT_DIR.parent

ROUGE_TYPES = ["rouge1", "rouge2", "rougeL"]
_SCORER = rouge_scorer.RougeScorer(ROUGE_TYPES, use_stemmer=True)

WS_RE = re.compile(r"\s+")


METRIC_NAMES = ("rouge", "bertscore", "bleurt")
MODE_NAMES = {0: "disabled", 1: "document", 2: "section", 3: "subsection"}
DEFAULT_EVAL_CONFIG = RELEASE_ROOT / "config" / "evaluation.yaml"
_HF_METRICS: dict[tuple[str, str | None], object] = {}


def resolve_text_level_block(metrics: dict) -> dict:
    """Return text-level metric settings."""
    text_level = metrics.get("text_level")
    if not isinstance(text_level, dict):
        sys.exit("[evaluate] invalid config: metrics.text_level must be a mapping")
    return text_level


def resolve_bullet_level_spec(metrics: dict) -> dict | None:
    """Return bullet-level settings."""
    spec = metrics.get("bullet_level")
    return dict(spec) if isinstance(spec, dict) else None


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
    try:
        subsection_alignment_method = resolve_subsection_alignment_method(raw)
    except ValueError as exc:
        sys.exit(f"[evaluate] invalid config: {exc}")
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
        result[name] = {
            **spec,
            "mode": mode,
            "aggregation": aggregation,
            "denominator_policy": denominator_policy,
            "include_section_headers": bool(spec.get("include_section_headers", False)),
            "include_subsection_headers": bool(spec.get("include_subsection_headers", False)),
            "subsection_alignment_method": subsection_alignment_method,
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
    matched_rows = [row for row in pairs if row["status"] == "matched"]
    scored_rows = [
        row for row in matched_rows
        if row["candidate"].strip() or row["reference"].strip()
    ]
    gold_rows = [
        row for row in pairs
        if row["status"] in {"matched", "reference_only"} and row["reference"].strip()
    ]
    skipped_both_empty = sum(
        1 for row in matched_rows
        if not row["candidate"].strip() and not row["reference"].strip()
    )
    diagnostics = {
        "gold_units": sum(1 for row in pairs if row["status"] in {"matched", "reference_only"}),
        "system_units": sum(1 for row in pairs if row["status"] in {"matched", "candidate_only"}),
        "matched_units": len(matched_rows),
        "scored_units": len(scored_rows),
        "skipped_both_empty_units": skipped_both_empty,
        "denominator": denominator_policy,
        "denominator_policy": denominator_policy,
        "rouge1": {
            "gold_ngrams": 0,
            "matched_gold_ngrams": 0,
            "whole_gold_ngrams": 0,
            "system_ngrams": 0,
            "overlapping_ngrams": 0,
        },
        "rouge2": {
            "gold_ngrams": 0,
            "matched_gold_ngrams": 0,
            "whole_gold_ngrams": 0,
            "system_ngrams": 0,
            "overlapping_ngrams": 0,
        },
        "rougeL": {
            "gold_tokens": 0,
            "matched_gold_tokens": 0,
            "whole_gold_tokens": 0,
            "system_tokens": 0,
            "total_lcs_length": 0,
        },
    }
    for row in gold_rows:
        gold_tokens = _tokenize_for_rouge(row["reference"])
        for n, key in ((1, "rouge1"), (2, "rouge2")):
            diagnostics[key]["whole_gold_ngrams"] += sum(
                _ngram_counter(gold_tokens, n).values()
            )
        diagnostics["rougeL"]["whole_gold_tokens"] += len(gold_tokens)
    for row in scored_rows:
        system_tokens = _tokenize_for_rouge(row["candidate"])
        gold_tokens = _tokenize_for_rouge(row["reference"])
        for n, key in ((1, "rouge1"), (2, "rouge2")):
            gold_ngrams = _ngram_counter(gold_tokens, n)
            system_ngrams = _ngram_counter(system_tokens, n)
            diagnostics[key]["matched_gold_ngrams"] += sum(gold_ngrams.values())
            diagnostics[key]["system_ngrams"] += sum(system_ngrams.values())
            diagnostics[key]["overlapping_ngrams"] += sum(
                (gold_ngrams & system_ngrams).values()
            )
        diagnostics["rougeL"]["matched_gold_tokens"] += len(gold_tokens)
        diagnostics["rougeL"]["system_tokens"] += len(system_tokens)
        diagnostics["rougeL"]["total_lcs_length"] += _lcs_length(gold_tokens, system_tokens)
    for key in ("rouge1", "rouge2"):
        denominator_key = (
            "whole_gold_ngrams" if denominator_policy == "whole_gold"
            else "matched_gold_ngrams"
        )
        diagnostics[key]["gold_ngrams"] = diagnostics[key][denominator_key]
    rouge_l_denominator_key = (
        "whole_gold_tokens" if denominator_policy == "whole_gold"
        else "matched_gold_tokens"
    )
    diagnostics["rougeL"]["gold_tokens"] = diagnostics["rougeL"][rouge_l_denominator_key]
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


def _metric_hierarchy(
    path: Path,
    subsection_alignment_method: str = DEFAULT_SUBSECTION_ALIGNMENT_METHOD,
) -> dict[str, object]:
    """Load structured report JSON and report available evaluation levels."""
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
            subtitle = str(sub.get("title", "")).strip()
            texts = _container_bullet_text(sub)
            all_section_text.extend(texts)
            if sid:
                try:
                    alignment_key = subsection_alignment_key(
                        subid,
                        subtitle,
                        subsection_alignment_method,
                    )
                except ValueError as exc:
                    raise ValueError(
                        f"subsection at section {sid}, index {sub_index}: {exc}"
                    ) from exc
                if alignment_key in subsections:
                    raise ValueError(
                        "duplicate subsection alignment key within section "
                        f"{sid!r}: {alignment_key!r}"
                    )
                subsections[alignment_key] = {
                    "id": subid,
                    "title": subtitle,
                    "alignment_key": alignment_key,
                    "text": " ".join(texts).strip(),
                }
            elif texts:
                section_only_text.extend(texts)
                warnings.append({
                    "code": "missing_section_id",
                    "message": "subsection text is usable only at document level because its section id is missing",
                })
        if not sid:
            orphan_text.extend(all_section_text)
            if all_section_text:
                warnings.append({
                    "code": "missing_section_id",
                    "message": "section text is usable only at document level because its id is missing",
                })
            continue
        out[sid] = {
            "title": sec.get("title", ""),
            "own_text": " ".join(section_only_text).strip(),
            "subsections": subsections,
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


def _render_section(sec: dict, include_subsection_headers: bool) -> str:
    parts = [sec.get("own_text", "")]
    for sub in sec.get("subsections", {}).values():
        if include_subsection_headers and sub.get("title"):
            parts.append(sub["title"])
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
    mode = spec["mode"]
    subsection_alignment_method = str(
        spec.get(
            "subsection_alignment_method",
            DEFAULT_SUBSECTION_ALIGNMENT_METHOD,
        )
    )
    hierarchy_alignment_method = (
        subsection_alignment_method if mode == 3 else "id_only"
    )
    cand_doc = _filter_metric_hierarchy(
        _metric_hierarchy(candidate, hierarchy_alignment_method),
        selected_sections,
    )
    ref_doc = _filter_metric_hierarchy(
        _metric_hierarchy(reference, hierarchy_alignment_method),
        selected_sections,
    )
    cand = cand_doc["sections"]
    ref = ref_doc["sections"]
    sec_headers = spec["include_section_headers"]
    sub_headers = spec["include_subsection_headers"]
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
                if sec_headers and sec.get("title"):
                    parts.append(sec["title"])
                parts.append(_render_section(sec, sub_headers))
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
            ctext = _render_section(csec, sub_headers) if csec else ""
            rtext = _render_section(rsec, sub_headers) if rsec else ""
            if sec_headers:
                ctext = " ".join(p for p in ((csec or {}).get("title", ""), ctext) if p)
                rtext = " ".join(p for p in ((rsec or {}).get("title", ""), rtext) if p)
            rows.append({"unit_id": f"section:{sid}", "status": status,
                         "candidate": ctext, "reference": rtext})
        if rows:
            rows[0]["input_warnings"] = input_warnings
        return rows

    rows = []
    for sid in sorted(set(cand) | set(ref), key=lambda x: (len(x), x)):
        csubs = (cand.get(sid) or {}).get("subsections", {})
        rsubs = (ref.get(sid) or {}).get("subsections", {})
        for alignment_key in sorted(set(csubs) | set(rsubs)):
            csub, rsub = csubs.get(alignment_key), rsubs.get(alignment_key)
            status = "matched" if csub and rsub else ("candidate_only" if csub else "reference_only")
            ctext, rtext = (csub or {}).get("text", ""), (rsub or {}).get("text", "")
            if sub_headers:
                ctext = " ".join(p for p in ((csub or {}).get("title", ""), ctext) if p)
                rtext = " ".join(p for p in ((rsub or {}).get("title", ""), rtext) if p)
            if sec_headers:
                ctext = " ".join(p for p in ((cand.get(sid) or {}).get("title", ""), ctext) if p)
                rtext = " ".join(p for p in ((ref.get(sid) or {}).get("title", ""), rtext) if p)
            displayed_key = display_subsection_alignment_key(
                alignment_key,
                subsection_alignment_method,
            )
            rows.append({
                "unit_id": f"subsection:{sid}/{displayed_key}",
                "status": status,
                "candidate": ctext,
                "reference": rtext,
                "subsection_alignment_method": subsection_alignment_method,
                "subsection_alignment_key": displayed_key,
                "candidate_subsection_id": (csub or {}).get("id"),
                "reference_subsection_id": (rsub or {}).get("id"),
                "candidate_subsection_header": (csub or {}).get("title"),
                "reference_subsection_header": (rsub or {}).get("title"),
            })
    if rows:
        rows[0]["input_warnings"] = input_warnings
    return rows


def _load_hf_evaluate_library():
    """Import HuggingFace evaluate without local-module shadowing."""

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
    """Cap tokenizer lengths that break bert-score."""

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
    """Return an extracted BLEURT checkpoint from the HuggingFace metric cache."""

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
    matched = [
        row for row in pairs
        if row["status"] == "matched"
        and (row["candidate"].strip() or row["reference"].strip())
    ]
    candidate_only = [
        row for row in pairs
        if row["status"] == "candidate_only" and row["candidate"].strip()
    ]
    reference_only = [
        row for row in pairs
        if row["status"] == "reference_only" and row["reference"].strip()
    ]
    refs = [row["reference"] for row in matched]
    preds = [row["candidate"] for row in matched]
    items = []
    score_items = []
    skipped_both_empty = 0
    for row in pairs:
        item = {"unit_id": row["unit_id"], "status": row["status"]}
        for field in (
            "subsection_alignment_method",
            "subsection_alignment_key",
            "candidate_subsection_id",
            "reference_subsection_id",
            "candidate_subsection_header",
            "reference_subsection_header",
        ):
            if field in row:
                item[field] = row[field]
        both_empty = (
            row["status"] == "matched"
            and not row["candidate"].strip()
            and not row["reference"].strip()
        )
        if both_empty:
            item["excluded_from_aggregates"] = "both_empty"
            skipped_both_empty += 1
        elif row["status"] == "matched":
            score_items.append(item)
        items.append(item)
    bertscore_has_unmatched_content = (
        name == "bertscore" and bool(candidate_only or reference_only)
    )
    if not matched and not bertscore_has_unmatched_content:
        reason = (
            "no_scorable_text"
            if any(row.get("status") == "matched" for row in pairs)
            else f"no_shared_{MODE_NAMES[spec['mode']]}_groups"
        )
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

    def token_count(text: str) -> int:
        return len(WS_RE.findall(text.strip())) + 1 if text.strip() else 0

    def weighted_mean(values: list[float], weights: list[int]) -> float:
        denominator = sum(weights)
        return (sum(value * weight for value, weight in zip(values, weights))
                / denominator if denominator else 0.0)

    def harmonic_f1(precision: float, recall: float) -> float:
        return (2 * precision * recall / (precision + recall)
                if precision + recall else 0.0)

    candidate_token_counts = [token_count(text) for text in preds]
    reference_token_counts = [token_count(text) for text in refs]

    if name == "rouge":
        raw_results = [_SCORER.score(ref, pred) for pred, ref in zip(preds, refs)]
        rouge_candidate_counts = [len(_SCORER._tokenizer.tokenize(text))
                                  for text in preds]
        rouge_reference_counts = [len(_SCORER._tokenizer.tokenize(text))
                                  for text in refs]
        scores = [{
            rt: {
                "precision": round(result[rt].precision, 4),
                "recall": round(result[rt].recall, 4),
                "fmeasure": round(result[rt].fmeasure, 4),
            }
            for rt in ROUGE_TYPES
        } for result in raw_results]
        for item, score in zip(score_items, scores):
            item["scores"] = score
        macro = {
            rt: {flav: round(statistics.mean(getattr(result[rt], flav)
                                             for result in raw_results), 4)
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
        if matched:
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
        scores = [{k: round(float(result[k][i]), 6) for k in ("precision", "recall", "f1")}
                  for i in range(len(matched))]
        for item, score in zip(score_items, scores):
            item["scores"] = score

        candidate_only_token_counts = [
            token_count(row["candidate"]) for row in candidate_only
        ]
        reference_only_token_counts = [
            token_count(row["reference"]) for row in reference_only
        ]

        macro_precision_denominator = len(matched) + len(candidate_only)
        macro_recall_denominator = len(matched) + len(reference_only)
        macro_precision = (
            sum(float(value) for value in result["precision"])
            / macro_precision_denominator
            if macro_precision_denominator else 0.0
        )
        macro_recall = (
            sum(float(value) for value in result["recall"])
            / macro_recall_denominator
            if macro_recall_denominator else 0.0
        )
        macro = {
            "precision": round(macro_precision, 6),
            "recall": round(macro_recall, 6),
            "f1": round(harmonic_f1(macro_precision, macro_recall), 6),
        }

        precision_denominator = (
            sum(candidate_token_counts) + sum(candidate_only_token_counts)
        )
        recall_denominator = (
            sum(reference_token_counts) + sum(reference_only_token_counts)
        )
        precision_numerator = sum(
            float(value) * weight
            for value, weight in zip(result["precision"], candidate_token_counts)
        )
        recall_numerator = sum(
            float(value) * weight
            for value, weight in zip(result["recall"], reference_token_counts)
        )
        precision = (
            precision_numerator / precision_denominator
            if precision_denominator else 0.0
        )
        recall = (
            recall_numerator / recall_denominator
            if recall_denominator else 0.0
        )
        micro = {
            "precision": round(precision, 6),
            "recall": round(recall, 6),
            "f1": round(harmonic_f1(precision, recall), 6),
        }
        for aggregate in (macro, micro):
            aggregate["model_type"] = model_type
            aggregate["unmatched_policy"] = "side_specific_zero"
        if result.get("hashcode"):
            macro["hashcode"] = result["hashcode"]
            micro["hashcode"] = result["hashcode"]
        bertscore_penalty = {
            "policy": "side_specific_zero",
            "matched_system_token_weight": sum(candidate_token_counts),
            "system_only_units": len(candidate_only),
            "system_only_token_weight": sum(candidate_only_token_counts),
            "precision_denominator_token_weight": precision_denominator,
            "matched_gold_token_weight": sum(reference_token_counts),
            "gold_only_units": len(reference_only),
            "gold_only_token_weight": sum(reference_only_token_counts),
            "recall_denominator_token_weight": recall_denominator,
        }
    else:
        config_name = spec.get("config_name", "BLEURT-20")
        raw_scores = _score_bleurt(refs, preds, config_name)
        scores = [round(value, 6) for value in raw_scores]
        for item, score in zip(score_items, scores):
            item["score"] = score
        macro = {"score": round(statistics.mean(raw_scores), 6),
                 "config_name": config_name}
        scalar_weights = [reference or candidate for reference, candidate
                          in zip(reference_token_counts, candidate_token_counts)]
        micro = {"score": round(weighted_mean(raw_scores, scalar_weights), 6),
                 "config_name": config_name}

    aggregates = {"macro": macro, "micro": micro}
    return {
        "mode": MODE_NAMES[spec["mode"]],
        "status": "scored",
        "warnings": input_warnings,
        "aggregation": aggregation,
        "n_scored": len(matched),
        "n_skipped_both_empty": skipped_both_empty,
        "items": items,
        "aggregates": aggregates,
        "overall": aggregates[aggregation],
        **({"diagnostics": diagnostics} if diagnostics is not None else {}),
        **({"unmatched_penalty": bertscore_penalty} if name == "bertscore" else {}),
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
            if spec["mode"] == 3:
                results[name]["subsection_alignment_method"] = spec[
                    "subsection_alignment_method"
                ]
        except (
            OSError,
            json.JSONDecodeError,
            TypeError,
            AttributeError,
            ValueError,
        ) as exc:
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
    result = _score_configured_metric(metric_name, pairs, spec)
    if spec["mode"] == 3:
        result["subsection_alignment_method"] = spec.get(
            "subsection_alignment_method",
            DEFAULT_SUBSECTION_ALIGNMENT_METHOD,
        )
    return result
