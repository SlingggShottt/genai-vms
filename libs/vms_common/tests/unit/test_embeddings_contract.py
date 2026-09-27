"""Round-trip test for the embeddings.npz layout (style_guide.md §A.4)."""

from pathlib import Path

import numpy as np
import pytest
from vms_common.contracts.embeddings import (
    InvalidEmbeddingsError,
    build_embeddings_npz,
    load_embeddings_npz,
)

FIXTURE = Path(__file__).parents[2] / "src" / "vms_common" / "fixtures" / "embeddings.npz"


def test_embeddings_fixture_round_trips() -> None:
    result = load_embeddings_npz(FIXTURE.read_bytes())

    assert result["frame_vectors"].shape == (5, 768)
    assert result["frame_ts"].shape == (5,)
    assert result["track_vectors"].shape == (2, 768)
    assert list(result["track_ids"]) == ["cam03-t412", "cam03-t415"]

    # L2-normalized (build_embeddings_npz's own contract, float16 tolerance)
    norms = np.linalg.norm(result["frame_vectors"].astype(np.float32), axis=1)
    assert np.allclose(norms, 1.0, atol=1e-2)


def test_build_then_load_round_trips_a_fresh_payload() -> None:
    frame_vectors = np.ones((3, 4), dtype=np.float32)
    track_vectors = np.ones((1, 4), dtype=np.float32)

    data = build_embeddings_npz(
        frame_vectors=frame_vectors,
        frame_ts=["t0", "t1", "t2"],
        track_vectors=track_vectors,
        track_ids=["cam01-t1"],
    )
    result = load_embeddings_npz(data)

    assert result["frame_vectors"].shape == (3, 4)
    assert list(result["frame_ts"]) == ["t0", "t1", "t2"]
    assert list(result["track_ids"]) == ["cam01-t1"]


def test_build_rejects_frame_vectors_ts_length_mismatch() -> None:
    with pytest.raises(InvalidEmbeddingsError, match="length mismatch"):
        build_embeddings_npz(
            frame_vectors=np.ones((3, 4), dtype=np.float32),
            frame_ts=["t0", "t1"],  # 2, not 3
            track_vectors=np.ones((1, 4), dtype=np.float32),
            track_ids=["cam01-t1"],
        )


def test_build_rejects_track_vectors_ids_length_mismatch() -> None:
    with pytest.raises(InvalidEmbeddingsError, match="length mismatch"):
        build_embeddings_npz(
            frame_vectors=np.ones((1, 4), dtype=np.float32),
            frame_ts=["t0"],
            track_vectors=np.ones((2, 4), dtype=np.float32),
            track_ids=["cam01-t1"],  # 1, not 2
        )


def test_load_rejects_npz_missing_required_keys() -> None:
    import io

    buf = io.BytesIO()
    np.savez(buf, frame_vectors=np.ones((1, 4)))  # missing the other 3 keys

    with pytest.raises(InvalidEmbeddingsError, match="missing keys"):
        load_embeddings_npz(buf.getvalue())
