"""Personal comments anchored to user-selected PDF text, without model calls."""
from fastapi import APIRouter, HTTPException, Request

from .models import Annotation, AnnotationCreate, AnnotationText


router = APIRouter(prefix="/api/papers/{paper_id}/annotations", tags=["PDF 批注"])


@router.get("", response_model=list[Annotation])
def annotations(paper_id: str, request: Request):
    paper = request.app.state.store.get_paper(paper_id)
    if paper is None:
        raise HTTPException(404, "文献不存在或已移至回收站")
    return paper["annotations"]


@router.post("", response_model=Annotation, status_code=201)
def create(paper_id: str, value: AnnotationCreate, request: Request):
    try:
        result = request.app.state.store.create_annotation(paper_id, value.model_dump())
    except ValueError as error:
        raise HTTPException(422, "批注页码超出 PDF 范围") from error
    if result is None:
        raise HTTPException(404, "文献不存在或已移至回收站")
    return result


@router.patch("/{annotation_id}", response_model=Annotation)
def edit(paper_id: str, annotation_id: str, value: AnnotationText, request: Request):
    result = request.app.state.store.edit_annotation(paper_id, annotation_id, value.content)
    if result is None:
        raise HTTPException(404, "批注不存在或所属文献已移至回收站")
    return result


@router.delete("/{annotation_id}", status_code=204)
def delete(paper_id: str, annotation_id: str, request: Request):
    if not request.app.state.store.delete_annotation(paper_id, annotation_id):
        raise HTTPException(404, "批注不存在或所属文献已移至回收站")
