"""embeddings `.npz` layout — frozen alongside `twin.v1` at P2 day 1
(design_architecture.md §16: `fixtures/embeddings.npz`).

Not a Pydantic model (numpy arrays aren't JSON), so this documents and
validates the four required arrays directly instead:

    frame_vectors: (n_frames, dim) float16, L2-normalized SigLIP2
        embeddings, one per sampled keyframe (every 2s, FR-PER-06).
    frame_ts: (n_frames,) ISO-8601 UTC strings, aligned 1:1 with
        frame_vectors.
    track_vectors: (n_tracks, dim) float16, L2-normalized, one best-crop
        embedding per track per segment.
    track_ids: (n_tracks,) strings, aligned 1:1 with track_vectors.
"""

from __future__ import annotations

import io

import numpy as np

REQUIRED_KEYS = ("frame_vectors", "frame_ts", "track_vectors", "track_ids")


class InvalidEmbeddingsError(ValueError):
    """Raised when an `.npz` payload doesn't match the embeddings layout."""


def build_embeddings_npz(
    *,
    frame_vectors: np.ndarray,
    frame_ts: list[str],
    track_vectors: np.ndarray,
    track_ids: list[str],
) -> bytes:
    """Serialize the four required arrays into `.npz` bytes, ready for S3."""
    _validate_shapes(frame_vectors, frame_ts, track_vectors, track_ids)
    buf = io.BytesIO()
    np.savez(
        buf,
        frame_vectors=np.asarray(frame_vectors, dtype=np.float16),
        frame_ts=np.array(frame_ts, dtype=object),
        track_vectors=np.asarray(track_vectors, dtype=np.float16),
        track_ids=np.array(track_ids, dtype=object),
    )
    return buf.getvalue()


def load_embeddings_npz(data: bytes) -> dict[str, np.ndarray]:
    """Parse `.npz` bytes and validate the embeddings layout."""
    with np.load(io.BytesIO(data), allow_pickle=True) as npz:
        missing = [k for k in REQUIRED_KEYS if k not in npz]
        if missing:
            raise InvalidEmbeddingsError(f"missing keys: {missing}")
        result = {k: npz[k] for k in REQUIRED_KEYS}
    _validate_shapes(
        result["frame_vectors"],
        result["frame_ts"],
        result["track_vectors"],
        result["track_ids"],
    )
    return result


def _validate_shapes(
    frame_vectors: np.ndarray,
    frame_ts: list[str] | np.ndarray,
    track_vectors: np.ndarray,
    track_ids: list[str] | np.ndarray,
) -> None:
    if len(frame_vectors) != len(frame_ts):
        raise InvalidEmbeddingsError(
            f"frame_vectors ({len(frame_vectors)}) and frame_ts ({len(frame_ts)}) length mismatch"
        )
    if len(track_vectors) != len(track_ids):
        raise InvalidEmbeddingsError(
            f"track_vectors ({len(track_vectors)}) and track_ids ({len(track_ids)}) length mismatch"
        )
    if (
        len(frame_vectors)
        and len(track_vectors)
        and frame_vectors.shape[1] != track_vectors.shape[1]
    ):
        raise InvalidEmbeddingsError("frame_vectors and track_vectors must share the same dim")
