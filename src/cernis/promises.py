"""The no-promise rule (DESIGN.md principle 3).

A recommendation may say what to change and why. It may never say what will
happen as a result. :func:`find_outcome_language` checks a string against
:data:`FORBIDDEN_PHRASES`; the test suite runs it over every recommendation
template, so a promise is a build failure, not a style note.

A phrase list is a floor, not a proof: it catches the common ways of
predicting an outcome, and review catches the rest. When review finds one the
list missed, add it here.
"""

import re

PREDICTIVE_MODALS: tuple[str, ...] = ("will", "would", "should", "could", "may", "might")
"""Modal verbs that, followed by an outcome verb, predict a result."""

OUTCOME_VERBS: tuple[str, ...] = (
    "attract",
    "boost",
    "drive",
    "grow",
    "help",
    "improve",
    "increase",
    "lift",
    "raise",
    "rank",
)
"""Verbs that describe a result rather than an action."""

OUTCOME_PHRASES: tuple[str, ...] = (
    "boost",
    "better ranking",
    "drive traffic",
    "guarantee",
    "higher ranking",
    "improve discoverability",
    "improve ranking",
    "improve visibility",
    "improve your ranking",
    "increase traffic",
    "increase visibility",
    "more citations",
    "more clicks",
    "more impressions",
    "more readers",
    "more shares",
    "more traffic",
    "more views",
    "more visibility",
    "rank better",
    "rank higher",
)
"""Outcome phrases that are forbidden with or without a modal verb."""

FORBIDDEN_PHRASES: tuple[str, ...] = (
    tuple(f"{modal} {verb}" for modal in PREDICTIVE_MODALS for verb in OUTCOME_VERBS)
    + OUTCOME_PHRASES
)
"""Every phrase that recommendation text must not contain.

Matching ignores case and treats any run of whitespace as one space. Each
word matches at the start of a word with any ending, so ``boost`` also
matches ``boosts`` and ``boosted``, and ``improve ranking`` also matches
``improves rankings``. Up to two other words may sit between a phrase's
words, so ``will improve`` also matches ``will likely improve`` and
``will very likely improve``. The contraction ``'ll`` is read as ``will``.
"""


_GAP = r"\s+(?:\w+\s+){0,2}?"


def _phrase_pattern(phrase: str) -> str:
    """Build the regular expression for one phrase.

    :param phrase: A phrase from :data:`FORBIDDEN_PHRASES`.
    :return: A pattern matching the phrase's words with any word ending,
        allowing up to two other words between them.
    """
    return _GAP.join(rf"{re.escape(word)}\w*" for word in phrase.split())


_FORBIDDEN = re.compile(
    r"\b(?:" + "|".join(_phrase_pattern(p) for p in FORBIDDEN_PHRASES) + r")\b",
    re.IGNORECASE,
)
_CONTRACTED_WILL = re.compile("(?<=\\w)['\u2019]ll\\b", re.IGNORECASE)


def find_outcome_language(text: str) -> tuple[str, ...]:
    """Find every forbidden outcome phrase in ``text``.

    :param text: Recommendation text, such as a template's action or
        rationale.
    :return: The matching passages, in order of appearance; empty when the
        text makes no promise.
    """
    normalized = _CONTRACTED_WILL.sub(" will", text)
    return tuple(match.group(0) for match in _FORBIDDEN.finditer(normalized))
