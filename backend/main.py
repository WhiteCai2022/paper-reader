import json
import logging
import os
import re
import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path, PureWindowsPath
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import FileResponse, JSONResponse
from pydantic import ValidationError
from pypdf import PdfReader
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool

from .models import ImportDocument, ImportNote, Metadata, MetadataPatch, Note, NoteCreate, NotePatch
from .models import Paper, PaperDetail, Progress, ProgressPatch
from .models import Category, CategoryAssignment, CategoryInput, CategoryMembers
from .models import DoiQuery, MetadataPreview
from .bibliography import LookupFailure, local_metadata, lookup_doi
from .store import Store
from .reading import reading_task
from .translation import TranslationService, router as translation_router
from .reading_api import ReadingService, router as reading_router
from .library_safety import router as library_safety_router
from .evidence import router as evidence_router
from .trash import router as trash_router
from .annotations import router as annotations_router


APP_DIR = Path(__file__).resolve().parent.parent
MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_IMPORT_BYTES = 10 * 1024 * 1024
LOGGER = logging.getLogger(__name__)
PAGE_HEADING = re.compile(r"^##\s+\[p\.\s*(\d+)(?:\s*[-\u2013\u2014]\s*(\d+))?\]\s+(.+?)\s*$", re.IGNORECASE)
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


def validation_error(error: ValidationError):
    details = []
    for item in error.errors(include_context=False):
        details.append({"type": item["type"], "loc": ["body", *item["loc"]], "msg": item["msg"]})
    raise HTTPException(status_code=422, detail=details)


def validate(model, value):
    try:
        return model.model_validate(value)
    except ValidationError as error:
        validation_error(error)


def validate_note_pages(note: NoteCreate, page_count: int):
    if note.page_start > page_count or note.page_end > page_count:
        raise HTTPException(status_code=422, detail=f"Note pages must be between 1 and {page_count}")
    if any(item.page > page_count for item in note.evidence):
        raise HTTPException(status_code=422, detail=f"Evidence pages must be between 1 and {page_count}")


def filename_only(name: str | None, fallback="document.pdf") -> str:
    name = PureWindowsPath(name or "").name
    name = Path(name).name
    name = "".join(char for char in name if ord(char) >= 32 and char not in '\"<>:|?*')
    return name[:240].strip(" .") or fallback


def inspect_pdf(path: Path):
    try:
        with path.open("rb") as stream:
            if b"%PDF-" not in stream.read(1024):
                raise ValueError("Missing PDF header")
            stream.seek(0)
            reader = PdfReader(stream, strict=True)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDFs are not supported")
            page_count = len(reader.pages)
            if page_count < 1:
                raise ValueError("PDF has no pages")
            try:
                metadata = reader.metadata
                return page_count, (metadata.title if metadata else None), (metadata.author if metadata else None)
            except Exception:
                return page_count, None, None
    except Exception as error:
        raise HTTPException(status_code=422, detail="The file must be a readable, unencrypted PDF with at least one page") from error


async def save_pdf_upload(file, path):
    total = 0
    with path.open("xb") as output:
        while chunk := await file.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="PDF exceeds the 100 MB upload limit")
            output.write(chunk)


def inspect_upload_metadata(path, filename):
    page_count, _, _ = inspect_pdf(path)
    try:
        result = local_metadata(path, filename)
    except Exception:
        result = {"title": Path(filename).stem[:500], "authors": "", "venue": "", "year": None, "doi": "", "sources": {"title": "filename"}, "warnings": ["未能读取内嵌元数据，请核对后手工填写。"]}
    return {**result, "page_count": page_count}


def metadata_from_paper(paper):
    return {name: paper[name] for name in Metadata.model_fields}


def merge_metadata(paper, patch):
    current = metadata_from_paper(paper)
    current.update(patch)
    cleaned = validate(Metadata, current).model_dump()
    return {name: cleaned[name] for name in patch}


