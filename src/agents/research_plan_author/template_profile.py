"""Explicit, fail-closed LaTeX template profiles for Research Plan Author."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


TEMPLATE_PROFILE_SCHEMA_VERSION = "research_plan_author_template_profile_v1"
_REQUIRED_INSERTIONS = ("title", "author", "abstract", "body", "bibliography")


class TemplateProfileError(ValueError):
    """Raised when a template profile is absent, ambiguous, or unsafe."""


@dataclass(frozen=True)
class TemplateInsertion:
    """One exact marker or bounded source region in a declared template."""

    kind: str
    marker: str = ""
    start: str = ""
    end: str = ""
    include_start: bool = True
    include_end: bool = True


@dataclass(frozen=True)
class TemplateProfile:
    """Template-owned locations that the renderer may replace exactly once."""

    profile_id: str
    main_tex: str
    generated_bib: str
    bibliography_style: str
    insertions: dict[str, TemplateInsertion]
    discard_regions: tuple[TemplateInsertion, ...] = ()


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _region(*, start: str, end: str, include_start: bool = True, include_end: bool = True) -> TemplateInsertion:
    return TemplateInsertion(
        kind="region",
        start=start,
        end=end,
        include_start=include_start,
        include_end=include_end,
    )


def _builtin_profiles() -> dict[str, TemplateProfile]:
    """Return only profiles with deliberately fixed, auditable anchors."""

    return {
        "markers_v1": TemplateProfile(
            profile_id="markers_v1",
            main_tex="main.tex",
            generated_bib="references.bib",
            bibliography_style="plain",
            insertions={
                name: TemplateInsertion(kind="marker", marker=f"% QWENSCI_AUTHOR_{name.upper()}")
                for name in _REQUIRED_INSERTIONS
            },
        ),
        "ieee_conference_v1": TemplateProfile(
            profile_id="ieee_conference_v1",
            main_tex="conference_101719.tex",
            generated_bib="references.bib",
            bibliography_style="IEEEtran",
            insertions={
                "title": _region(start="\\title{", end="\\author{", include_start=True, include_end=False),
                "author": _region(start="\\author{", end="\\maketitle", include_start=True, include_end=False),
                "abstract": _region(start="\\begin{abstract}", end="\\end{IEEEkeywords}"),
                "body": _region(
                    start="\\end{IEEEkeywords}",
                    end="\\section*{Acknowledgment}",
                    include_start=False,
                    include_end=False,
                ),
                "bibliography": _region(start="\\section*{References}", end="\\end{thebibliography}"),
            },
            discard_regions=(
                _region(
                    start="\\section*{Acknowledgment}",
                    end="\\section*{References}",
                    include_start=True,
                    include_end=False,
                ),
                _region(
                    start="\\vspace{12pt}",
                    end="\\end{document}",
                    include_start=True,
                    include_end=False,
                ),
            ),
        ),
    }


def _parse_insertion(raw: object, *, label: str) -> TemplateInsertion:
    value = _mapping(raw)
    kind = _text(value.get("kind"))
    if kind == "marker":
        marker = _text(value.get("marker"))
        if not marker:
            raise TemplateProfileError(f"template profile insertion '{label}' has no marker")
        return TemplateInsertion(kind="marker", marker=marker)
    if kind == "region":
        start = _text(value.get("start"))
        end = _text(value.get("end"))
        if not start or not end or start == end:
            raise TemplateProfileError(f"template profile insertion '{label}' has an invalid bounded region")
        return TemplateInsertion(
            kind="region",
            start=start,
            end=end,
            include_start=bool(value.get("include_start", True)),
            include_end=bool(value.get("include_end", True)),
        )
    raise TemplateProfileError(f"template profile insertion '{label}' must be marker or region")


def _profile_from_mapping(payload: Mapping[str, Any]) -> TemplateProfile:
    if _text(payload.get("schema_version")) != TEMPLATE_PROFILE_SCHEMA_VERSION:
        raise TemplateProfileError(
            f"template profile schema_version must be {TEMPLATE_PROFILE_SCHEMA_VERSION}"
        )
    profile_id = _text(payload.get("profile_id"))
    main_tex = _text(payload.get("main_tex"))
    if not profile_id or not main_tex:
        raise TemplateProfileError("template profile requires non-empty profile_id and main_tex")
    insertions_raw = _mapping(payload.get("insertions"))
    missing = [name for name in _REQUIRED_INSERTIONS if name not in insertions_raw]
    if missing:
        raise TemplateProfileError("template profile is missing insertions: " + ", ".join(missing))
    insertions = {name: _parse_insertion(insertions_raw[name], label=name) for name in _REQUIRED_INSERTIONS}
    discard_regions = tuple(
        _parse_insertion(value, label=f"discard_regions[{index}]")
        for index, value in enumerate(payload.get("discard_regions") or [])
    )
    if any(region.kind != "region" for region in discard_regions):
        raise TemplateProfileError("template profile discard_regions must contain bounded regions")
    return TemplateProfile(
        profile_id=profile_id,
        main_tex=main_tex,
        generated_bib=_text(payload.get("generated_bib")) or "references.bib",
        bibliography_style=_text(payload.get("bibliography_style")) or "plain",
        insertions=insertions,
        discard_regions=discard_regions,
    )


def load_template_profile(reference: str | Path | None, *, main_tex: str | None = None) -> TemplateProfile:
    """Load an explicit built-in or JSON profile without guessing source anchors."""

    raw_reference = _text(reference) or "markers_v1"
    builtins = _builtin_profiles()
    if raw_reference in builtins:
        profile = builtins[raw_reference]
    else:
        path = Path(raw_reference).expanduser().resolve()
        if not path.is_file():
            raise TemplateProfileError(
                f"template profile '{raw_reference}' is neither a supported profile ID nor a readable JSON file"
            )
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise TemplateProfileError(f"cannot read template profile '{path}': {error}") from error
        if not isinstance(parsed, Mapping):
            raise TemplateProfileError("template profile JSON root must be an object")
        profile = _profile_from_mapping(parsed)
    if main_tex is None or not _text(main_tex):
        return profile
    relative_main = Path(_text(main_tex))
    if relative_main.is_absolute() or ".." in relative_main.parts:
        raise TemplateProfileError("template main TeX path must be relative and remain inside the template")
    return TemplateProfile(
        profile_id=profile.profile_id,
        main_tex=relative_main.as_posix(),
        generated_bib=profile.generated_bib,
        bibliography_style=profile.bibliography_style,
        insertions=profile.insertions,
        discard_regions=profile.discard_regions,
    )


__all__ = [
    "TEMPLATE_PROFILE_SCHEMA_VERSION",
    "TemplateInsertion",
    "TemplateProfile",
    "TemplateProfileError",
    "load_template_profile",
]
