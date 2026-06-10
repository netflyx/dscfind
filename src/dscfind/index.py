"""The local, on-disk search index.

The index is a plain JSON file so it is easy to inspect, diff, or delete. Its
location can be overridden with the ``DSCFIND_HOME`` environment variable, which
also makes the tool trivial to test in isolation.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Record:
    course_code: str
    course_name: str
    offering: str
    offering_url: str
    title: str
    url: str
    kind: str
    context: str

    def haystack(self) -> str:
        """The text BM25 ranks against."""
        return " ".join([
            self.title, self.title,            # title counts double (it matters most)
            self.kind, self.context,
            self.course_code, self.course_name,
        ])


def home() -> Path:
    base = os.environ.get("DSCFIND_HOME")
    path = Path(base) if base else Path.home() / ".dscfind"
    path.mkdir(parents=True, exist_ok=True)
    return path


def index_path() -> Path:
    return home() / "index.json"


def save_index(records: list[Record], path: Path | None = None) -> Path:
    path = path or index_path()
    payload = {
        "version": 1,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(records),
        "records": [asdict(r) for r in records],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path


def load_index(path: Path | None = None) -> tuple[list[Record], dict]:
    path = path or index_path()
    if not path.exists():
        return [], {}
    data = json.loads(path.read_text())
    records = [Record(**r) for r in data.get("records", [])]
    meta = {k: v for k, v in data.items() if k != "records"}
    return records, meta
