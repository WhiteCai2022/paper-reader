import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from .models import MAX_SORT_ORDER, NoteCreate


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.uploads_dir = self.data_dir / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "papers.sqlite3"
        with self.connection() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS papers (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    short_title TEXT NOT NULL DEFAULT '',
                    authors TEXT NOT NULL DEFAULT '',
                    venue TEXT NOT NULL DEFAULT '',
                    year INTEGER,
                    doi TEXT NOT NULL DEFAULT '',
                    tags TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'unread',
                    page_count INTEGER NOT NULL CHECK(page_count > 0),
                    file_name TEXT NOT NULL,
                    pdf_path TEXT NOT NULL,
                    managed INTEGER NOT NULL DEFAULT 0,
                    page INTEGER NOT NULL DEFAULT 1,
                    zoom REAL NOT NULL DEFAULT 1,
                    active_note_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    page_start INTEGER NOT NULL,
                    page_end INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS notes_paper_order ON notes(paper_id, sort_order);
                CREATE TABLE IF NOT EXISTS deleted_seeds (
                    id TEXT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS categories (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE
                );
                CREATE TABLE IF NOT EXISTS paper_categories (
                    paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
                    category_id TEXT NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
                    PRIMARY KEY (paper_id, category_id)
                );
                CREATE INDEX IF NOT EXISTS paper_categories_category ON paper_categories(category_id, paper_id);
                """
            )
            if "doi" not in {row["name"] for row in connection.execute("PRAGMA table_info(papers)")}:
                connection.execute("ALTER TABLE papers ADD COLUMN doi TEXT NOT NULL DEFAULT ''")
            for table, additions in {
                "papers": {"deleted_at": "TEXT"},
                "notes": {"deleted_at": "TEXT", "evidence": "TEXT NOT NULL DEFAULT '[]'", "verification_status": "TEXT NOT NULL DEFAULT 'unverified'"},
            }.items():
                columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
                for name, declaration in additions.items():
                    if name not in columns:
                        connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")
            connection.execute("""CREATE TABLE IF NOT EXISTS note_versions (
                id TEXT PRIMARY KEY, note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
                paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
                snapshot TEXT NOT NULL, reason TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
            connection.execute("CREATE INDEX IF NOT EXISTS versions_note ON note_versions(note_id,created_at)")
            for row in connection.execute("SELECT id,paper_id FROM notes WHERE NOT EXISTS (SELECT 1 FROM note_versions v WHERE v.note_id=notes.id)").fetchall():
                self.snapshot_note(connection, row["paper_id"], row["id"], "baseline")
            # Rebase legacy managed uploads once so moving the data directory is portable.
            for row in connection.execute("SELECT id,pdf_path FROM papers WHERE managed=1"):
                path = Path(row["pdf_path"])
                if path.is_absolute() and path.parent.name == "uploads":
                    connection.execute("UPDATE papers SET pdf_path=? WHERE id=?", (f"uploads/{path.name}", row["id"]))

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.db_path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def note_dict(row):
        if row is None:
            return None
        result = dict(row)
        result.pop("paper_id", None)
        result.pop("deleted_at", None)
        result["completed"] = bool(result["completed"])
        result["evidence"] = json.loads(result.get("evidence", "[]"))
        result.setdefault("verification_status", "unverified")
        return result

    @staticmethod
    def paper_dict(row):
        if row is None:
            return None
        result = dict(row)
        result["tags"] = json.loads(result["tags"])
        result["progress"] = {
            "page": result.pop("page"),
            "zoom": result.pop("zoom"),
            "active_note_id": result.pop("active_note_id"),
        }
        result["file_url"] = f"/api/papers/{result['id']}/pdf"
        result["category_ids"] = []
        for name in ("pdf_path", "managed", "created_at", "deleted_at"):
            result.pop(name, None)
        return result

    def list_papers(self):
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT p.*, (SELECT COUNT(*) FROM notes n WHERE n.paper_id=p.id AND n.deleted_at IS NULL) AS notes_count "
                "FROM papers p WHERE p.deleted_at IS NULL ORDER BY p.created_at, p.rowid"
            ).fetchall()
            memberships = {}
            for membership in connection.execute("SELECT paper_id,category_id FROM paper_categories ORDER BY category_id"):
                memberships.setdefault(membership["paper_id"], []).append(membership["category_id"])
            papers = [self.paper_dict(row) for row in rows]
            for paper in papers:
                paper["category_ids"] = memberships.get(paper["id"], [])
            return papers

    def get_paper(self, paper_id: str, detail=True):
        with self.connection() as connection:
            row = connection.execute(
                "SELECT p.*, (SELECT COUNT(*) FROM notes n WHERE n.paper_id=p.id AND n.deleted_at IS NULL) AS notes_count "
                "FROM papers p WHERE p.id=? AND p.deleted_at IS NULL", (paper_id,)
            ).fetchone()
            paper = self.paper_dict(row)
            if paper is not None:
                paper["category_ids"] = [row[0] for row in connection.execute(
                    "SELECT category_id FROM paper_categories WHERE paper_id=? ORDER BY category_id", (paper_id,)
                )]
            if paper is not None and detail:
                paper["notes"] = [self.note_dict(note) for note in connection.execute(
                    "SELECT * FROM notes WHERE paper_id=? AND deleted_at IS NULL ORDER BY sort_order, rowid", (paper_id,)
                ).fetchall()]
            return paper

    def source(self, paper_id: str):
        with self.connection() as connection:
            row = connection.execute("SELECT pdf_path,managed,file_name FROM papers WHERE id=? AND deleted_at IS NULL", (paper_id,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            path = Path(result["pdf_path"])
            result["pdf_path"] = str((self.data_dir / path).resolve()) if not path.is_absolute() else str(path)
            return result

    def seed_is_deleted(self, paper_id: str):
        with self.connection() as connection:
            return connection.execute("SELECT 1 FROM deleted_seeds WHERE id=?", (paper_id,)).fetchone() is not None

    def create_paper(self, metadata, path: Path, page_count: int, file_name: str, managed: bool, paper_id=None, notes=None, category_ids=None):
        paper_id = paper_id or uuid.uuid4().hex
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            category_ids = self.validate_categories(connection, category_ids or [])
            cursor = connection.execute(
                "INSERT OR IGNORE INTO papers "
                "(id,title,short_title,authors,venue,year,doi,tags,status,page_count,file_name,pdf_path,managed) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (paper_id, metadata["title"], metadata.get("short_title", ""), metadata.get("authors", ""),
                 metadata.get("venue", ""), metadata.get("year"), metadata.get("doi", ""), json.dumps(metadata.get("tags", [])),
                 metadata.get("status", "unread"), page_count, file_name,
                 path.resolve().relative_to(self.data_dir).as_posix() if managed else str(path.resolve()), int(managed)),
            )
            if cursor.rowcount and notes:
                for index, note in enumerate(notes):
                    self.insert_note(connection, paper_id, note, note.get("sort_order", index))
            if cursor.rowcount:
                connection.executemany("INSERT INTO paper_categories(paper_id,category_id) VALUES (?,?)", [(paper_id, category_id) for category_id in category_ids])
        return self.get_paper(paper_id)

    @staticmethod
    def validate_categories(connection, category_ids):
        category_ids = list(dict.fromkeys(category_ids))
        if category_ids:
            placeholders = ",".join("?" for _ in category_ids)
            found = {row[0] for row in connection.execute(f"SELECT id FROM categories WHERE id IN ({placeholders})", category_ids)}
            if found != set(category_ids):
                raise ValueError("One or more categories no longer exist")
        return category_ids

    def list_categories(self):
        with self.connection() as connection:
            default_count = connection.execute("SELECT COUNT(*) FROM papers p WHERE p.deleted_at IS NULL AND NOT EXISTS (SELECT 1 FROM paper_categories pc WHERE pc.paper_id=p.id)").fetchone()[0]
            result = [{"id": "default", "name": "默认分类", "paper_count": default_count, "is_default": True}]
            result.extend({**dict(row), "is_default": False} for row in connection.execute(
                "SELECT c.id,c.name,COUNT(p.id) AS paper_count FROM categories c "
                "LEFT JOIN paper_categories pc ON pc.category_id=c.id LEFT JOIN papers p ON p.id=pc.paper_id AND p.deleted_at IS NULL GROUP BY c.id ORDER BY c.rowid"
            ))
            return result

    def create_category(self, name):
        category_id = uuid.uuid4().hex
        with self.connection() as connection:
            connection.execute("INSERT INTO categories(id,name) VALUES (?,?)", (category_id, name))
        return {"id": category_id, "name": name, "paper_count": 0, "is_default": False}

    def rename_category(self, category_id, name):
        with self.connection() as connection:
            if not connection.execute("UPDATE categories SET name=? WHERE id=?", (name, category_id)).rowcount:
                return None
        return next((category for category in self.list_categories() if category["id"] == category_id), None)

    def delete_category(self, category_id):
        with self.connection() as connection:
            return bool(connection.execute("DELETE FROM categories WHERE id=?", (category_id,)).rowcount)

    def set_paper_categories(self, paper_id, category_ids):
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute("SELECT 1 FROM papers WHERE id=? AND deleted_at IS NULL", (paper_id,)).fetchone():
                return None
            category_ids = self.validate_categories(connection, category_ids)
            connection.execute("DELETE FROM paper_categories WHERE paper_id=?", (paper_id,))
            connection.executemany("INSERT INTO paper_categories(paper_id,category_id) VALUES (?,?)", [(paper_id, category_id) for category_id in category_ids])
        return self.get_paper(paper_id)

    def set_category_papers(self, category_id, paper_ids):
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute("SELECT 1 FROM categories WHERE id=?", (category_id,)).fetchone():
                return None
            paper_ids = list(dict.fromkeys(paper_ids))
            available = {row[0] for row in connection.execute("SELECT id FROM papers WHERE deleted_at IS NULL")}
            if not set(paper_ids).issubset(available):
                raise ValueError("One or more papers no longer exist")
            connection.execute("DELETE FROM paper_categories WHERE category_id=? AND paper_id IN (SELECT id FROM papers WHERE deleted_at IS NULL)", (category_id,))
            connection.executemany("INSERT INTO paper_categories(paper_id,category_id) VALUES (?,?)", [(paper_id, category_id) for paper_id in paper_ids])
        return next((category for category in self.list_categories() if category["id"] == category_id), None)

    @staticmethod
    def update_metadata(connection, paper_id, values):
        if not values:
            return
        allowed = {"title", "short_title", "authors", "venue", "year", "doi", "tags", "status"}
        if not set(values).issubset(allowed):
            raise ValueError("Unsupported metadata field")
        values = {key: json.dumps(value) if key == "tags" else value for key, value in values.items()}
        columns = ",".join(f"{name}=?" for name in values)
        connection.execute(f"UPDATE papers SET {columns} WHERE id=?", (*values.values(), paper_id))

    def patch_paper(self, paper_id, values):
        with self.connection() as connection:
            self.update_metadata(connection, paper_id, values)
        return self.get_paper(paper_id)

    def delete_paper(self, paper_id):
        with self.connection() as connection:
            row = connection.execute("SELECT managed FROM papers WHERE id=? AND deleted_at IS NULL", (paper_id,)).fetchone()
            if row is None:
                return False
            if not row["managed"]:
                connection.execute("INSERT OR IGNORE INTO deleted_seeds(id) VALUES (?)", (paper_id,))
            connection.execute("UPDATE papers SET deleted_at=CURRENT_TIMESTAMP WHERE id=?", (paper_id,))
        return True

    @staticmethod
    def insert_note(connection, paper_id, note, order):
        note_id = uuid.uuid4().hex
        connection.execute(
            "INSERT INTO notes (id,paper_id,title,page_start,page_end,kind,content,sort_order,completed,evidence,verification_status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (note_id, paper_id, note["title"], note["page_start"], note["page_end"], note["kind"],
             note["content"], order, int(note["completed"]), json.dumps(note.get("evidence", []), ensure_ascii=False), note.get("verification_status", "unverified")),
        )
        Store.snapshot_note(connection, paper_id, note_id, "create")
        return note_id

    def get_note(self, paper_id, note_id):
        with self.connection() as connection:
            return self.note_dict(connection.execute("SELECT n.* FROM notes n JOIN papers p ON p.id=n.paper_id WHERE n.paper_id=? AND n.id=? AND n.deleted_at IS NULL AND p.deleted_at IS NULL", (paper_id, note_id)).fetchone())

    def create_note(self, paper_id, note, explicit_order=False):
        with self.connection() as connection:
            last = connection.execute("SELECT COALESCE(MAX(sort_order),-1) FROM notes WHERE paper_id=?", (paper_id,)).fetchone()[0]
            note_id = self.insert_note(connection, paper_id, note, note["sort_order"] if explicit_order else min(last + 1, MAX_SORT_ORDER))
        return self.get_note(paper_id, note_id)

    def update_note(self, paper_id, note_id, note):
        names = ("title", "page_start", "page_end", "kind", "content", "sort_order", "completed", "evidence", "verification_status")
        with self.connection() as connection:
            self.snapshot_note(connection, paper_id, note_id, "before_edit")
            connection.execute(
                "UPDATE notes SET " + ",".join(f"{name}=?" for name in names) + " WHERE paper_id=? AND id=?",
                (*(int(note[name]) if name == "completed" else json.dumps(note.get(name, []), ensure_ascii=False) if name == "evidence" else note.get(name, "unverified") for name in names), paper_id, note_id),
            )
            self.snapshot_note(connection, paper_id, note_id, "edit")
        return self.get_note(paper_id, note_id)

    def delete_note(self, paper_id, note_id):
        with self.connection() as connection:
            self.snapshot_note(connection, paper_id, note_id, "delete")
            connection.execute("UPDATE papers SET active_note_id=NULL WHERE id=? AND active_note_id=?", (paper_id, note_id))
            return bool(connection.execute("UPDATE notes SET deleted_at=CURRENT_TIMESTAMP WHERE paper_id=? AND id=? AND deleted_at IS NULL", (paper_id, note_id)).rowcount)

    def patch_progress(self, paper_id, values):
        if not values:
            return self.get_paper(paper_id, detail=False)["progress"]
        allowed = {"page", "zoom", "active_note_id", "status"}
        if not set(values).issubset(allowed):
            raise ValueError("Unsupported progress field")
        with self.connection() as connection:
            connection.execute(
                "UPDATE papers SET " + ",".join(f"{name}=?" for name in values) + " WHERE id=?",
                (*values.values(), paper_id),
            )
        return self.get_paper(paper_id, detail=False)["progress"]

    def import_notes(self, paper_id, notes, metadata, mode):
        # The caller validates the entire document before this transaction starts.
        with self.connection() as connection:
            self.update_metadata(connection, paper_id, metadata)
            if mode == "replace":
                for row in connection.execute("SELECT id FROM notes WHERE paper_id=? AND deleted_at IS NULL", (paper_id,)).fetchall():
                    self.snapshot_note(connection, paper_id, row["id"], "import_replace")
                connection.execute("UPDATE notes SET deleted_at=CURRENT_TIMESTAMP WHERE paper_id=? AND deleted_at IS NULL", (paper_id,))
                connection.execute("UPDATE papers SET active_note_id=NULL WHERE id=?", (paper_id,))
                for note in notes:
                    self.insert_note(connection, paper_id, note, note["sort_order"])
            else:
                last = connection.execute("SELECT COALESCE(MAX(sort_order),-1) FROM notes WHERE paper_id=?", (paper_id,)).fetchone()[0]
                for index, note in enumerate(sorted(notes, key=lambda item: item["sort_order"])):
                    self.insert_note(connection, paper_id, note, min(last + 1 + index, MAX_SORT_ORDER))
        return self.get_paper(paper_id)

    @staticmethod
    def snapshot_note(connection, paper_id, note_id, reason):
        row = connection.execute("SELECT * FROM notes WHERE paper_id=? AND id=?", (paper_id, note_id)).fetchone()
        if row is None:
            return
        snapshot = json.dumps(Store.note_dict(row), ensure_ascii=False)
        latest = connection.execute("SELECT snapshot FROM note_versions WHERE note_id=? ORDER BY rowid DESC LIMIT 1", (note_id,)).fetchone()
        if latest and latest["snapshot"] == snapshot and reason not in {"delete", "import_replace", "restore"}:
            return
        connection.execute("INSERT INTO note_versions(id,note_id,paper_id,snapshot,reason) VALUES (?,?,?,?,?)",
                           (uuid.uuid4().hex, note_id, paper_id, snapshot, reason))

    def note_versions(self, paper_id, note_id):
        with self.connection() as connection:
            return [{"id": row["id"], "created_at": row["created_at"], "reason": row["reason"], "note": json.loads(row["snapshot"])}
                    for row in connection.execute("SELECT * FROM note_versions WHERE paper_id=? AND note_id=? ORDER BY rowid DESC", (paper_id, note_id))]

    def restore_note_version(self, paper_id, note_id, version_id):
        with self.connection() as connection:
            row = connection.execute("SELECT snapshot FROM note_versions WHERE id=? AND paper_id=? AND note_id=?", (version_id, paper_id, note_id)).fetchone()
            if row is None:
                return None
            value = json.loads(row["snapshot"])
        value.pop("id", None)
        note = NoteCreate.model_validate(value)
        paper = self.get_paper(paper_id, detail=False)
        if paper is None or self.get_note(paper_id, note_id) is None:
            return None
        if note.page_end > paper["page_count"] or any(item.page > paper["page_count"] for item in note.evidence):
            raise ValueError("Version contains pages outside the current PDF")
        result = self.update_note(paper_id, note_id, note.model_dump())
        with self.connection() as connection:
            self.snapshot_note(connection, paper_id, note_id, "restore")
        return result

    def list_trash(self):
        with self.connection() as connection:
            papers = [{"type": "paper", "id": row["id"], "paper_id": row["id"], "title": row["title"], "deleted_at": row["deleted_at"]}
                      for row in connection.execute("SELECT id,title,deleted_at FROM papers WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC,rowid DESC")]
            notes = [{"type": "note", "id": row["id"], "paper_id": row["paper_id"], "paper_title": row["paper_title"], "title": row["title"], "deleted_at": row["deleted_at"]}
                     for row in connection.execute("SELECT n.id,n.paper_id,n.title,n.deleted_at,p.title AS paper_title FROM notes n JOIN papers p ON p.id=n.paper_id WHERE n.deleted_at IS NOT NULL AND p.deleted_at IS NULL ORDER BY n.deleted_at DESC,n.rowid DESC")]
        return sorted([*papers, *notes], key=lambda item: item["deleted_at"], reverse=True)

    def restore_trash(self, kind, item_id):
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if kind == "paper":
                row = connection.execute("SELECT id FROM papers WHERE id=? AND deleted_at IS NOT NULL", (item_id,)).fetchone()
                if row is None:
                    return None
                connection.execute("UPDATE papers SET deleted_at=NULL WHERE id=?", (item_id,))
                connection.execute("DELETE FROM deleted_seeds WHERE id=?", (item_id,))
                return {"type": kind, "id": item_id, "paper_id": item_id}
            if kind == "note":
                row = connection.execute("SELECT n.paper_id FROM notes n JOIN papers p ON p.id=n.paper_id WHERE n.id=? AND n.deleted_at IS NOT NULL AND p.deleted_at IS NULL", (item_id,)).fetchone()
                if row is None:
                    return None
                connection.execute("UPDATE notes SET deleted_at=NULL WHERE id=?", (item_id,))
                return {"type": kind, "id": item_id, "paper_id": row["paper_id"]}
            return None
