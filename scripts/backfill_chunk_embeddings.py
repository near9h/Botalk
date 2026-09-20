#!/usr/bin/env python3
"""One-shot backfill: embed every existing kb_chunks row that has
`embedding IS NULL`. Run from inside the backend container:

    docker compose exec backend python /app/scripts/backfill_chunk_embeddings.py

The script mirrors `app.workers.ingest_worker._store_chunks` + the
embed step: walks each `KbDocument` (status=ready), reads the stored
chunk text, calls `zhipuai_embed.embed_texts`, and writes the
1024-dim vector back via `UPDATE ... embedding = CAST(:vec AS vector)`.

Idempotent: rows with non-null embeddings are skipped. Run as many
times as you like; the cost is just the network round-trip to GLM.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

# Make sure we can import the app package whether we're running inside
# the backend container (`/app/scripts/...`) or on the host
# (`./scripts/...` with PYTHONPATH=./backend).
HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (
    os.path.normpath(os.path.join(HERE, "..", "backend")),  # host layout: ./scripts/.. → ./backend
    "/app",                                                 # container layout: /app/scripts/.. → /app
):
    if os.path.isdir(os.path.join(cand, "app")) and cand not in sys.path:
        sys.path.insert(0, cand)
        break

from sqlalchemy import select, func, text

from app.db.session import SessionLocal
from app.db.models import Attachment, KbChunk, KbDocument
from app.services import local_retriever, zhipuai_embed


async def main() -> None:
    if not local_retriever.is_configured():
        print(
            "ZHIPUAI_API_KEY is not set. Populate it in .env and rebuild.",
            file=sys.stderr,
        )
        sys.exit(2)

    print("Zhipu config OK; scanning for chunks without embeddings…")
    async with SessionLocal() as db:
        # Aggregate how many chunks need work, broken down by KB +
        # document, so progress is human-readable.
        rows = (await db.execute(
            select(
                KbDocument.kb_id,
                KbDocument.id,
                Attachment.filename,
                func.count(KbChunk.id),
            )
            .join(KbChunk, KbChunk.kb_doc_id == KbDocument.id)
            .join(Attachment, Attachment.id == KbDocument.attachment_id)
            .where(KbChunk.embedding.is_(None), KbChunk.text != "")
            .group_by(KbDocument.kb_id, KbDocument.id, Attachment.filename)
            .order_by(KbDocument.kb_id, KbDocument.id)
        )).all()
        if not rows:
            print("Nothing to do — every chunk is already embedded.")
            return
        for kb_id, doc_id, name, n in rows:
            print(f"  KB{kb_id} doc{doc_id} {name!r}: {n} chunks")
        total = sum(int(r[3]) for r in rows)
        print(f"Total: {total} chunks across {len(rows)} documents.\n")

    # Walk doc-by-doc; GLM has a 64-text-per-request cap inside
    # `embed_texts`, so we batch with a safety margin (50 / batch).
    started = time.time()
    embedded_total = 0
    for kb_id, doc_id, name, _ in rows:
        async with SessionLocal() as db:
            chunks = (await db.execute(
                select(KbChunk.id, KbChunk.text, KbChunk.page, KbChunk.para)
                .where(
                    KbChunk.kb_doc_id == doc_id,
                    KbChunk.embedding.is_(None),
                )
                .order_by(KbChunk.id)
            )).all()
        if not chunks:
            continue
        print(f"  KB{kb_id} doc{doc_id} {name!r}: embedding {len(chunks)} chunks…", flush=True)

        model = local_retriever.settings.zhipuai_embedding_model
        # Batches of 50 — keeps payloads < 1 MB on average (1024 floats
        # per row × ~10 chars/float representation ≈ 10 KB / row).
        for i in range(0, len(chunks), 50):
            batch = chunks[i : i + 50]
            texts = [c[1] for c in batch]
            try:
                vectors = await zhipuai_embed.embed_texts(texts)
            except Exception as exc:  # noqa: BLE001
                print(f"    batch {i}-{i+len(batch)}: embedding failed: {exc}", file=sys.stderr)
                # Bail out for this doc; the next doc's retry starts
                # fresh. Caller can re-run the script to retry.
                continue
            if len(vectors) != len(batch):
                print(
                    f"    batch {i}: dim mismatch {len(vectors)} vs {len(batch)}",
                    file=sys.stderr,
                )
                continue
            async with SessionLocal() as db:
                for (row_id, *_), vec in zip(batch, vectors):
                    await db.execute(
                        text(
                            "UPDATE kb_chunks SET embedding = CAST(:vec AS vector), "
                            "embedding_model = :model WHERE id = :rid"
                        ),
                        {
                            "vec": "[" + ",".join(f"{x:.7f}" for x in vec) + "]",
                            "model": model,
                            "rid": row_id,
                        },
                    )
                await db.commit()
            embedded_total += len(batch)
            print(f"    embedded {embedded_total}/{sum(int(r[3]) for r in rows)}", flush=True)

    # Stamp the embedding_model on each KB document we touched so the
    # UI shows the model + version.
    async with SessionLocal() as db:
        await db.execute(
            text("UPDATE kb_documents SET embedding_model = :model"),
            {"model": local_retriever.settings.zhipuai_embedding_model},
        )
        await db.commit()

    print(
        f"\nDone. Embedded {embedded_total} chunks in "
        f"{time.time() - started:.1f}s."
    )


if __name__ == "__main__":
    asyncio.run(main())
