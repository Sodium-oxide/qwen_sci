"""Stable page-count policy for rendered research-plan reports."""

from __future__ import annotations


DEFAULT_MINIMUM_PAGES = 7
LEGACY_MINIMUM_PAGES = 8


class PagePolicyError(ValueError):
    """Raised when a report page requirement conflicts with the project policy."""


def normalize_minimum_pages(value: object | None) -> int:
    """Return the project page minimum, translating legacy eight-page requests.

    Reports now require at least seven pages.  A former ``8``-page minimum is
    deliberately treated as the legacy spelling of that seven-page policy so
    callers do not pad a report with non-research material merely to fill one
    extra page.  Higher explicit requirements remain available.
    """

    if value is None or (isinstance(value, str) and not value.strip()):
        candidate = DEFAULT_MINIMUM_PAGES
    elif isinstance(value, bool):
        raise PagePolicyError("minimum_pages must be an integer, not a boolean")
    else:
        try:
            candidate = int(value)
        except (TypeError, ValueError) as error:
            raise PagePolicyError("minimum_pages must be an integer") from error
    if candidate == LEGACY_MINIMUM_PAGES:
        return DEFAULT_MINIMUM_PAGES
    if candidate < DEFAULT_MINIMUM_PAGES:
        raise PagePolicyError(
            f"minimum_pages must be at least {DEFAULT_MINIMUM_PAGES}; "
            f"the legacy value {LEGACY_MINIMUM_PAGES} is normalized to {DEFAULT_MINIMUM_PAGES}"
        )
    return candidate


__all__ = [
    "DEFAULT_MINIMUM_PAGES",
    "LEGACY_MINIMUM_PAGES",
    "PagePolicyError",
    "normalize_minimum_pages",
]
