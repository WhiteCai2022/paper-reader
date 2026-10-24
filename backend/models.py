from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator, model_validator

from .bibliography import normalize_doi


Status = Literal["unread", "reading", "done"]
NoteKind = Literal["guide", "concept", "method", "experiment", "critique", "exercise", "note"]
Title = Annotated[str, Field(min_length=1, max_length=500)]
Page = Annotated[StrictInt, Field(ge=1)]
Year = Annotated[StrictInt, Field(ge=1800, le=2200)]
Content = Annotated[str, Field(max_length=2_000_000)]
MAX_SORT_ORDER = (1 << 63) - 1
SortOrder = Annotated[StrictInt, Field(ge=0, le=MAX_SORT_ORDER)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CategoryInput(Model):
    name: Annotated[str, Field(min_length=1, max_length=80)]

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Category name must be a nonblank single line")
        if value in {"默认分类", "全部文献"}:
            raise ValueError("This category name is reserved")
        return value


class Category(Model):
    id: str
    name: str
    paper_count: int
    is_default: bool = False


class CategoryAssignment(Model):
    category_ids: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(max_length=100)

    @field_validator("category_ids")
    @classmethod
    def unique_categories(cls, value: list[str]) -> list[str]:
        if "default" in value:
            raise ValueError("Use an empty category_ids list for the default category")
        return list(dict.fromkeys(value))


class CategoryMembers(Model):
    paper_ids: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(max_length=10_000)

    @field_validator("paper_ids")
    @classmethod
    def unique_papers(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class Metadata(Model):
    title: Title
    short_title: Annotated[str, Field(max_length=500)] = ""
    authors: Annotated[str, Field(max_length=5000)] = ""
    venue: Annotated[str, Field(max_length=1000)] = ""
    year: Year | None = None
    doi: Annotated[str, Field(max_length=500)] = ""
    tags: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(default_factory=list, max_length=100)
    status: Status = "unread"

    @field_validator("doi")
    @classmethod
    def clean_doi(cls, value: str) -> str:
        return normalize_doi(value)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        value = value.strip()
        if not value or "\n" in value or "\r" in value:
            raise ValueError("Title must be a nonblank single line")
        return value

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value: list[str]) -> list[str]:
        result = list(dict.fromkeys(tag.strip() for tag in value))
        if any(not tag for tag in result):
            raise ValueError("Tags cannot be blank")
        return result


class MetadataPatch(Model):
    title: Title | None = None
    short_title: Annotated[str, Field(max_length=500)] | None = None
    authors: Annotated[str, Field(max_length=5000)] | None = None
    venue: Annotated[str, Field(max_length=1000)] | None = None
    year: Year | None = None
    doi: Annotated[str, Field(max_length=500)] | None = None
    tags: list[Annotated[str, Field(min_length=1, max_length=100)]] | None = Field(default=None, max_length=100)
    status: Status | None = None

    @field_validator("doi")
    @classmethod
    def clean_doi(cls, value):
        return normalize_doi(value) if value is not None else None

    @model_validator(mode="after")
    def reject_null_fields(self):
        for name in self.model_fields_set - {"year"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class MetadataPreview(Model):
    title: str
    authors: str = ""
    venue: str = ""
    year: Year | None = None
    doi: str = ""
    page_count: Page | None = None
    sources: dict[str, Literal["pdf", "xmp", "first_page", "filename", "crossref"]] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class DoiQuery(Model):
    doi: Annotated[str, Field(min_length=1, max_length=550)]

    @field_validator("doi")
    @classmethod
    def clean_doi(cls, value: str) -> str:
        value = normalize_doi(value)
        if not value:
            raise ValueError("DOI cannot be blank")
        return value


class Evidence(Model):
    page: Page
    quote: Annotated[str, Field(min_length=10, max_length=2000)]
    label: Annotated[str, Field(max_length=200)] = ""

    @field_validator("quote")
    @classmethod
    def clean_quote(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Evidence quote must contain at least 10 characters")
        return value


class NoteCreate(Model):
    title: Title = "Note"
    page_start: Page = 1
    page_end: Page | None = None
    kind: NoteKind = "note"
    content: Content = ""
    sort_order: SortOrder = 0
    completed: StrictBool = False
    evidence: list[Evidence] = Field(default_factory=list, max_length=32)
    verification_status: Literal["unverified", "verified", "needs_review"] = "unverified"

    @model_validator(mode="after")
    def validate_range(self):
        self.title = self.title.strip()
        if not self.title or "\n" in self.title or "\r" in self.title:
            raise ValueError("Title must be a nonblank single line")
        if self.page_end is None:
            self.page_end = self.page_start
        if self.page_end < self.page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        return self


class NotePatch(Model):
    title: Title | None = None
    page_start: Page | None = None
    page_end: Page | None = None
    kind: NoteKind | None = None
    content: Content | None = None
    sort_order: SortOrder | None = None
    completed: StrictBool | None = None
    evidence: list[Evidence] | None = Field(default=None, max_length=32)
    verification_status: Literal["unverified", "verified", "needs_review"] | None = None

    @model_validator(mode="after")
    def reject_null_fields(self):
        for name in self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class Note(NoteCreate):
    id: str


class AnnotationRect(Model):
    x: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    y: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    width: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]
    height: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]

    @model_validator(mode="after")
    def inside_page(self):
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("Annotation rectangle must be inside the PDF page")
        return self


class AnnotationText(Model):
    content: Annotated[str, Field(min_length=1, max_length=20_000)]

    @field_validator("content")
    @classmethod
    def nonblank_content(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Annotation content cannot be blank")
        return value


class AnnotationCreate(AnnotationText):
    page: Page
    quote: Annotated[str, Field(min_length=1, max_length=10_000)]
    rects: list[AnnotationRect] = Field(min_length=1, max_length=512)

    @field_validator("quote")
    @classmethod
    def nonblank_quote(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Selected text cannot be blank")
        return value


class Annotation(AnnotationCreate):
    id: str
    created_at: str
    updated_at: str


class ImportNote(NoteCreate):
    id: str | None = None


class ImportDocument(Model):
    schema_version: Literal[1]
    paper: MetadataPatch | None = None
    notes: list[ImportNote] = Field(max_length=10_000)


class Progress(Model):
    page: Page = 1
    zoom: Annotated[float, Field(ge=0.25, le=4, allow_inf_nan=False)] = 1.0
    active_note_id: str | None = None


class ProgressPatch(Model):
    page: Page | None = None
    zoom: Annotated[float, Field(ge=0.25, le=4, allow_inf_nan=False)] | None = None
    active_note_id: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    status: Status | None = None

    @model_validator(mode="after")
    def reject_null_fields(self):
        for name in self.model_fields_set - {"active_note_id"}:
            if getattr(self, name) is None:
                raise ValueError(f"{name} cannot be null")
        return self


class Paper(Metadata):
    id: str
    page_count: Page
    file_name: str
    file_url: str
    notes_count: int
    progress: Progress
    category_ids: list[str] = Field(default_factory=list)


class PaperDetail(Paper):
    notes: list[Note]
    annotations: list[Annotation] = Field(default_factory=list)