def comment_json(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def export_markdown(paper):
    document = {"schema_version": 1, "paper": metadata_from_paper(paper)}
    parts = [f"<!-- paper-reader: {comment_json(document)} -->", "", f"# {paper['title']}", ""]
    for note in paper["notes"]:
        pages = str(note["page_start"]) if note["page_start"] == note["page_end"] else f"{note['page_start']}-{note['page_end']}"
        note_meta = {name: note[name] for name in ("kind", "sort_order", "completed", "evidence", "verification_status")}
        parts.extend([f"## [p. {pages}] {note['title']}", f"<!-- paper-reader-note: {comment_json(note_meta)} -->", "", note["content"], ""])
    return "\n".join(parts)


def parse_markdown(text, fallback_title):
    lines = text.splitlines()
    paper_metadata = None
    first = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first is not None and lines[first].startswith("<!-- paper-reader:"):
        match = re.fullmatch(r"<!-- paper-reader: (.+) -->", lines[first])
        if not match:
            raise HTTPException(status_code=422, detail="Malformed paper metadata comment")
        try:
            header = json.loads(match[1])
        except (ValueError, TypeError) as error:
            raise HTTPException(status_code=422, detail="Invalid paper metadata JSON") from error
        if not isinstance(header, dict) or header.get("schema_version") != 1:
            raise HTTPException(status_code=422, detail="Unsupported schema_version")
        paper_metadata = header.get("paper")
        lines.pop(first)

    sections = []
    current = None
    prefix = []
    fence_char, fence_length = None, 0
    for line in lines:
        fence = FENCE.match(line)
        if fence:
            marker = fence[1]
            if fence_char is None:
                fence_char, fence_length = marker[0], len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                fence_char = None
        heading = PAGE_HEADING.match(line) if fence_char is None and not fence else None
        if heading:
            current = {
                "title": heading[3], "page_start": int(heading[1]),
                "page_end": int(heading[2] or heading[1]), "sort_order": len(sections), "lines": [],
            }
            sections.append(current)
        elif current is None:
            prefix.append(line)
        else:
            current["lines"].append(line)

    if not sections:
        if paper_metadata is not None and not re.sub(r"^# [^\n]*(?:\n|$)", "", "\n".join(lines).strip(), count=1).strip():
            return {"schema_version": 1, "paper": paper_metadata, "notes": []}
        return {"schema_version": 1, "paper": paper_metadata, "notes": [{
            "title": fallback_title, "page_start": 1, "page_end": 1, "content": "\n".join(lines).strip("\n"),
        }]}

    notes = []
    # Preserve introductory prose while ignoring the export's document-level title.
    introduction = "\n".join(prefix).strip()
    introduction = re.sub(r"^# [^\n]*(?:\n|$)", "", introduction, count=1).strip()
    if introduction:
        notes.append({"title": "Overview", "page_start": 1, "page_end": 1, "content": introduction, "sort_order": 0})
    for section in sections:
        content_lines = section.pop("lines")
        first_content = next((index for index, line in enumerate(content_lines) if line.strip()), None)
        if first_content is not None and content_lines[first_content].startswith("<!-- paper-reader-note:"):
            match = re.fullmatch(r"<!-- paper-reader-note: (.+) -->", content_lines[first_content])
            if not match:
                raise HTTPException(status_code=422, detail="Malformed note metadata comment")
            try:
                note_metadata = json.loads(match[1])
            except (ValueError, TypeError) as error:
                raise HTTPException(status_code=422, detail="Invalid note metadata JSON") from error
            if not isinstance(note_metadata, dict) or not set(note_metadata).issubset({"kind", "completed", "sort_order", "evidence", "verification_status"}):
                raise HTTPException(status_code=422, detail="Unsupported note metadata")
            section.update(note_metadata)
            content_lines.pop(first_content)
        section["content"] = "\n".join(content_lines).strip("\n")
        if introduction:
            section["sort_order"] = len(notes)
        notes.append(section)
    return {"schema_version": 1, "paper": paper_metadata, "notes": notes}


def load_seeds(store):
    seed_file = store.data_dir / "seed.json"
    if not seed_file.is_file():
        return
    try:
        seeds = json.loads(seed_file.read_text(encoding="utf-8-sig"))
        if not isinstance(seeds, list):
            raise ValueError("seed.json must contain an array")
    except (OSError, ValueError):
        LOGGER.exception("Could not load seed.json")
        return
    for seed in seeds:
        try:
            if not isinstance(seed, dict) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", seed.get("id", "")):
                raise ValueError("Invalid seed id")
            if store.get_paper(seed["id"], detail=False) or store.seed_is_deleted(seed["id"]):
                continue
            source = Path(seed["pdf_path"])
            if not source.is_absolute() or not source.is_file():
                raise ValueError("Seed PDF must be an existing absolute path")
            page_count, _, _ = inspect_pdf(source)
            metadata = Metadata.model_validate({name: seed[name] for name in Metadata.model_fields if name in seed})
            notes = [ImportNote.model_validate(note) for note in seed.get("notes", [])]
            for note in notes:
                validate_note_pages(note, page_count)
            store.create_paper(metadata.model_dump(), source, page_count, source.name, False, seed["id"], [note.model_dump(exclude={"id"}) for note in notes])
        except (KeyError, TypeError, ValueError, OSError, HTTPException):
            LOGGER.exception("Skipping invalid seed entry")


def origin_allowed(request):
    try:
        origin = urlsplit(request.headers["origin"])
        host = urlsplit("//" + request.headers.get("host", ""))
        loopback = {"localhost", "127.0.0.1"}
        if origin.scheme not in {"http", "https"} or origin.hostname not in loopback or host.hostname not in loopback:
            return False
        if origin.username or origin.password or origin.query or origin.fragment or origin.path not in {"", "/"}:
            return False
        default = 443 if request.url.scheme == "https" else 80
        return origin.scheme == request.url.scheme and (origin.port or default) == (host.port or default)
    except (ValueError, KeyError):
        return False


def create_app(data_dir=None, frontend_dist=None):
    data_dir = Path(data_dir or os.environ.get("PAPER_READER_DATA_DIR", APP_DIR / "data"))
    frontend_dist = Path(frontend_dist or APP_DIR / "frontend" / "dist").resolve()

    @asynccontextmanager
    async def lifespan(application):
        application.state.store = Store(data_dir)
        load_seeds(application.state.store)
        application.state.translator = TranslationService(application.state.store)
        application.state.reader = ReadingService(application.state.translator)
        try:
            yield
        finally:
            application.state.translator.close()

    application = FastAPI(title="Local Paper Reader", version="1.0.0", docs_url=None, redoc_url=None, openapi_url="/api/openapi.json", lifespan=lifespan)
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1"])

    @application.middleware("http")
    async def protect_origin(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and "origin" in request.headers and not origin_allowed(request):
            return JSONResponse(status_code=403, content={"detail": "Mutating requests must originate from the same local host and port"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def store(request):
        return request.app.state.store

    def get_paper(request, paper_id):
        paper = store(request).get_paper(paper_id)
        if paper is None:
            raise HTTPException(status_code=404, detail="Paper not found")
        return paper

    @application.get("/api/health")
    def health(request: Request):
        return {"status": "ok", "papers_count": len(store(request).list_papers())}

    @application.get("/api/docs", include_in_schema=False)
    def docs():
        return get_swagger_ui_html(openapi_url="/api/openapi.json", title="Paper Reader API", swagger_js_url="/swagger/swagger-ui-bundle.js", swagger_css_url="/swagger/swagger-ui.css", swagger_favicon_url="/swagger/favicon-32x32.png", swagger_ui_parameters={"validatorUrl": None})

    @application.get("/swagger/{asset_name}", include_in_schema=False)
    def swagger_asset(asset_name: str):
        if asset_name not in {"swagger-ui-bundle.js", "swagger-ui.css", "favicon-32x32.png"}:
            raise HTTPException(status_code=404, detail="Asset not found")
        for directory in (frontend_dist / "swagger", APP_DIR / "frontend" / "public" / "swagger"):
            candidate = directory / asset_name
            if candidate.is_file():
                return FileResponse(candidate)
        raise HTTPException(status_code=404, detail="Swagger asset not installed")

    @application.get("/api/papers", response_model=list[Paper])
    def papers(request: Request):
        return store(request).list_papers()

    @application.post("/api/papers/metadata", response_model=MetadataPreview)
    async def preview_pdf_metadata(request: Request, file: Annotated[UploadFile, File()]):
        temporary = store(request).uploads_dir / f"metadata-{uuid.uuid4().hex}.part"
        try:
            await save_pdf_upload(file, temporary)
            return await run_in_threadpool(inspect_upload_metadata, temporary, filename_only(file.filename))
        finally:
            await file.close()
            temporary.unlink(missing_ok=True)

    @application.post("/api/metadata/doi", response_model=MetadataPreview)
    def query_doi(value: DoiQuery):
        try:
            return lookup_doi(value.doi)
        except LookupFailure as error:
            raise HTTPException(status_code=error.status, detail=str(error)) from error

    @application.get("/api/categories", response_model=list[Category])
    def categories(request: Request):
        return store(request).list_categories()

    @application.post("/api/categories", response_model=Category, status_code=201)
    def create_category(value: CategoryInput, request: Request):
        try:
            return store(request).create_category(value.name)
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="分类名称已存在") from error

    @application.patch("/api/categories/{category_id}", response_model=Category)
    def rename_category(category_id: str, value: CategoryInput, request: Request):
        if category_id == "default":
            raise HTTPException(status_code=409, detail="默认分类不能重命名")
        try:
            category = store(request).rename_category(category_id, value.name)
        except sqlite3.IntegrityError as error:
            raise HTTPException(status_code=409, detail="分类名称已存在") from error
        if category is None:
            raise HTTPException(status_code=404, detail="分类不存在")
        return category

    @application.delete("/api/categories/{category_id}", status_code=204)
    def delete_category(category_id: str, request: Request):
        if category_id == "default":
            raise HTTPException(status_code=409, detail="默认分类不能删除")
        if not store(request).delete_category(category_id):
            raise HTTPException(status_code=404, detail="分类不存在")
        return Response(status_code=204)

    @application.put("/api/papers/{paper_id}/categories", response_model=PaperDetail)
    def assign_categories(paper_id: str, value: CategoryAssignment, request: Request):
        try:
            paper = store(request).set_paper_categories(paper_id, value.category_ids)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="所选分类已不存在，请刷新分类列表") from error
        if paper is None:
            raise HTTPException(status_code=404, detail="Paper not found")
        return paper

    @application.put("/api/categories/{category_id}/papers", response_model=Category)
    def assign_category_papers(category_id: str, value: CategoryMembers, request: Request):
        if category_id == "default":
            raise HTTPException(status_code=409, detail="默认分类由未归类文献自动组成")
        try:
            category = store(request).set_category_papers(category_id, value.paper_ids)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="所选文献已不存在，请刷新文献库") from error
        if category is None:
            raise HTTPException(status_code=404, detail="分类不存在")
        return category

    @application.get("/api/papers/{paper_id}", response_model=PaperDetail)
    def paper_detail(paper_id: str, request: Request):
        return get_paper(request, paper_id)

    @application.post("/api/papers", response_model=PaperDetail, status_code=201)
    async def upload_paper(request: Request, file: Annotated[UploadFile, File()], title: Annotated[str | None, Form(max_length=500)] = None, short_title: Annotated[str | None, Form(max_length=500)] = None, category_ids: Annotated[list[str] | None, Form()] = None, metadata_json: Annotated[str | None, Form(alias="metadata", max_length=20_000)] = None):
        database = store(request)
        token = uuid.uuid4().hex
        temporary = database.uploads_dir / f"{token}.part"
        destination = database.uploads_dir / f"{token}.pdf"
        committed = False
        try:
            selected_categories = validate(CategoryAssignment, {"category_ids": category_ids or []}).category_ids
            overrides = {}
            if metadata_json is not None:
                try:
                    value = json.loads(metadata_json)
                except ValueError as error:
                    raise HTTPException(status_code=422, detail="Invalid metadata JSON") from error
                overrides = validate(MetadataPatch, value).model_dump(exclude_unset=True)
            await save_pdf_upload(file, temporary)
            original_name = filename_only(file.filename)
            detected = await run_in_threadpool(inspect_upload_metadata, temporary, original_name)
            page_count = detected["page_count"]
            values = {name: detected[name] for name in ("title", "authors", "venue", "year", "doi")}
            if title is not None:
                values["title"] = title
            if short_title is not None:
                values["short_title"] = short_title
            values.update(overrides)
            metadata = validate(Metadata, values)
            temporary.replace(destination)
            try:
                paper = database.create_paper(metadata.model_dump(), destination, page_count, original_name, True, category_ids=selected_categories)
            except ValueError as error:
                raise HTTPException(status_code=422, detail="所选分类已不存在，请刷新分类列表") from error
            committed = True
            return paper
        finally:
            await file.close()
            temporary.unlink(missing_ok=True)
            if not committed:
                destination.unlink(missing_ok=True)

    @application.patch("/api/papers/{paper_id}", response_model=PaperDetail)
    def patch_paper(paper_id: str, patch: MetadataPatch, request: Request):
        paper = get_paper(request, paper_id)
        return store(request).patch_paper(paper_id, merge_metadata(paper, patch.model_dump(exclude_unset=True)))

    @application.delete("/api/papers/{paper_id}", status_code=204)
    def delete_paper(paper_id: str, request: Request):
        request.app.state.translator.cancel_paper(paper_id)
        if not store(request).delete_paper(paper_id):
            raise HTTPException(status_code=404, detail="Paper not found")
        return Response(status_code=204)

    @application.get("/api/papers/{paper_id}/pdf")
    def paper_pdf(paper_id: str, request: Request):
        source = store(request).source(paper_id)
        if source is None:
            raise HTTPException(status_code=404, detail="Paper not found")
        path = Path(source["pdf_path"])
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Registered PDF is not available")
        return FileResponse(path, media_type="application/pdf", filename=source["file_name"], content_disposition_type="inline")

    @application.post("/api/papers/{paper_id}/notes", response_model=Note, status_code=201)
    def create_note(paper_id: str, note: NoteCreate, request: Request):
        paper = get_paper(request, paper_id)
        validate_note_pages(note, paper["page_count"])
        return store(request).create_note(paper_id, note.model_dump(), "sort_order" in note.model_fields_set)

    @application.put("/api/papers/{paper_id}/notes/{note_id}", response_model=Note)
    def update_note(paper_id: str, note_id: str, patch: NotePatch, request: Request):
        paper = get_paper(request, paper_id)
        current = store(request).get_note(paper_id, note_id)
        if current is None:
            raise HTTPException(status_code=404, detail="Note not found")
        values = patch.model_dump(exclude_unset=True)
        if (current["verification_status"] == "verified" and "verification_status" not in values
                and any(name in values and values[name] != current[name] for name in ("title", "content", "page_start", "page_end", "kind", "evidence"))):
            values["verification_status"] = "needs_review"
        current.pop("id")
        current.update(values)
        note = validate(NoteCreate, current)
        validate_note_pages(note, paper["page_count"])
        return store(request).update_note(paper_id, note_id, note.model_dump())

    @application.delete("/api/papers/{paper_id}/notes/{note_id}", status_code=204)
    def delete_note(paper_id: str, note_id: str, request: Request):
        get_paper(request, paper_id)
        if not store(request).delete_note(paper_id, note_id):
            raise HTTPException(status_code=404, detail="Note not found")
        return Response(status_code=204)

    @application.patch("/api/papers/{paper_id}/progress", response_model=Progress)
    def update_progress(paper_id: str, patch: ProgressPatch, request: Request):
        paper = get_paper(request, paper_id)
        values = patch.model_dump(exclude_unset=True)
        if values.get("page", 1) > paper["page_count"]:
            raise HTTPException(status_code=422, detail=f"Page must be between 1 and {paper['page_count']}")
        if values.get("active_note_id") is not None and store(request).get_note(paper_id, values["active_note_id"]) is None:
            raise HTTPException(status_code=422, detail="active_note_id must identify a note in this paper")
        return store(request).patch_progress(paper_id, values)

    @application.post("/api/papers/{paper_id}/import", response_model=PaperDetail)
    async def import_notes(paper_id: str, request: Request, file: Annotated[UploadFile, File()], mode: Annotated[Literal["append", "replace"], Form()] = "append"):
        paper = get_paper(request, paper_id)
        try:
            raw = await file.read(MAX_IMPORT_BYTES + 1)
        finally:
            await file.close()
        if len(raw) > MAX_IMPORT_BYTES:
            raise HTTPException(status_code=413, detail="Import exceeds the 10 MB limit")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise HTTPException(status_code=422, detail="Import must be UTF-8 encoded") from error
        extension = Path(filename_only(file.filename, "notes.json")).suffix.lower()
        if extension == ".json":
            try:
                value = json.loads(text)
            except ValueError as error:
                raise HTTPException(status_code=422, detail="Invalid JSON document") from error
        elif extension in {".md", ".markdown"}:
            value = parse_markdown(text, Path(filename_only(file.filename, "Notes.md")).stem)
        else:
            raise HTTPException(status_code=422, detail="Import must be a .json or .md file")
        document = validate(ImportDocument, value)
        for note in document.notes:
            validate_note_pages(note, paper["page_count"])
        metadata = merge_metadata(paper, document.paper.model_dump(exclude_unset=True)) if document.paper else {}
        return store(request).import_notes(paper_id, [note.model_dump(exclude={"id"}) for note in document.notes], metadata, mode)

    @application.get("/api/papers/{paper_id}/export")
    def export_notes(paper_id: str, request: Request, format: Annotated[Literal["json", "markdown"], Query()] = "json"):
        paper = get_paper(request, paper_id)
        if format == "markdown":
            content = export_markdown(paper)
            media_type, extension = "text/markdown", "md"
        else:
            content = json.dumps({"schema_version": 1, "paper": metadata_from_paper(paper), "notes": paper["notes"]}, ensure_ascii=False, indent=2)
            media_type, extension = "application/json", "json"
        return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="notes-{paper_id}.{extension}"'})

    @application.get("/api/papers/{paper_id}/reading-task")
    def prepare_reading_task(paper_id: str, request: Request, focus: Annotated[str, Query(max_length=2000)] = "", format: Annotated[Literal["json", "markdown"], Query()] = "json"):
        paper = get_paper(request, paper_id)
        source = store(request).source(paper_id)
        if not Path(source["pdf_path"]).is_file():
            raise HTTPException(status_code=404, detail="Registered PDF is not available")
        task = reading_task(paper, source, store(request).data_dir, focus)
        if format == "markdown":
            return Response(content=task["request"], media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="reading-task-{paper_id}.md"'})
        return task

    application.include_router(translation_router)
    application.include_router(reading_router)
    application.include_router(library_safety_router)
    application.include_router(evidence_router)
    application.include_router(trash_router)
    application.include_router(annotations_router)

    @application.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API endpoint not found")
        candidate = (frontend_dist / path).resolve()
        if not candidate.is_relative_to(frontend_dist):
            raise HTTPException(status_code=404, detail="Not found")
        if candidate.is_file():
            return FileResponse(candidate)
        if Path(path).suffix:
            raise HTTPException(status_code=404, detail="Asset not found")
        index = frontend_dist / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise HTTPException(status_code=503, detail="Frontend has not been built")

    return application


app = create_app()
