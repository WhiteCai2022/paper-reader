"""Exact quote alignment allowing PDF typography, never fuzzy or semantic matching."""

import re
import unicodedata


WRAP_MARKER = "\x00"
LINE_HYPHEN = re.compile(r"(?<=[^\W\d_])[-\u2010\u2011][ \t]*\r?\n[ \t]*(?=[^\W\d_])")
SOFT_HYPHEN = re.compile(r"\u00ad(?:[ \t]*\r?\n[ \t]*)?")


def _canonical(text):
    characters, offsets = [], []
    for index, character in enumerate(text):
        # Expand typographic ligatures/width only; never flatten superscripts, subscripts or math alphabets.
        compatible = "\ufb00" <= character <= "\ufb06" or "\uff01" <= character <= "\uff5e"
        for normalized in unicodedata.normalize("NFKC", character) if compatible else character:
            characters.append(normalized)
            offsets.append((index, index + 1))
    value = "".join(characters)
    wraps = {}
    for match in LINE_HYPHEN.finditer(value):
        left, right = match.start(), match.end()
        while left and value[left - 1].isalpha():
            left -= 1
        while right < len(value) and value[right].isalpha():
            right += 1
        if match.start() - left + right - match.end() >= 5:
            wraps[match.start()] = match.end()
    result, positions, index = [], [], 0
    while index < len(value):
        soft = SOFT_HYPHEN.match(value, index)
        if soft:
            index = soft.end()
            continue
        if index in wraps:
            end = wraps[index]
            result.append(WRAP_MARKER)
            positions.append((offsets[index][0], offsets[end - 1][1]))
            index = end
            continue
        character = value[index]
        if character.isspace():
            if result and result[-1] == " ":
                positions[-1] = (positions[-1][0], offsets[index][1])
            else:
                result.append(" ")
                positions.append(offsets[index])
        else:
            result.append("-" if character in {"\u2010", "\u2011"} else character)
            positions.append(offsets[index])
        index += 1
    return "".join(result), positions


def quote_matches(quote, source):
    """Return up to two original source slices. Multiple matches are ambiguous."""
    if WRAP_MARKER in quote or WRAP_MARKER in source:
        return []
    query = _canonical(quote)[0].strip()
    text, positions = _canonical(source)
    if not query:
        return []
    parts = []
    for index, character in enumerate(query):
        parts.append("[-\x00]?" if character == WRAP_MARKER else "[-\x00]" if character == "-" else re.escape(character))
        if index + 1 < len(query) and character.isalpha() and query[index + 1].isalpha():
            parts.append("\x00?")
    pattern = re.compile("".join(parts))
    matches, start = [], 0
    while match := pattern.search(text, start):
        start = match.start() + 1
        if match.start() and ((query[0].isalpha() and text[match.start() - 1].isalpha())
                              or (query[0].isdecimal() and text[match.start() - 1].isdecimal())):
            continue
        if match.end() < len(text) and ((query[-1].isalpha() and text[match.end()].isalpha())
                                      or (query[-1].isdecimal() and text[match.end()].isdecimal())):
            continue
        matches.append(source[positions[match.start()][0]:positions[match.end() - 1][1]])
        if len(matches) == 2:
            break
    return matches
