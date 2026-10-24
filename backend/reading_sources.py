"""Deterministic, verbatim source passages for model-selected evidence references."""
import hashlib
import re

from .quote_matching import quote_matches


WORKFLOW = "whole-paper-topics-v1"
PASSAGE_CHARS = 900


def source_catalog(pages):
    catalog = []
    for page in pages:
        text, spans, start = page["text"], [], 0
        while start < len(text):
            end = min(len(text), start + PASSAGE_CHARS)
            if end < len(text):
                boundaries = list(re.finditer(r"[。！？.!?](?:\s+|(?=[\u3400-\u9fff]))|\n\s*\n|\s+", text[start + PASSAGE_CHARS // 2:end]))
                if boundaries:
                    end = start + PASSAGE_CHARS // 2 + boundaries[-1].end()
            if spans and len(text) - start < 10:
                spans[-1][1] = len(text)
                break
            spans.append([start, end])
            start = end
        passages = []
        for start, end in spans:
            quote = text[start:end]
            if len(quote.strip()) < 10:
                continue
            digest = hashlib.sha256(quote.encode()).hexdigest()[:10]
            passages.append({"source_id": f"p{page['page']}-{start}-{end}-{digest}", "start": start, "end": end, "text": quote})
        catalog.append({"page": page["page"], "passages": passages})
    return catalog


def passage_lookup(catalog, pages):
    sources = {page["page"]: page["text"] for page in pages}
    result = {}
    for page in catalog:
        text = sources.get(page["page"], "")
        for passage in page["passages"]:
            if (passage["source_id"] in result or type(passage["start"]) is not int or type(passage["end"]) is not int
                    or not 0 <= passage["start"] < passage["end"] <= len(text)
                    or text[passage["start"]:passage["end"]] != passage["text"]):
                raise ValueError("Frozen source passage does not match its PDF text")
            result[passage["source_id"]] = {"page": page["page"], "quote": passage["text"].strip()}
    return result


def resolve_evidence(value, passages, pages):
    """Only PDF-backed references survive; a bad reference must not discard a sound note body."""
    resolved, adjustments, warnings = [], set(), []
    if not isinstance(value, list):
        return [], adjustments, [{"code": "evidence_source_schema", "message": "证据字段不是数组，未采纳其中的引用；请对照原文核对正文。"}]
    if len(value) > 32:
        warnings.append({"code": "evidence_count", "message": "证据超过 32 条，仅处理前 32 条；请核对引用是否充分。"})
    sources = {page["page"]: page["text"] for page in pages}
    for index, reference in enumerate(value[:32], 1):
        if isinstance(reference, str):
            reference = {"source_id": reference}
            adjustments.add("evidence_string_id_normalized")
        source, code = None, "evidence_source_schema"
        if isinstance(reference, dict):
            identifier = reference.get("source_id")
            if isinstance(identifier, str) and identifier.strip():
                source = passages.get(identifier.strip())
                code = "evidence_source_id"
                if source is not None and (set(reference) - {"source_id", "label"} or identifier != identifier.strip()):
                    adjustments.add("evidence_fields_normalized")
            elif "source_id" not in reference and isinstance(reference.get("quote"), str) and 10 <= len(reference["quote"].strip()) <= 2000:
                # Compatibility with the export schema: exact local text matching, never semantic repair.
                page = reference.get("page")
                matches = [(page, match) for match in quote_matches(reference["quote"], sources[page])] if type(page) is int and page in sources else []
                if not matches:
                    for number, text in sources.items():
                        matches.extend((number, match) for match in quote_matches(reference["quote"], text))
                        if len(matches) > 1:
                            break
                if len(matches) == 1 and len(matches[0][1]) <= 2000:
                    source = {"page": matches[0][0], "quote": matches[0][1]}
                    adjustments.add("evidence_quote_resolved")
                code = "evidence_quote"
        if source is None:
            warnings.append({"code": code, "message": f"第 {index} 条证据无法从本篇原文可靠定位，已移除该引用；未把它当作原文证据，正文需人工复核。"})
            continue
        label = reference.get("label", "")
        if not isinstance(label, str):
            label = ""
            adjustments.add("evidence_label_normalized")
        if len(label) > 200:
            label = label[:200]
            adjustments.add("evidence_label_normalized")
        resolved.append({**source, "label": label})
    return resolved, adjustments, warnings
