"""
Seed character memories into episodic_memories + sqlite-vec.

Reads data/character_memories.json, generates bge-m3 embeddings via ModelRouter,
stores in episodic_memories (session_id="character") + memories_vec.

Idempotent — checks by summary content match before inserting.
Usage:
    uv run python scripts/seed_character_memories.py
    uv run python scripts/seed_character_memories.py --force   # re-embed all
"""
import asyncio
import json
import sys
import time
from pathlib import Path

# Project root → Python path
_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))

from packages.shared.database import DatabaseManager
from packages.shared.model_router import ModelRouter
from packages.shared.vector_store import VectorStore
from loguru import logger


async def seed(force: bool = False, db_path: str = "data/xilian.db") -> tuple[int, int]:
    json_path = _project_root / "data" / "character_memories.json"
    if not json_path.exists():
        logger.error(f"File not found: {json_path}")
        return 0, 0

    with open(json_path) as f:
        data = json.load(f)

    entries = data["entries"]
    source = data["source"]
    logger.info(f"Loaded {len(entries)} entries from {json_path}")

    # ── Init infrastructure ──
    db = DatabaseManager(db_path)
    await db.init()

    router = ModelRouter()

    vs = VectorStore(str(db_path), dimension=1024)
    await vs.init()

    # ── Gather existing summaries for dedup ──
    existing: set[str] = set()
    if not force and db._conn:
        rows = await db._conn.execute(
            "SELECT summary FROM episodic_memories WHERE session_id = ?",
            (source,),
        )
        async for row in rows:
            existing.add(row[0])
    logger.info(f"Existing character memories in DB: {len(existing)}")

    # ── Seed loop ──
    inserted = 0
    skipped = 0
    errors = 0

    for i, entry in enumerate(entries):
        eid = entry["id"]
        summary = entry["content"]

        if summary in existing:
            logger.debug(f"[{i+1}/{len(entries)}] Skip: {eid}")
            skipped += 1
            continue

        try:
            # Step 1: embedding
            t0 = time.time()
            vector = await router.embed(summary)
            elapsed = (time.time() - t0) * 1000
            logger.info(f"[{i+1}/{len(entries)}] Embed {eid} ({elapsed:.0f}ms)")

            # Step 2: insert into episodic_memories
            emotion_tags = {
                "character_id": eid,
                "category": entry["category"],
                "tags": entry["tags"],
                "source": source,
            }
            episodic_id = await db.insert_episodic_memory(
                summary=summary,
                raw_conversation=summary,
                emotion_tags=emotion_tags,
                importance=entry["importance"],
                embedding_model=router._embed_model,
                embedding_version="v1",
                session_id=source,
            )

            # Step 3: insert vector (row_id = episodic_id)
            await vs.insert(row_id=episodic_id, embedding=vector)

            # Step 4: mark done
            await db.update_embedding_status(episodic_id, "done", eid)

            logger.info(f"  → episodic_id={episodic_id} done")
            inserted += 1

        except Exception as exc:
            logger.error(f"[{i+1}/{len(entries)}] Error {eid}: {exc}")
            errors += 1

    logger.info(f"Seed complete. inserted={inserted} skipped={skipped} errors={errors}")
    return inserted, skipped


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Seed character memories")
    parser.add_argument("--force", action="store_true", help="Re-insert all, skip dedup")
    parser.add_argument("--db", default="data/xilian.db", help="Database path")
    args = parser.parse_args()

    inserted, skipped = asyncio.run(seed(force=args.force, db_path=args.db))
    print(f"\nDone: {inserted} inserted, {skipped} skipped")

    if inserted == 0 and skipped == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
