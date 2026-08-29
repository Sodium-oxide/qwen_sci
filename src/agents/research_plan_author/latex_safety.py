"""Small, shared safety primitives for generated LaTeX and BibTeX."""

from __future__ import annotations

import re
import unicodedata


class LatexSafetyError(ValueError):
    """Raised when document-controlled text is unsafe for the renderer."""


_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002FA1F]")
_NON_ENGLISH_SCRIPT_MARKERS = (
    "ARABIC",
    "ARMENIAN",
    "BALINESE",
    "BENGALI",
    "BOPOMOFO",
    "CANADIAN SYLLABICS",
    "CHEROKEE",
    "CJK",
    "COPTIC",
    "CYRILLIC",
    "DEVANAGARI",
    "ETHIOPIC",
    "GEORGIAN",
    "GREEK",
    "GUJARATI",
    "GURMUKHI",
    "HANGUL",
    "HEBREW",
    "HIRAGANA",
    "KANGXI",
    "KANNADA",
    "KATAKANA",
    "KHMER",
    "LAO",
    "MALAYALAM",
    "MONGOLIAN",
    "MYANMAR",
    "ORIYA",
    "RUNIC",
    "SINHALA",
    "SYRIAC",
    "TAMIL",
    "TELUGU",
    "THAI",
    "TIBETAN",
    "YI ",
)
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


def contains_cjk(value: object) -> bool:
    return bool(_CJK.search(str(value or "")))


def contains_non_english_script(value: object) -> bool:
    """Return whether visible text uses a non-Latin writing system.

    This is a script safeguard rather than a language detector: accented Latin
    scientific terms and names remain allowed, whereas scripts that cannot
    satisfy the English-only Author prose contract are rejected.
    """

    for character in str(value or ""):
        name = unicodedata.name(character, "")
        if any(marker in name for marker in _NON_ENGLISH_SCRIPT_MARKERS):
            return True
    return False


def contains_observed_result_language(value: object) -> bool:
    """Detect proposal-incompatible statements that present work as completed."""

    return bool(_OBSERVED_RESULT_LANGUAGE.search(str(value or "")))


def require_english_visible_text(value: object, *, label: str) -> str:
    text = str(value or "")
    if contains_non_english_script(text):
        raise LatexSafetyError(
            f"{label} contains non-English-script visible prose; final Author prose must be English only"
        )
    if any(ord(character) < 32 and character not in "\n\r\t" for character in text):
        raise LatexSafetyError(f"{label} contains an unsupported control character")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def escape_latex_text(value: object, *, label: str = "text") -> str:
    """Escape plain visible text; this intentionally never preserves raw TeX."""

    text = require_english_visible_text(value, label=label)
    placeholder = "\u0000QWENSCI_BACKSLASH\u0000"
    text = text.replace("\\", placeholder)
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
    }
    for raw, escaped in replacements.items():
        text = text.replace(raw, escaped)
    return text.replace(placeholder, r"\textbackslash{}")


def safe_math_expression(value: object, *, label: str = "equation") -> str:
    """Allow a deliberately small math-only subset and reject executable TeX."""

    text = require_english_visible_text(value, label=label).strip()
    if not text:
        raise LatexSafetyError(f"{label} is empty")
    if "$" in text or "\\begin" in text.casefold() or "\\end" in text.casefold():
        raise LatexSafetyError(f"{label} must be a math expression, not a TeX environment")
    if _FORBIDDEN_TEX_COMMANDS.search(text):
        raise LatexSafetyError(f"{label} contains a forbidden TeX command")
    if not _ALLOWED_MATH_CHARS.fullmatch(text):
        raise LatexSafetyError(f"{label} contains unsupported math characters")
    commands = _MATH_COMMAND.findall(text)
    unsupported = sorted({command for command in commands if command not in _ALLOWED_MATH_COMMANDS})
    if unsupported:
        raise LatexSafetyError(f"{label} contains unsupported math commands: {', '.join(unsupported)}")
    return text


def validate_citation_key(value: object) -> str:
    key = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9._:+-]+", key):
        raise LatexSafetyError(f"citation key is unsafe for BibTeX: {key!r}")
    return key


__all__ = [
    "LatexSafetyError",
    "contains_cjk",
    "contains_non_english_script",
    "contains_observed_result_language",
    "escape_latex_text",
    "require_english_visible_text",
    "safe_math_expression",
    "validate_citation_key",
]
