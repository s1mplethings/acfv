from __future__ import annotations

import argparse
import json
from pathlib import Path

from acfv.library import LibraryService
from acfv.moments.quality import repair_moments


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely suppress unreferenced low-information and structural duplicate Moments.")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--creator-slug", required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    library = LibraryService(args.db)
    creator = library.repository.get_creator_by_slug(args.creator_slug)
    if creator is None:
        raise KeyError(f"Unknown Creator slug: {args.creator_slug}")
    report = repair_moments(library.repository, creator_id=creator.id, dry_run=not args.apply)
    report.update({"schema_version": "1.0", "creator_id": creator.id, "creator_slug": creator.slug})
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("dry_run", "before_count", "after_count", "counts")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
