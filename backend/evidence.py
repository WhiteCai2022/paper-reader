"""Local quote presence checks, not semantic or scholarly verification."""
from fastapi import APIRouter, HTTPException, Request
from pypdf import PdfReader

from .models import Evidence
from .pdf_paragraphs import extract_source
from .quote_matching import quote_matches


router = APIRouter(tags=["原文证据"])


@router.post("/api/papers/{paper_id}/evidence/check", summary="本地核对原句是否存在，不调用模型、不判断结论正确性")
def check(paper_id: str, evidence: Evidence, request: Request):
    store = request.app.state.store
    paper = store.get_paper(paper_id, detail=False)
    if not paper:
        raise HTTPException(404, "文献不存在或已移至回收站。")
    if evidence.page > paper["page_count"]:
        raise HTTPException(422, "证据页码超出 PDF 范围。")
    try:
        source = store.source(paper_id)
        text = str(extract_source(PdfReader(source["pdf_path"]).pages[evidence.page - 1]))
    except Exception:
        return {"page": evidence.page, "quote": evidence.quote, "status": "unavailable", "matched": False,
                "message": "本页文字暂时无法提取，请对照右侧 PDF 人工核验。"}
    matches = quote_matches(evidence.quote, text)
    occurrences = len(matches)
    status = "matched" if occurrences == 1 else "ambiguous" if occurrences > 1 else "not_found"
    messages = {"matched": "已在本页提取文字中找到原句；这不代表该原句支持解析结论，请继续核验上下文。",
                "ambiguous": "原句在本页重复出现，无法唯一定位，请补充上下文。",
                "not_found": "未在本页提取文字中找到原句，可能是页码、摘录或文字提取有误，请人工核验。"}
    return {"page": evidence.page, "quote": evidence.quote, "status": status, "matched": occurrences == 1,
            "message": messages[status]}
