"""Render only audited quantitative-model JSON into a fixed standalone TeX document."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from src.agents.research_plan_author.latex_safety import (
    LatexSafetyError,
    escape_latex_text,
    safe_math_expression,
)


class QuantitativeTexRenderError(ValueError):
    """Raised when audited data still cannot be rendered as safe standalone TeX."""


_MATH_TEXT_IDENTIFIER = re.compile(
    r"\\text\s*\{\s*([A-Za-z][A-Za-z0-9]*(?:\s*,\s*[A-Za-z0-9]+)*)\s*\}"
)
_BARE_MATH_SUBSCRIPT_IDENTIFIER = re.compile(r"(?P<operator>[_^])\{(?P<identifier>[A-Za-z][A-Za-z0-9]*)\}")
_CASES_ENVIRONMENT = re.compile(
    r"\\begin\s*\{cases\}(.*?)\\end\s*\{cases\}",
    re.DOTALL,
)
_UNIT_PRODUCT_TOKEN = re.compile(r"([A-Za-z]+)(?:\^([+-]?\d+))?")
_LONG_ALNUM_TOKEN = re.compile(r"(?<![A-Za-z0-9])([A-Za-z0-9]{24,})(?![A-Za-z0-9])")


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str:
    return str(value or "").strip()


def _label(value: object) -> str:
    result = re.sub(r"[^A-Za-z0-9:-]+", "-", _text(value)).strip("-:")
    if not result:
        raise QuantitativeTexRenderError("a stable non-empty TeX label is required")
    return result


def _safe_text(value: object, *, label: str) -> str:
    """Render prose fields safely even when they contain a literal equality sign."""

    return escape_latex_text(value, label=label).replace("=", r"\ensuremath{=}")


def _safe_breakable_text(value: object, *, label: str) -> str:
    escaped = _safe_text(value, label=label)
    escaped = escaped.replace(r"\_", r"\_\allowbreak{}")
    escaped = escaped.replace("/", r"/\allowbreak{}")

    def split_long_token(match: re.Match[str]) -> str:
        token = match.group(1)
        return r"\allowbreak{}".join(
            token[index : index + 16] for index in range(0, len(token), 16)
        )

    return _LONG_ALNUM_TOKEN.sub(split_long_token, escaped)


def _normalize_quantitative_math(value: object) -> str:
    raw = _text(value).replace(r"\quad", " ")

    raw = _BARE_MATH_SUBSCRIPT_IDENTIFIER.sub(
        lambda match: f"{match.group('operator')}{{\\mathrm{{{match.group('identifier')}}}}}",
        raw,
    )

    def replace_identifier(match: re.Match[str]) -> str:
        identifier = re.sub(r"\s+", "", match.group(1))
        return r"\mathrm{" + identifier + "}"

    return _MATH_TEXT_IDENTIFIER.sub(replace_identifier, raw)


def _validate_math_fragment(value: str, *, label: str) -> None:
    fragment = value.strip()
    if not fragment:
        raise QuantitativeTexRenderError(f"{label} is empty")
    if fragment.endswith(("=", "<", ">")):
        candidate = fragment + "0"
    else:
        candidate = f"({fragment})=0"
    safe_math_expression(candidate, label=label)


def _safe_quantitative_equation(value: object, *, label: str) -> str:
    expression = _normalize_quantitative_math(value)
    cases = list(_CASES_ENVIRONMENT.finditer(expression))
    if not cases:
        return safe_math_expression(expression, label=label)
    if len(cases) != 1:
        raise QuantitativeTexRenderError(f"{label} must contain at most one cases environment")
    match = cases[0]
    outside = expression[: match.start()] + expression[match.end() :]
    if r"\begin" in outside or r"\end" in outside:
        raise QuantitativeTexRenderError(f"{label} contains an unsupported TeX environment")
    _validate_math_fragment(expression[: match.start()], label=f"{label} left-hand side")
    suffix = expression[match.end() :]
    if suffix.strip():
        _validate_math_fragment(suffix, label=f"{label} suffix")
    rows = [row.strip() for row in re.split(r"\\\\", match.group(1)) if row.strip()]
    if not rows:
        raise QuantitativeTexRenderError(f"{label} cases environment is empty")
    for index, row in enumerate(rows, start=1):
        parts = row.split("&")
        if len(parts) != 2:
            raise QuantitativeTexRenderError(
                f"{label} case row {index} must contain exactly one alignment separator"
            )
        _validate_math_fragment(parts[0], label=f"{label} case row {index} value")
        _validate_math_fragment(parts[1], label=f"{label} case row {index} condition")
    return expression


def _bullet_list(values: Sequence[object], *, label: str) -> str:
    items = [_safe_breakable_text(value, label=label) for value in values if _text(value)]
    if not items:
        return "\\emph{Not specified.}"
    return "\\begin{itemize}\\raggedright\n" + "\n".join(f"\\item {item}" for item in items) + "\n\\end{itemize}"


def _safe_symbol_latex(value: object) -> str:
    """Reuse the strict math checker while allowing a symbol such as ``x``."""

    raw = _normalize_quantitative_math(value)
    safe_math_expression(raw + "=0", label="symbol")
    return raw


def _render_unit(value: object) -> str:
    raw = _text(value)
    if raw == "solar_mass":
        return "solar mass"
    product_tokens = raw.split("_")
    parsed_tokens = [_UNIT_PRODUCT_TOKEN.fullmatch(token) for token in product_tokens]
    if product_tokens and all(parsed_tokens):
        rendered_tokens: list[str] = []
        for parsed in parsed_tokens:
            assert parsed is not None
            rendered = r"\mathrm{" + parsed.group(1) + "}"
            if parsed.group(2):
                rendered += "^{" + parsed.group(2) + "}"
            rendered_tokens.append(rendered)
        return "$" + r"\,".join(rendered_tokens) + "$"
    if any(character in raw for character in "^_/\\"):
        try:
            return "$" + safe_math_expression(raw, label="symbol unit") + "$"
        except LatexSafetyError:
            pass
    return _safe_text(raw, label="symbol unit")


def _render_symbols(symbols: Sequence[object]) -> str:
    rows: list[str] = []
    for raw in symbols:
        symbol = _mapping(raw)
        rows.append(
            " & ".join(
                (
                    _safe_text(symbol.get("symbol_id"), label="symbol ID"),
                    "$" + _safe_symbol_latex(symbol.get("latex")) + "$",
                    _safe_text(symbol.get("meaning"), label="symbol meaning"),
                    _render_unit(symbol.get("unit")),
                )
            )
            + r" \\ \hline"
        )
    return "\n".join(
        (
            "\\begin{center}",
            "\\small",
            "\\begin{tabular}{|p{0.12\\linewidth}|p{0.15\\linewidth}|p{0.46\\linewidth}|p{0.17\\linewidth}|}",
            "\\hline",
            "ID & Symbol & Meaning & Unit \\\\ \\hline",
            *rows,
            "\\end{tabular}",
            "\\end{center}",
        )
    )


def _render_equations(equations: Sequence[object], symbols: Sequence[object]) -> str:
    meanings = {str(_mapping(symbol).get("symbol_id")): _mapping(symbol).get("meaning") for symbol in symbols}
    fragments: list[str] = []
    for raw in equations:
        equation = _mapping(raw)
        equation_id = _text(equation.get("equation_id"))
        expression = _safe_quantitative_equation(equation.get("latex"), label=equation_id)
        where_ids = [str(item) for item in equation.get("where_symbol_ids") or []]
        where = "; ".join(
            f"{identifier}: {_text(meanings.get(identifier))}" for identifier in where_ids
        )
        fragments.append(
            "\n".join(
                (
                f"\\begin{{equation}}\\label{{eq:{_label(equation_id)}}}",
                expression,
                "\\end{equation}",
                "\\noindent\\textbf{" + _safe_text(equation_id, label="equation ID") + " where} "
                + _safe_text(where, label="equation where explanation")
                + ".",
                )
            )
        )
    return "\n\n".join(fragments)


def _render_algorithm(algorithm: Mapping[str, object]) -> str:
    return "\n".join(
        (
            "\\noindent\\textbf{Algorithm}",
            "\\paragraph{Input}",
            _bullet_list(list(algorithm.get("input") or []), label="algorithm input"),
            "\\paragraph{Output}",
            _bullet_list(list(algorithm.get("output") or []), label="algorithm output"),
            "\\paragraph{Steps}",
            _bullet_list(list(algorithm.get("steps") or []), label="algorithm step"),
        )
    )


def _render_result_entries(entries: Sequence[object]) -> str:
    lines: list[str] = []
    for raw in entries:
        entry = _mapping(raw)
        lines.append(
            "\\item "
            + _safe_text(
                " ".join(
                    (
                        f"Execution {entry.get('execution_id')};",
                        "NUMERICAL_SIMULATION; SIMULATED; NOT_EMPIRICAL;",
                        f"relation {entry.get('hypothesis_relation')};",
                        f"summary: {entry.get('result_summary')}",
                    )
                ),
                label="simulation result summary",
            )
        )
    return "\\begin{itemize}\n" + "\n".join(lines) + "\n\\end{itemize}"


def _render_pde_contract(specification: Mapping[str, object]) -> list[str]:
    execution_ir = _mapping(specification.get("execution_ir"))
    document = _mapping(execution_ir.get("document"))
    if execution_ir.get("kind") != "PDE" or not document:
        return []
    fields = [
        f"{_text(_mapping(field).get('id'))} ({_text(_mapping(field).get('symbol'))}); unit {_text(_mapping(field).get('unit'))}"
        for field in document.get("fields") or []
    ]
    domain = _mapping(document.get("spatial_domain"))
    grid = _mapping(document.get("grid"))
    boundary_lines = [
        f"{name}: {_text(_mapping(value).get('type'))}"
        for name, value in _mapping(document.get("boundary_conditions")).items()
    ]
    solver_options = _mapping(document.get("solver_options"))
    lines = [
        "\\subsection{PDE Model Class}",
        "\\noindent\\textbf{System type.} " + _safe_text(document.get("system_type"), label="PDE system type") + ".",
        "\\noindent\\textbf{Trusted adapter.} " + _safe_text(
            _mapping(specification.get("numerical_plan")).get("solver_family"), label="PDE solver family"
        ) + ".",
        "\\subsection{Spatial Domain and Field Variables}",
        "\\paragraph{Domain and mesh}\n" + _bullet_list(
            [
                "Domain: " + "; ".join(f"{key}={value}" for key, value in domain.items()),
                "Grid: " + "; ".join(f"{key}={value}" for key, value in grid.items()),
            ],
            label="PDE domain",
        ),
        "\\paragraph{Fields}\n" + _bullet_list(fields, label="PDE field"),
        "\\subsection{PDE Initial and Boundary Conditions}",
        "\\paragraph{Initial condition}\n" + _bullet_list(
            ["Sampled values on the normalized mesh.", "Time span: " + "; ".join(str(value) for value in document.get("time_span") or [])]
            if document.get("time_span") is not None
            else ["Steady-state solve."],
            label="PDE initial condition",
        ),
        "\\paragraph{Boundary condition types}\n" + _bullet_list(boundary_lines, label="PDE boundary condition"),
        "\\subsection{Discretization and Stability}",
        "\\noindent\\textbf{Discretization.} " + _safe_text(
            _mapping(specification.get("numerical_plan")).get("discretization"), label="PDE discretization"
        ) + ".",
        "\\noindent\\textbf{Time integration.} " + _safe_text(
            solver_options.get("time_integrator") or "steady solve", label="PDE time integrator"
        ) + ("; time step " + _safe_text(solver_options.get("time_step"), label="PDE time step") + "." if solver_options else "."),
        "\\subsection{Numerical Verification}",
        "\\noindent The fixed PDE adapter reports finite-field checks and the family-specific stability or linear-residual diagnostic. "
        "A result is qualified only when the declared checks pass; all outcomes remain model-internal simulations.",
    ]
    return lines


def _render_parameter_provenance(value: object) -> str:
    provenance = _mapping(value)
    mode = _text(provenance.get("mode"))
    if mode != "APPROVED_PARAMETER_SET":
        return (
            "\\noindent\\textbf{Parameter status.} "
            "This legacy model used inline assumptions; it has no approved external parameter set."
        )
    entries: list[str] = []
    for raw_entry in provenance.get("entries") or []:
        entry = _mapping(raw_entry)
        source = _mapping(entry.get("source"))
        locator = _mapping(entry.get("evidence_locator"))
        conditions = _mapping(entry.get("conditions"))
        uncertainty = _mapping(entry.get("uncertainty"))
        status = _text(entry.get("provenance_status"))
        if status == "APPROVED_MODEL_ASSUMPTION":
            source_text = "MODEL ASSUMPTION (not a measured or literature value)"
        else:
            source_parts = [
                _text(source.get("title")),
                f"DOI {_text(source.get('doi'))}" if _text(source.get("doi")) else "",
                f"document {_text(source.get('document_id'))}" if _text(source.get("document_id")) else "",
            ]
            source_text = "; ".join(part for part in source_parts if part) or "controlled source metadata"
            locator_parts = [
                _text(locator.get("document_type")),
                _text(locator.get("section")),
                _text(locator.get("table_or_figure")),
                f"page {locator.get('page')}" if locator.get("page") is not None else "",
            ]
            locator_text = "; ".join(part for part in locator_parts if part) or "no structured locator supplied"
            source_text = source_text + "; locator: " + locator_text
        condition_text = "; ".join(
            f"{key}={item}" for key, item in sorted(conditions.items())
        ) or "no additional structured condition supplied"
        uncertainty_text = "; ".join(
            f"{key}={item}" for key, item in sorted(uncertainty.items())
        ) or "not reported"
        entries.append(
            " ".join(
                (
                    f"{_text(entry.get('parameter_id'))} ({_text(entry.get('mathir_symbol'))})",
                    f"= {entry.get('selected_value')} {_text(entry.get('unit'))};",
                    f"role {_text(entry.get('role'))};",
                    f"status {status};",
                    f"source: {source_text};",
                    f"applicability: {condition_text}.",
                    f"uncertainty: {uncertainty_text}.",
                )
            )
        )
    identity = _safe_breakable_text(
        provenance.get("parameter_set_identity"), label="parameter set identity"
    )
    return "\n".join(
        (
            "\\noindent\\textbf{Approved parameter-set identity.} " + identity + ".",
            _bullet_list(entries, label="parameter provenance"),
        )
    )


def render_quantitative_models_tex(records: Sequence[Mapping[str, object]]) -> str:
    """Create standalone TeX with numbered formulas and no raw LLM TeX template input."""

    if not records:
        raise QuantitativeTexRenderError("at least one finalized quantitative model is required")
    sections: list[str] = []
    for raw_record in records:
        record = _mapping(raw_record)
        specification = _mapping(record.get("model_spec"))
        lineage = _mapping(specification.get("lineage"))
        quantitative_idea_id = _text(lineage.get("quantitative_idea_id"))
        version = lineage.get("version")
        sections.extend(
            (
                "\\section{" + _safe_text(f"{quantitative_idea_id} (final: v{version})", label="model title") + "}",
                "\\noindent\\textbf{Abstract—} " + _safe_text(specification.get("abstract"), label="abstract"),
                "\\subsection{Question and Scope}",
                "\\noindent\\textbf{Question.} " + _safe_text(specification.get("scientific_question"), label="question"),
                "\n\n" + _safe_text(specification.get("model_scope"), label="model scope"),
                "\\subsection{Model Assumptions and Applicability}",
                _bullet_list(
                    [
                        f"{item.get('assumption_id')}: {item.get('statement')} If violated: {item.get('effect_if_violated')}"
                        for item in specification.get("assumptions") or []
                        if isinstance(item, Mapping)
                    ],
                    label="assumption",
                ),
                *_render_pde_contract(specification),
                "\\subsection{Symbols and Units}",
                _render_symbols(list(specification.get("symbols") or [])),
                "\\subsection{Mechanistic Equations}",
                _render_equations(list(specification.get("equations") or []), list(specification.get("symbols") or [])),
                "\\subsection{Initial Conditions, Boundary Conditions, and Constraints}",
                "\\paragraph{Initial Conditions}\n" + _bullet_list(list(specification.get("initial_conditions") or []), label="initial condition"),
                "\\paragraph{Boundary Conditions}\n" + _bullet_list(list(specification.get("boundary_conditions") or []), label="boundary condition"),
                "\\paragraph{Objective and Constraints}\n" + _bullet_list(list(specification.get("objective_and_constraints") or []), label="objective and constraint"),
                "\\subsection{Algorithm}",
                _render_algorithm(_mapping(specification.get("algorithm"))),
                "\\subsection{Parameters, Scenarios, and Numerical Settings}",
                "\\paragraph{Parameters}\n" + _bullet_list(list(specification.get("parameterization") or []), label="parameter"),
                "\\paragraph{Scenarios}\n" + _bullet_list(list(specification.get("scenarios") or []), label="scenario"),
                "\\noindent\\textbf{Solver family.} " + _safe_text(_mapping(specification.get("numerical_plan")).get("solver_family"), label="solver family") + ".",
                "\\subsection{Parameter Provenance and Applicability}",
                _render_parameter_provenance(specification.get("parameter_provenance")),
                "\\subsection{Numerical Validation and Model-Internal Results}",
                "\\paragraph{Validation Plan}\n" + _bullet_list(list(specification.get("validation_plan") or []), label="validation plan"),
                _render_result_entries(list(record.get("qualified_entries") or [])),
                "\\subsection{Hypothesis Iteration Lineage}",
                _bullet_list(list(record.get("lineage_summary") or []), label="iteration lineage"),
                "\\subsection{Limitations, Non-Empirical Disclosure, and References}",
                "\\noindent All values in this section are model-internal numerical simulations (NUMERICAL\\_SIMULATION; SIMULATED; NOT\\_EMPIRICAL), not empirical observations.",
                "\\paragraph{Limitations}\n" + _bullet_list(list(specification.get("limitations") or []), label="limitation"),
                "\\paragraph{References}\n" + _bullet_list(list(specification.get("references") or []), label="reference"),
            )
        )
    return "\n\n".join(
        (
            r"\documentclass[11pt]{article}",
            r"\usepackage[margin=1in]{geometry}",
            r"\usepackage{amsmath}",
            r"\usepackage[T1]{fontenc}",
            r"\title{Mathematical Modeling and Numerical Simulation Supplement}",
            r"\author{Anonymous Research Plan Author}",
            r"\date{}",
            r"\begin{document}",
            r"\setlength{\emergencystretch}{3em}",
            r"\maketitle",
            *sections,
            r"\end{document}",
        )
    ) + "\n"


__all__ = ["QuantitativeTexRenderError", "render_quantitative_models_tex"]
