"""Creates the Qdrant collections in docs/design_architecture.md §6.2
against the `infra` profile's Qdrant. Idempotent. Invoked via
`make qdrant-collections` — requires
`docker compose -f deploy/compose/docker-compose.yml --profile infra up -d qdrant`
(or the full infra profile) to be running first. Same shape as
`create_topics.sh`'s Kafka bootstrap, in Python because collection/payload
index schemas are more naturally expressed via `qdrant-client` than curl.
"""

from __future__ import annotations

import asyncio

from qdrant_client import AsyncQdrantClient
from vms_common.config import QdrantSettings
from vms_common.qdrant.collections import (
    FRAMES_COLLECTION,
    KNOWLEDGE_COLLECTION,
    TRACKS_COLLECTION,
    ensure_collections,
)


async def _amain() -> None:
    settings = QdrantSettings()
    client = AsyncQdrantClient(url=settings.url, api_key=settings.api_key or None)
    try:
        print(f"creating collections at {settings.url} (idempotent, if not already present)")
        await ensure_collections(client)
        for name in (FRAMES_COLLECTION, TRACKS_COLLECTION, KNOWLEDGE_COLLECTION):
            print(f"  ok: {name}")
    finally:
        await client.close()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
