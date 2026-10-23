"""Remove legacy exercises and label unchanged batch guides, with JSON backups."""

import argparse
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from backend.models import Metadata
from backend.store import Store


GUIDE_PREFIX = "版本：批量简要导读，尚非逐篇精读稿。\n\n"


def upgrade(data_dir: Path, apply: bool = False) -> dict:
    database = Store(data_dir)
    seed_file = data_dir / "seed.json"
    seeds = json.loads(seed_file.read_text(encoding="utf-8-sig")) if seed_file.is_file() else []
    guides = {
        (paper["id"], note["title"]): note["content"].removeprefix(GUIDE_PREFIX)
        for paper in seeds for note in paper["notes"] if note["kind"] == "guide"
    }
    backup_dir = None
    with database.connection() as connection:
        # Hold the write lock so backup and edits refer to the same note versions.
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute("SELECT * FROM notes").fetchall()
        exercises = [row for row in rows if row["kind"] == "exercise"]
        unchanged_guides = [
            row for row in rows if row["kind"] == "guide"
            and (row["paper_id"], row["title"]) in guides
            and row["content"] == guides[(row["paper_id"], row["title"])]
        ]
        affected = {row["paper_id"] for row in exercises + unchanged_guides}
        if apply and affected:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_dir = data_dir / "backups" / f"before-reading-upgrade-{stamp}-{uuid.uuid4().hex[:8]}"
            backup_dir.mkdir(parents=True, exist_ok=False)
            for index, paper_id in enumerate(sorted(affected)):
                paper_row = connection.execute("SELECT * FROM papers WHERE id=?", (paper_id,)).fetchone()
                paper = database.paper_dict(paper_row)
                document = {
                    "schema_version": 1,
                    "paper": {key: paper[key] for key in Metadata.model_fields},
                    "notes": [database.note_dict(row) for row in connection.execute(
                        "SELECT * FROM notes WHERE paper_id=? ORDER BY sort_order,rowid", (paper_id,)
                    ).fetchall()],
                }
                # Numeric names avoid using metadata or seed IDs as filesystem paths.
                with (backup_dir / f"{index + 1:02d}.json").open("x", encoding="utf-8") as output:
                    json.dump(document, output, ensure_ascii=False, indent=2)
                    output.write("\n")
            for row in exercises:
                connection.execute("UPDATE papers SET active_note_id=NULL WHERE id=? AND active_note_id=?", (row["paper_id"], row["id"]))
                connection.execute("DELETE FROM notes WHERE id=?", (row["id"],))
            for row in unchanged_guides:
                connection.execute("UPDATE notes SET content=? WHERE id=?", (GUIDE_PREFIX + row["content"], row["id"]))
    return {"applied": apply, "exercises": len(exercises), "guides": len(unchanged_guides), "backup_dir": str(backup_dir) if backup_dir else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[1] / "data")
    parser.add_argument("--apply", action="store_true", help="Apply changes after saving importable JSON backups")
    args = parser.parse_args()
    print(json.dumps(upgrade(args.data_dir, args.apply), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
