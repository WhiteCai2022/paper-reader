"""Recover paragraph boundaries without changing the extracted source or cache digest."""

import math
import re
from statistics import median

from pypdf import mult


LABEL = re.compile(r"^(?:Abstract|Index\s+Terms|Keywords)\b", re.I)
STANDALONE = re.compile(r"^(?:(?:[IVXLC]+\.|\d+(?:\.\d+)*\.?)\s+[A-Z][A-Z\s,:&()/\-]{2,100}|Abstract|References|Acknowledg(?:ment|ement)s?)$", re.I)


def math_line(text):
    words = re.findall(r"[A-Za-z]{2,}", text)
    return len(words) < 3 and (bool(re.search(r"[=+\u2200-\u22ff\u0370-\u03ff{}()\[\]]", text))
                               or len(text.strip()) < 4)


class SourceText(str):
    def __new__(cls, text, paragraphs):
        value = super().__new__(cls, text)
        value.paragraphs = paragraphs
        return value


def plain_paragraphs(text):
    paragraphs, current = [], []
    for raw in text.splitlines():
        line = raw.strip()
        standalone = bool(STANDALONE.fullmatch(line)) and len(line) < 110
        if not line or standalone or (LABEL.match(line) and current):
            if current:
                paragraphs.append("\n".join(current))
            current = []
        if line:
            current.append(line)
        if standalone:
            paragraphs.append("\n".join(current))
            current = []
    if current:
        paragraphs.append("\n".join(current))
    return paragraphs


def positioned_lines(fragments, text):
    lines, parts, positions = [], [], []
    blank_before = False

    def flush():
        nonlocal blank_before
        line = "".join(parts).replace("\x00", "").strip()
        if line:
            if not positions:
                return False
            main = max(positions, key=lambda item: item[3])
            lines.append({"text": line, "x": min(item[0] for item in positions), "y": main[1], "font": main[2], "blank_before": blank_before})
            blank_before = False
        else:
            blank_before = True
        parts.clear()
        positions.clear()
        return True

    for value, x, y, font in fragments:
        for part in value.splitlines(keepends=True):
            parts.append(part.rstrip("\r\n"))
            if part.strip():
                positions.append((x, y, font, len(part.strip())))
            if part.endswith(("\n", "\r")) and not flush():
                return []
    if not flush():
        return []
    original = [line.strip() for line in text.splitlines() if line.strip()]
    return lines if [line["text"] for line in lines] == original else []


def group_lines(lines, width):
    if not lines:
        return []
    body_sizes = [line["font"] for line in lines if len(line["text"]) >= 35 and line["font"] > 0]
    body = median(body_sizes) if body_sizes else 10
    # IEEE-like columns have a shared flush-left edge and a small first-line indent.
    edges = {}
    for column in (0, 1):
        candidates = [line["x"] for line in lines if (line["x"] >= width * .48) == bool(column)
                      and len(line["text"]) >= 35 and .65 * body <= line["font"] <= 1.25 * body]
        if candidates:
            edges[column] = min(candidates)
    paragraphs, current, previous = [], [], None
    for line in lines:
        text, font = line["text"], max(1, line["font"])
        column = int(line["x"] >= width * .48)
        edge = edges.get(column, line["x"])
        indent = line["x"] - edge
        standalone = bool(STANDALONE.fullmatch(text)) and len(text) < 110
        boundary = False
        if previous:
            prev_font = max(1, previous["font"])
            gap = previous["y"] - line["y"]
            jumped = gap < -max(font, prev_font) * .8
            spaced = gap > max(font, prev_font) * 1.65
            font_change = (max(font, prev_font) > 1.4 * body
                           and max(font, prev_font) / min(font, prev_font) > 1.22)
            indented = (.4 * font <= indent <= 2.2 * font and font <= 1.25 * body
                        and not re.match(r"^\[\d+\]", previous["text"])
                        and not previous["text"].endswith(("-", "\u00ad")))
            boundary = bool(line.get("blank_before")) or standalone or bool(LABEL.match(text)) or jumped or spaced or font_change or indented
            current_math, previous_math = math_line(text), math_line(previous["text"])
            if current_math and previous_math:
                boundary = gap > body * 6 or (column != int(previous["x"] >= width * .48) and gap < -body * 4)
            elif current_math != previous_math:
                boundary = True
            if re.fullmatch(r"[A-Z]", previous["text"]) and re.match(r"^[A-Z]{2,}\b", text):
                boundary = False
        if boundary and current:
            paragraphs.append("\n".join(current))
            current = []
        current.append(text)
        if standalone:
            paragraphs.append("\n".join(current))
            current = []
        previous = line
    if current:
        paragraphs.append("\n".join(current))
    return paragraphs


def extract_source(page):
    fragments = []

    def visitor(text, cm, tm, font_dictionary, font_size):
        if not text:
            return
        try:
            matrix = mult(tm, cm)
            font = abs(font_size) * math.hypot(matrix[0], matrix[1])
        except (TypeError, ValueError, OverflowError):
            return
        if not all(math.isfinite(value) for value in (*matrix, font)):
            return
        fragments.append((text, matrix[4], matrix[5], font))

    text = page.extract_text(visitor_text=visitor) or ""
    text = "\n".join(line.rstrip() for line in text.replace("\x00", "").splitlines()).strip()
    lines = positioned_lines(fragments, text)
    paragraphs = group_lines(lines, float(page.mediabox.width)) if lines else plain_paragraphs(text)
    return SourceText(text, paragraphs)
