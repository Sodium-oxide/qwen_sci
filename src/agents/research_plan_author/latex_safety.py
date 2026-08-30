"""Small, shared safety primitives for generated LaTeX and BibTeX."""

from __future__ import annotations

import re


class LatexSafetyError(ValueError):
    """Raised when document-controlled text is unsafe for the renderer."""


_OBSERVED_RESULT_LANGUAGE = re.compile(
    r"\b(?:we|this\s+(?:study|research|work|investigation|analysis)|"
    r"the\s+(?:study|experiment|analysis|evaluation))\s+(?:have\s+)?"
    r"(?:observed|found|demonstrated|showed|measured|established|confirmed|revealed)\b"
    r"|\b(?:the\s+)?(?:results|experiments|analyses|data|evaluation)\s+(?:have\s+)?"
    r"(?:observed|found|demonstrated|showed|measured|established|confirmed|revealed)\b",
    re.IGNORECASE,
)
_FORBIDDEN_TEX_COMMANDS = re.compile(
    r"\\(?:input|include|write|openout|read|catcode|newcommand|renewcommand|def|gdef|"
    r"usepackage|documentclass|immediate|write18|csname|expandafter|every|loop|directlua)\b",
    re.IGNORECASE,
)
_MATH_COMMAND = re.compile(r"\\([A-Za-z]+)")
_ALLOWED_MATH_COMMANDS = {
    "alpha", "beta", "gamma", "delta", "epsilon", "varepsilon", "zeta", "eta", "theta",
    "vartheta", "iota", "kappa", "lambda", "mu", "nu", "xi", "pi", "rho", "sigma",
    "tau", "upsilon", "phi", "varphi", "chi", "psi", "omega", "Gamma", "Delta", "Theta",
    "Lambda", "Xi", "Pi", "Sigma", "Phi", "Psi", "Omega", "frac", "sqrt", "sum", "prod",
    "int", "lim", "log", "ln", "exp", "sin", "cos", "tan", "min", "max", "sup", "inf",
    "forall", "exists", "in", "notin", "subset", "subseteq", "supset", "supseteq", "cup", "cap",
    "to", "rightarrow", "Rightarrow", "Leftarrow", "Leftrightarrow", "leq", "geq", "neq", "approx",
    "equiv", "times", "cdot", "pm", "mp", "partial", "nabla", "infty", "ldots", "dots", "mathrm",
    "mathcal", "mathbb", "mathbf", "operatorname", "left", "right", "langle", "rangle", "vert", "mid",
}
_ALLOWED_MATH_CHARS = re.compile(r"^[A-Za-z0-9\s+\-*/=<>(),.;:{}\[\]_\\^|!?'`]+$")
_MATH_STRUCTURE = re.compile(
    r"(?:[=<>]|[_^]|\\(?:frac|sqrt|sum|prod|int|lim|forall|exists|leq|geq|neq|approx|equiv|to|rightarrow|Rightarrow|Leftarrow|Leftrightarrow)\b)"
)
_MATH_IDENTIFIER_COMMAND = re.compile(
    r"\\(?:operatorname|mathrm|mathcal|mathbb|mathbf)\s*\{[A-Za-z]+\}"
)
_LOWERCASE_PROSE_WORD = re.compile(r"\b[a-z]{3,}\b")
_EQUATION_FRAGMENT_BOUNDARY = re.compile(r"\n[ \t]*\n+")


def contains_observed_result_language(value: object) -> bool:
    """Detect proposal-incompatible statements that present work as completed."""

    return bool(_OBSERVED_RESULT_LANGUAGE.search(str(value or "")))


def normalize_visible_text(value: object, *, label: str) -> str:
    """Normalize visible text while rejecting unsupported control characters.

    Author content may use any Unicode script. Text safety is enforced by
    escaping and raw-TeX restrictions rather than by a language gate.
    """

    text = str(value or "")
    if any(ord(character) < 32 and character not in "\n\r\t" for character in text):
        raise LatexSafetyError(f"{label} contains an unsupported control character")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def escape_latex_text(
    value: object,
    *,
    label: str = "text",
) -> str:
    """Escape plain visible text; this intentionally never preserves raw TeX."""

    text = normalize_visible_text(value, label=label)
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
        "\\": r"\textbackslash{}",
    }
    return "".join(replacements.get(character, character) for character in text)


def safe_math_expression(value: object, *, label: str = "equation") -> str:
    """Allow a deliberately small math-only subset and reject executable TeX."""

    text = normalize_visible_text(value, label=label).strip()
    if not text:
        raise LatexSafetyError(f"{label} is empty")
    if "$" in text or "\\begin" in text.casefold() or "\\end" in text.casefold():
        raise LatexSafetyError(f"{label} must be a math expression, not a TeX environment")
    if _FORBIDDEN_TEX_COMMANDS.search(text):
        raise LatexSafetyError(f"{label} contains a forbidden TeX command")
    if not _ALLOWED_MATH_CHARS.fullmatch(text):
        raise LatexSafetyError(f"{label} contains unsupported math characters")
    commands = _MATH_COMMAND.findall(text.replace(r"\\", " "))
    unsupported = sorted({command for command in commands if command not in _ALLOWED_MATH_COMMANDS})
    if unsupported:
        raise LatexSafetyError(f"{label} contains unsupported math commands: {', '.join(unsupported)}")
    if not _MATH_STRUCTURE.search(text):
        raise LatexSafetyError(f"{label} must contain a mathematical relation or structure")
    residual_text = _MATH_COMMAND.sub("", _MATH_IDENTIFIER_COMMAND.sub("", text))
    if _LOWERCASE_PROSE_WORD.search(residual_text):
        raise LatexSafetyError(f"{label} contains explanatory prose and must be split from its mathematics")
    return text


def split_equation_content(value: object, *, label: str = "equation") -> list[tuple[str, str]]:
    """Partition an equation block into safe math expressions and visible prose.

    A model may put sentence-level explanation around otherwise valid formulae.
    Keeping these fragments distinct lets the renderer preserve the explanation
    without sending it into a display-math environment.
    """

    text = normalize_visible_text(value, label=label).strip()
    if not text:
        raise LatexSafetyError(f"{label} is empty")
    if "$" in text or "\\begin" in text.casefold() or "\\end" in text.casefold():
        raise LatexSafetyError(f"{label} must be a math expression, not a TeX environment")
    if _FORBIDDEN_TEX_COMMANDS.search(text):
        raise LatexSafetyError(f"{label} contains a forbidden TeX command")
    fragments = [
        fragment.strip()
        for fragment in _EQUATION_FRAGMENT_BOUNDARY.split(text)
        if fragment.strip()
    ]
    result: list[tuple[str, str]] = []
    for index, fragment in enumerate(fragments, start=1):
        fragment_label = label if len(fragments) == 1 else f"{label} fragment {index}"
        try:
            result.append(("equation", safe_math_expression(fragment, label=fragment_label)))
        except LatexSafetyError:
            result.append(("prose", fragment))
    return result


def validate_citation_key(value: object) -> str:
    key = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._:+-]+", key):
        raise LatexSafetyError(f"citation key is unsafe for BibTeX: {key!r}")
    return key


__all__ = [
    "LatexSafetyError",
    "contains_observed_result_language",
    "escape_latex_text",
    "normalize_visible_text",
    "safe_math_expression",
    "split_equation_content",
    "validate_citation_key",
]
