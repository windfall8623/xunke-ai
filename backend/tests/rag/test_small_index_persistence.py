"""Small immutable projections must survive Chroma's in-process segment reloads."""

import pytest

from app.rag.artifact_store import OwnerIndexStore
from app.rag.contracts import IndexProfile
from app.rag.ingestion import load_canonical_document
from tests.rag.helpers import FixtureEmbedding, request_for


@pytest.mark.asyncio
async def test_many_small_builds_remain_readable_without_restarting_the_owner(tmp_path):
    built, failures = [], []
    with OwnerIndexStore(tmp_path / "store", process_role="rag_owner") as store:
        # Also preserve a larger collection's incomplete final batch. Its 116
        # chunks cross the normal 100-vector persistence boundary.
        large = request_for(
            tmp_path,
            doc_id="large-tail",
            build="large-build",
            text="x" * 3701,
            profile=IndexProfile(
                embedding_model="fixture-vector-v1",
                embedding_dimensions=3,
                chunk_size=32,
                chunk_overlap=0,
            ),
        )
        built.append(
            await store.build(
                large.model_copy(
                    update={
                        "source": None,
                        "canonical": load_canonical_document(large.source),
                    }
                ),
                FixtureEmbedding(),
            )
        )
        assert built[0].node_count > 100 and built[0].node_count % 100 != 0
        for index in range(36):
            request = request_for(
                tmp_path,
                doc_id=f"small-{index}",
                build=f"build-{index}",
                text=f"# Synthetic source {index}\nCalibration value: {index + 17}.\n",
            )
            canonical = load_canonical_document(request.source)
            built.append(
                await store.build(
                    request.model_copy(update={"source": None, "canonical": canonical}),
                    FixtureEmbedding(),
                )
            )
        for _ in range(2):
            for result in built:
                try:
                    restored = store.read_build(result.to_source_manifest(1))
                    assert restored.node_count == result.node_count
                    assert restored.checksum == result.checksum
                except Exception as exc:
                    failures.append((result.doc_id, str(exc), str(exc.__cause__)))
        assert failures == []
