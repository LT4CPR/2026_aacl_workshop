from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SubsectionKey = tuple[str, str]
BulletUnit = dict[str, Any]
MODE_SCOPE = {1: "document", 2: "section", 3: "subsection"}


class UnitExtractionError(ValueError):
    """Raised when SITREP JSON cannot be extracted."""

    def __init__(self, message: str, *, code: str = "extraction_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ExtractionResult:
    units: dict[SubsectionKey, list[BulletUnit]]
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _warning(code: str, message: str, **extra: Any) -> dict[str, Any]:
    payload = {"code": code, "message": message}
    payload.update(extra)
    return payload


def _validate_document(sitrep_json: Any) -> None:
    if not isinstance(sitrep_json, dict):
        raise UnitExtractionError(
            f"expected a JSON object at the top level, got {type(sitrep_json).__name__}",
            code="invalid_document_type",
        )


def _missing_structure_warnings(
    sitrep_json: dict[str, Any],
    mode: int,
) -> list[dict[str, Any]]:
    """Return warnings for missing structure."""

    warnings: list[dict[str, Any]] = []
    sections = sitrep_json.get("sections")
    if sections is None:
        return [_warning(
            "missing_section_structure",
            "document has no usable section structure ('sections' is null or absent)",
            reason="sections_null",
        )]
    if not isinstance(sections, list):
        raise UnitExtractionError(
            f"'sections' must be a list, got {type(sections).__name__}",
            code="invalid_sections_type",
        )
    if not sections:
        return [_warning(
            "missing_section_structure",
            "document has no usable section structure ('sections' is empty)",
            reason="sections_empty",
        )]

    if mode == 3:
        has_subsections = any(
            isinstance(section, dict) and (section.get("subsections") or [])
            for section in sections
        )
        if not has_subsections:
            warnings.append(_warning(
                "missing_section_structure",
                "document has sections but no subsections required for mode 3",
                reason="no_subsections",
            ))
    elif mode == 2:
        has_section_ids = any(
            isinstance(section, dict) and str(section.get("id", "")).strip()
            for section in sections
        )
        if not has_section_ids:
            warnings.append(_warning(
                "missing_section_structure",
                "document has sections but none with an id for mode 2",
                reason="no_section_ids",
            ))
    return warnings


def _section_direct_bullets(section: dict[str, Any]) -> list[dict[str, Any]]:
    bullets = section.get("bullets")
    if not bullets:
        return []
    if not isinstance(bullets, list):
        raise UnitExtractionError(
            f"section {section.get('id')!r} has non-list 'bullets'",
            code="invalid_bullets_field",
        )
    return bullets


def _bullet_unit(
    section_id: str,
    subsection_id: str,
    bullet: dict[str, Any],
) -> BulletUnit:
    return {
        "section_id": section_id,
        "subsection_id": subsection_id,
        "bullet_id": bullet.get("id"),
        "text": bullet.get("text", ""),
        "tweet_ids": bullet.get("tweet_ids", []),
        "confidence": bullet.get("confidence"),
    }


def extract_bullets_by_subsection(
    sitrep_json: dict[str, Any],
) -> dict[SubsectionKey, list[BulletUnit]]:
    """Extract bullets by subsection key."""

    bullets_by_subsection: dict[SubsectionKey, list[BulletUnit]] = {}

    for section_index, section in enumerate(sitrep_json.get("sections", []) or []):
        if not isinstance(section, dict):
            raise UnitExtractionError(
                f"section at index {section_index} must be an object",
                code="invalid_section_type",
            )
        raw_subsections = section.get("subsections", []) or []
        if not isinstance(raw_subsections, list):
            raise UnitExtractionError(
                f"section at index {section_index} has non-list 'subsections'",
                code="invalid_subsections_type",
            )
        scorable_subsections: list[tuple[int, dict[str, Any], list[Any]]] = []
        for subsection_index, subsection in enumerate(raw_subsections):
            if not isinstance(subsection, dict):
                raise UnitExtractionError(
                    f"subsection at section index {section_index}, index "
                    f"{subsection_index} must be an object",
                    code="invalid_subsection_type",
                )
            bullets = subsection.get("bullets", []) or []
            if not isinstance(bullets, list):
                raise UnitExtractionError(
                    f"subsection at section index {section_index}, index "
                    f"{subsection_index} has non-list 'bullets'",
                    code="invalid_bullets_field",
                )
            if bullets:
                scorable_subsections.append(
                    (subsection_index, subsection, bullets)
                )

        direct_bullets = _section_direct_bullets(section)
        if not direct_bullets and not scorable_subsections:
            # Header-only containers have no scoring unit, so their IDs are
            # irrelevant and they are equivalent to absent structure.
            continue

        section_id = str(section.get("id", "")).strip()
        if not section_id:
            raise UnitExtractionError(
                f"section at index {section_index} has no id",
                code="missing_section_id",
            )

        for subsection_index, subsection, raw_bullets in scorable_subsections:
            subsection_id = str(subsection.get("id", "")).strip()
            if not subsection_id:
                raise UnitExtractionError(
                    f"subsection at section {section_id}, index "
                    f"{subsection_index} has no id",
                    code="missing_subsection_id",
                )

            key = (section_id, subsection_id)
            if key in bullets_by_subsection:
                raise UnitExtractionError(
                    f"duplicate subsection key: {key!r}",
                    code="duplicate_subsection_key",
                )

            bullets: list[BulletUnit] = []

            for bullet in raw_bullets:
                if not isinstance(bullet, dict):
                    raise UnitExtractionError(
                        f"bullet in subsection {key!r} must be an object",
                        code="invalid_bullet_type",
                    )
                bullets.append(_bullet_unit(section_id, subsection_id, bullet))

            bullets_by_subsection[key] = bullets

    return bullets_by_subsection


def _collect_section_level_bullets(
    sitrep_json: dict[str, Any],
) -> dict[str, list[BulletUnit]]:
    """Return section-level bullets by section ID."""

    grouped: dict[str, list[BulletUnit]] = {}
    for section_index, section in enumerate(sitrep_json.get("sections", []) or []):
        if not isinstance(section, dict):
            raise UnitExtractionError(
                f"section at index {section_index} must be an object",
                code="invalid_section_type",
            )
        direct = _section_direct_bullets(section)
        if not direct:
            continue
        section_id = str(section.get("id", "")).strip()
        if not section_id:
            raise UnitExtractionError(
                f"section at index {section_index} has no id",
                code="missing_section_id",
            )
        bullets: list[BulletUnit] = []
        for bullet_index, bullet in enumerate(direct):
            if not isinstance(bullet, dict):
                raise UnitExtractionError(
                    f"bullet at section {section_id}, index "
                    f"{bullet_index} must be an object",
                    code="invalid_bullet_type",
                )
            bullets.append(_bullet_unit(section_id, "_direct", bullet))
        grouped[section_id] = bullets
    return grouped


def extract_units_by_group(
    sitrep_json: dict[str, Any],
    mode: int,
    unit_mode: str,
    selected_sections: tuple[str, ...] | None = None,
) -> ExtractionResult:
    """Extract comparison units for the selected scope."""
    if mode not in MODE_SCOPE:
        raise UnitExtractionError(
            f"unsupported mode: {mode}; expected 1, 2, or 3",
            code="unsupported_mode",
        )
    if unit_mode not in {"bullet", "text"}:
        raise UnitExtractionError(
            f"unsupported unit_mode: {unit_mode!r}; expected 'bullet' or 'text'",
            code="unsupported_unit_mode",
        )

    _validate_document(sitrep_json)
    working_document = sitrep_json
    selection_warnings: list[dict[str, Any]] = []
    if selected_sections is not None:
        sections = sitrep_json.get("sections")
        if isinstance(sections, list):
            selected = set(selected_sections)
            present = {
                str(section.get("id", "")).strip()
                for section in sections
                if isinstance(section, dict) and str(section.get("id", "")).strip()
            }
            missing = [section_id for section_id in selected_sections if section_id not in present]
            if missing:
                selection_warnings.append(_warning(
                    "selected_sections_not_found",
                    "requested section IDs were not found in the document",
                    sections=missing,
                ))
            working_document = {
                **sitrep_json,
                "sections": [
                    section
                    for section in sections
                    if isinstance(section, dict)
                    and str(section.get("id", "")).strip() in selected
                ],
            }

    warnings = selection_warnings + _missing_structure_warnings(working_document, mode)
    section_level = _collect_section_level_bullets(working_document)
    if section_level and mode == 3:
        total = sum(len(bullets) for bullets in section_level.values())
        warnings.append(_warning(
            "section_level_bullets_ignored",
            f"ignored {total} section-level bullet(s) that cannot be aligned at subsection scope",
            count=total,
        ))
    if section_level and mode in {1, 2}:
        warnings.append(_warning(
            "section_level_bullets_included",
            "section-level bullets were merged into the active scope groups",
            count=sum(len(bullets) for bullets in section_level.values()),
        ))

    by_subsection = extract_bullets_by_subsection(working_document)
    grouped: dict[SubsectionKey, list[BulletUnit]] = {}

    if mode == 1:
        document_key = ("document", "document")
        grouped[document_key] = [
            bullet
            for bullets in by_subsection.values()
            for bullet in bullets
        ]
        for bullets in section_level.values():
            grouped[document_key].extend(bullets)
    elif mode == 2:
        for section in working_document.get("sections", []) or []:
            if not isinstance(section, dict):
                continue
            section_id = str(section.get("id", "")).strip()
            if section_id:
                grouped.setdefault((section_id, "section"), [])
        for (section_id, _), bullets in by_subsection.items():
            grouped.setdefault((section_id, "section"), []).extend(bullets)
        for section_id, bullets in section_level.items():
            grouped.setdefault((section_id, "section"), []).extend(bullets)
    else:
        grouped = {key: list(bullets) for key, bullets in by_subsection.items()}

    # A structural header with no content is equivalent to an absent group for
    # scoring.  Keeping empty keys would change structure precision/recall even
    # though there is no text or bullet to evaluate.
    if mode in {2, 3}:
        grouped = {
            key: bullets for key, bullets in grouped.items() if bullets
        }

    if unit_mode == "bullet":
        if not grouped and not any(
            warning["code"] == "missing_section_structure" for warning in warnings
        ):
            warnings.append(_warning(
                "no_units_extracted",
                "no comparison units were extracted from the document",
            ))
        elif grouped and sum(len(units) for units in grouped.values()) == 0:
            warnings.append(_warning(
                "no_units_extracted",
                "document structure exists but every comparison unit is empty",
            ))
        return ExtractionResult(units=grouped, warnings=warnings)

    text_groups: dict[SubsectionKey, list[BulletUnit]] = {}
    for key, bullets in grouped.items():
        text = " ".join(
            str(bullet.get("text", "")).strip()
            for bullet in bullets
            if str(bullet.get("text", "")).strip()
        )
        text_groups[key] = [] if not text else [{
            "section_id": key[0],
            "subsection_id": key[1],
            "bullet_id": None,
            "text": text,
            "tweet_ids": [
                tweet_id
                for bullet in bullets
                for tweet_id in (bullet.get("tweet_ids") or [])
            ],
            "confidence": None,
            "source_bullet_count": len(bullets),
        }]
    if not text_groups and not any(
        warning["code"] == "missing_section_structure" for warning in warnings
    ):
        warnings.append(_warning(
            "no_units_extracted",
            "no comparison units were extracted from the document",
        ))
    return ExtractionResult(units=text_groups, warnings=warnings)
