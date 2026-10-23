"""Local PDF bibliographic metadata and explicit, DOI-only Crossref lookup."""

import json
import math
import re
import unicodedata
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from pypdf import PdfReader


DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s<>\"\\]+", re.IGNORECASE)
FIELDS = ("title", "authors", "venue", "year", "doi")
MAX_RECORD_BYTES = 1024 * 1024
PRISM_NAMESPACES = [f"http://prismstandard.org/namespaces/basic/{version}/" for version in ("3.0", "2.1", "2.0", "1.2")]


def normalize_doi(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.IGNORECASE)
    if value and (len(value) > 500 or not DOI_PATTERN.fullmatch(value) or any(ord(char) < 33 for char in value)):
        raise ValueError("Invalid DOI")
    return value


def text(value, limit=500) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", "".join(char for char in value if ord(char) >= 32 or char in "\r\n\t")).strip()[:limit]


def usable_title(value) -> str:
    value = text(value)
    if len(value) < 3 or re.search(r"\.(?:pdf|docx?|tex|ps)$", value, re.IGNORECASE):
        return ""
    if re.match(r"^(?:untitled|microsoft (?:word|powerpoint)|document\d*|unknown|latex)$", value, re.IGNORECASE):
        return ""
    return value


def year_of(value):
    match = re.search(r"(?<!\d)(18\d{2}|19\d{2}|20\d{2}|21\d{2}|2200)(?!\d)", str(value or ""))
    return int(match[0]) if match else None


def find_dois(value):
    result = []
    for match in DOI_PATTERN.finditer(str(value or "")):
        candidate = match[0].rstrip(".,;")
        while candidate.endswith(")") and candidate.count(")") > candidate.count("("):
            candidate = candidate[:-1]
        try:
            candidate = normalize_doi(candidate)
        except ValueError:
            continue
        if candidate.casefold() not in {item.casefold() for item in result}:
            result.append(candidate)
    return result


def node_text(node):
    if node.nodeType in {node.TEXT_NODE, node.CDATA_SECTION_NODE, node.ATTRIBUTE_NODE}:
        return node.nodeValue or ""
    return " ".join(node_text(child) for child in node.childNodes)


def prism_value(xmp, name):
    for namespace in PRISM_NAMESPACES:
        for node in xmp.rdf_root.getElementsByTagNameNS(namespace, name):
            if value := text(node_text(node), 1000):
                return value
        for node in xmp.rdf_root.getElementsByTagNameNS("*", "Description"):
            if node.hasAttributeNS(namespace, name):
                return text(node.getAttributeNS(namespace, name), 1000)
    return ""


def publication(venue, volume="", issue="", pages=""):
    if not venue:
        return ""
    suffix = str(volume or "") + (f"({issue})" if issue else "")
    if pages:
        suffix += (":" if suffix else "pp. ") + str(pages)
    return text(str(venue) + (" " + suffix if suffix else ""), 1000)


def font_title(fragments):
    groups = {}
    for size, fragment in fragments:
        if 11 <= size <= 48 and len(fragment.strip()) >= 2 and not fragment.strip().isdigit():
            groups.setdefault(round(size * 2) / 2, []).append(fragment)
    for size in sorted(groups, reverse=True):
        candidate = usable_title(" ".join(groups[size]))
        if not candidate or len(candidate) > 450 or len(candidate.split()) < 4:
            continue
        if re.search(r"abstract|contents lists|journal homepage|\bVOL\.|\bISSN\b|https?://", candidate, re.IGNORECASE):
            continue
        return candidate
    return ""


