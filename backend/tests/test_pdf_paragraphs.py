from types import SimpleNamespace

from backend.pdf_paragraphs import SourceText, extract_source, group_lines, plain_paragraphs, positioned_lines
from backend.translation_alignment import source_blocks


def line(text, x=50, y=700, font=10):
    return {"text": text, "x": x, "y": y, "font": font}


def test_indented_paragraphs_keep_all_sentences_regardless_of_length():
    lines = [line("Abstract\u2014A complete long abstract starts here.", x=60)]
    lines.extend(line(f"The same paragraph contains sentence number {index} and ends with a period.", y=700-index*12) for index in range(1, 30))
    lines.extend([line("Index Terms\u2014Deep learning, resource allocation,", x=60, y=325), line("edge inference and network optimization.", y=313)])
    groups = group_lines(lines, 600)
    assert len(groups) == 2
    assert groups[0].count("\n") == 29
    assert len(groups[0]) > 1100
    assert groups[1].count("\n") == 1


def test_first_line_indent_distinguishes_real_paragraph_without_blank_lines():
    lines = [line("The first paragraph starts with a conventional indent.", x=60),
             line("It continues on another line with more than one sentence.", y=688),
             line("Here begins the second paragraph in the same column.", x=60, y=676),
             line("Its final line has normal alignment and ends here.", y=664)]
    assert len(group_lines(lines, 600)) == 2


def test_drop_cap_is_attached_and_line_break_hyphenation_does_not_split():
    lines = [line("W", x=320, font=22), line("ITH the development of mobile edge comput-", x=338, y=700),
             line("ing, many neural inference applications have emerged.", x=320, y=688),
             line("The second natural paragraph starts here.", x=330, y=676)]
    groups = group_lines(lines, 600)
    assert len(groups) == 2
    assert groups[0].startswith("W\nITH")


def test_inline_math_font_changes_do_not_cut_prose_and_display_formula_stays_whole():
    lines = [line("We study the queueing model for neural inference tasks."),
             line("The resource parameter m1 affects the total inference delay.", y=688, font=7.5),
             line("The remaining explanatory sentence continues in normal font.", y=676),
             line("T =", x=120, y=652), line("(", x=145, y=655, font=17),
             line("1 / \u03bc + \u03bb", x=155, y=652, font=8), line(") (1)", x=195, y=648),
             line("where the service rate is constrained by available resources.", y=625)]
    groups = group_lines(lines, 600)
    assert len(groups) == 3
    assert "normal font" in groups[0]
    assert groups[1] == "T =\n(\n1 / \u03bc + \u03bb\n) (1)"


def test_new_column_and_vertical_gap_are_boundaries_without_interleaving():
    lines = [line("The paragraph ends at the bottom of the first column.", y=80),
             line("A different column starts at the top right side.", x=320, y=700),
             line("The next row continues this same right-column paragraph.", x=320, y=688),
             line("A paragraph separated by substantial vertical whitespace.", x=320, y=650)]
    assert len(group_lines(lines, 600)) == 3


def test_plain_fallback_preserves_long_paragraph_and_inline_abstract_label():
    text = "I. INTRODUCTION\n" + "One paragraph has several sentences.\n" * 40 + "\nAbstract\u2014Another complete unit.\nIt must not be split here."
    groups = plain_paragraphs(text)
    assert len(groups) == 3
    assert groups[1].count("\n") == 39
    assert groups[2].startswith("Abstract\u2014")


def test_visitor_does_not_change_source_text_or_ligatures_and_attaches_layout():
    fragments = [("Abstract\u2014An example of ef\ufb01cient inference.\n", 60, 700),
                 ("The same paragraph continues on a second line.\n", 50, 688),
                 ("A new paragraph begins with first-line indentation.", 60, 676)]

    class Page:
        mediabox = SimpleNamespace(width=600)

        def extract_text(self, visitor_text):
            for text, x, y in fragments:
                visitor_text(text, [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, x, y], None, 10)
            return "".join(item[0] for item in fragments)

    result = extract_source(Page())
    assert isinstance(result, SourceText)
    assert result == "".join(item[0] for item in fragments)
    assert len(source_blocks(result)) == 2
    assert "\ufb01" in result


def test_position_mismatch_falls_back_without_losing_text():
    assert positioned_lines([("wrong\n", 50, 700, 10)], "actual text") == []


def test_explicit_blank_line_is_preserved_as_boundary_even_without_indent():
    text = "The first paragraph has regular body text.\n\nThe second paragraph has regular body text."
    fragments = [("The first paragraph has regular body text.\n\n", 50, 700, 10),
                 ("The second paragraph has regular body text.", 50, 688, 10)]
    lines = positioned_lines(fragments, text)
    assert lines[1]["blank_before"]
    assert len(group_lines(lines, 600)) == 2