def local_metadata(path, filename):
    result = {"title": "", "authors": "", "venue": "", "year": None, "doi": "", "sources": {}, "warnings": []}

    def put(field, value, source):
        if value not in (None, "") and not result[field]:
            result[field] = value
            result["sources"][field] = source

    reader = PdfReader(str(path), strict=True)
    info = reader.metadata or {}
    put("title", usable_title(info.get("/Title")), "pdf")
    put("authors", text(info.get("/Author"), 5000), "pdf")
    for key, value in info.items():
        if str(key).lower() in {"/doi", "/prism:doi"}:
            candidates = find_dois(value)
            if len(candidates) == 1:
                put("doi", candidates[0], "pdf")
        if str(key).lower() in {"/journal", "/journalname", "/publicationname"}:
            put("venue", text(value, 1000), "pdf")
        if str(key).lower() in {"/publicationdate", "/year"}:
            put("year", year_of(value), "pdf")

    try:
        raw = reader.root_object.get("/Metadata")
        if raw:
            raw = raw.get_object().get_data()
            if len(raw) > 2 * MAX_RECORD_BYTES or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
                raise ValueError("Unsafe or oversized XMP")
        xmp = reader.xmp_metadata
        if xmp:
            titles = xmp.dc_title or {}
            title = titles.get("x-default") or titles.get("") or next(iter(titles.values()), "")
            if usable_title(title):
                result["title"] = usable_title(title)
                result["sources"]["title"] = "xmp"
            creators = list(dict.fromkeys(text(author, 500) for author in xmp.dc_creator or [] if text(author, 500)))
            if creators:
                result["authors"] = text("; ".join(creators), 5000)
                result["sources"]["authors"] = "xmp"
            venue = prism_value(xmp, "publicationName")
            start, end = prism_value(xmp, "startingPage"), prism_value(xmp, "endingPage")
            pages = start + ("-" + end if end and end != start else "")
            put("venue", publication(venue, prism_value(xmp, "volume"), prism_value(xmp, "issueIdentifier") or prism_value(xmp, "number"), pages), "xmp")
            put("year", year_of(prism_value(xmp, "publicationDate") or prism_value(xmp, "coverDisplayDate")), "xmp")
            identifiers = xmp.dc_identifier or []
            if isinstance(identifiers, str):
                identifiers = [identifiers]
            for value in [prism_value(xmp, "doi"), *identifiers]:
                candidates = find_dois(value)
                if len(candidates) == 1:
                    put("doi", candidates[0], "xmp")
    except Exception:
        result["warnings"].append("PDF 的 XMP 元数据不可读取，已保留其他可用信息。")

    fragments = []
    try:
        def visitor(value, _cm, _tm, _font, size):
            if len(fragments) < 2000:
                scale = math.hypot(_tm[2], _tm[3]) * math.hypot(_cm[2], _cm[3])
                fragments.append((float(size) * scale, value))
        first_page = (reader.pages[0].extract_text(visitor_text=visitor) or "")[:60_000]
        put("title", font_title(fragments), "first_page")
        lines = [text(line, 1000) for line in first_page.splitlines() if line.strip()]
        for line in lines[:12]:
            if re.search(r"(?:IEEE|ACM).*\b(?:TRANSACTIONS|JOURNAL|VOL\.)", line, re.IGNORECASE):
                put("venue", re.sub(r"^\d+\s+|\s+\d+$", "", line), "first_page")
                put("year", year_of(line), "first_page")
                break
        if not result["doi"]:
            candidates = find_dois(first_page)
            if len(candidates) == 1:
                put("doi", candidates[0], "first_page")
            elif len(candidates) > 1:
                result["warnings"].append("首页出现多个 DOI，未自动选择，请核对本篇论文的 DOI。")
    except Exception:
        result["warnings"].append("首页文字无法提取，已保留 PDF 内嵌元数据。")
    if not result["title"]:
        put("title", text(filename.rsplit(".", 1)[0].replace("_", " ")) or "Untitled", "filename")
        result["warnings"].append("未识别到可信标题，当前使用文件名。")
    if any(source == "first_page" for source in result["sources"].values()):
        result["warnings"].append("部分信息来自首页候选，请核对后导入。")
    return result


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def crossref_text(value, limit=500):
    parser = PlainText()
    parser.feed(str(value or ""))
    return text(unescape("".join(parser.parts)), limit)


class LookupFailure(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def lookup_doi(doi):
    doi = normalize_doi(doi)
    if not doi:
        raise LookupFailure(422, "请填写有效的 DOI")
    request = Request("https://api.crossref.org/works/" + quote(doi, safe=""), headers={"Accept": "application/json", "User-Agent": "LocalPaperReader/1.0 (DOI metadata lookup)"})
    try:
        with urlopen(request, timeout=6) as response:
            raw = response.read(MAX_RECORD_BYTES + 1)
        if len(raw) > MAX_RECORD_BYTES:
            raise ValueError("Oversized metadata")
        message = json.loads(raw)["message"]
        if not isinstance(message, dict) or not isinstance(message.get("title"), list):
            raise ValueError("Invalid metadata shape")
        if not all(isinstance(value, str) for value in message["title"]):
            raise ValueError("Invalid title")
        if not isinstance(message.get("author", []), list) or not all(isinstance(author, dict) for author in message.get("author", [])):
            raise ValueError("Invalid authors")
        if not isinstance(message.get("container-title", []), list):
            raise ValueError("Invalid publication")
        if normalize_doi(message["DOI"]).casefold() != doi.casefold():
            raise ValueError("DOI mismatch")
        title = crossref_text(next(iter(message.get("title") or []), ""))
        if not title:
            raise ValueError("Missing title")
        authors = []
        for author in message.get("author") or []:
            name = " ".join(str(author.get(part) or "") for part in ("given", "family")).strip() or author.get("name", "")
            if name := crossref_text(name):
                authors.append(name)
        venue = crossref_text(next(iter(message.get("container-title") or []), ""), 1000)
        if not venue:
            venue = crossref_text((message.get("event") or {}).get("name"), 1000)
        year = None
        for field in ("published-print", "published", "published-online", "issued"):
            date = (message.get(field) or {}).get("date-parts") or []
            if date and date[0]:
                year = year_of(str(date[0][0]))
                if year:
                    break
        result = {"title": title, "authors": text("; ".join(dict.fromkeys(authors)), 5000), "venue": publication(venue, crossref_text(message.get("volume")), crossref_text(message.get("issue")), crossref_text(message.get("page") or message.get("article-number"))), "year": year, "doi": normalize_doi(message["DOI"]), "warnings": []}
        result["sources"] = {field: "crossref" for field in FIELDS if result[field] not in (None, "")}
        return result
    except HTTPError as error:
        if error.code == 404:
            raise LookupFailure(404, "Crossref 未找到该 DOI，可手工填写出版信息") from error
        raise LookupFailure(503, "Crossref 暂不可用，已保留当前填写的信息") from error
    except (URLError, TimeoutError, OSError) as error:
        raise LookupFailure(503, "DOI 查询网络不可用或超时，已保留当前填写的信息") from error
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise LookupFailure(502, "DOI 元数据不完整或不匹配，未覆盖当前信息") from error
