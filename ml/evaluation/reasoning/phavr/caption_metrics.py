"""Caption and VQA metrics for the PhaVR evaluation (P5-J3). Pure, no dependencies.

BLEU-4, ROUGE-L and CIDEr-D follow the usual definitions (the caption-evaluation toolkit's
formulas, one reference per caption). METEOR is NOT the published METEOR: that needs WordNet and a
stemmer downloaded at run time, and this runs offline. `meteor_exact` keeps its shape (the
recall-weighted harmonic mean and the fragmentation penalty) but only matches identical words, so
its numbers are comparable between runs of this harness and with nothing else.
"""

from __future__ import annotations

import math
import re
from collections import Counter

_WORD = re.compile(r"[a-z0-9']+")


def tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _ngrams(words: list[str], n: int) -> list[tuple[str, ...]]:
    return [tuple(words[i : i + n]) for i in range(len(words) - n + 1)]


# ---- BLEU ------------------------------------------------------------------------------------


def bleu(hyps: list[list[str]], refs: list[list[str]], max_n: int = 4) -> float:
    """Corpus BLEU against one reference each. An n-gram order with no match is smoothed the way
    sacreBLEU's `exp` does (1 / (2^k * total)), so a corpus of short captions does not score 0 for
    want of a single 4-gram; an order with no n-grams at all scores 0."""
    clipped = [0] * max_n
    total = [0] * max_n
    hyp_len = ref_len = 0
    for h, r in zip(hyps, refs, strict=True):
        hyp_len += len(h)
        ref_len += len(r)
        for n in range(1, max_n + 1):
            ref_counts = Counter(_ngrams(r, n))
            counts = Counter(_ngrams(h, n))
            clipped[n - 1] += sum(min(c, ref_counts[g]) for g, c in counts.items())
            total[n - 1] += max(len(h) - n + 1, 0)
    if hyp_len == 0 or any(t == 0 for t in total):
        return 0.0
    smooth = 1.0
    log_p = 0.0
    for c, t in zip(clipped, total, strict=True):
        if c == 0:
            smooth *= 2
            log_p += math.log(1.0 / (smooth * t))
        else:
            log_p += math.log(c / t)
    brevity = 1.0 if hyp_len > ref_len else math.exp(1 - ref_len / hyp_len)
    return brevity * math.exp(log_p / max_n)


# ---- ROUGE-L ---------------------------------------------------------------------------------


def _lcs(a: list[str], b: list[str]) -> int:
    prev = [0] * (len(b) + 1)
    for x in a:
        cur = [0]
        for j, y in enumerate(b, 1):
            cur.append(prev[j - 1] + 1 if x == y else max(prev[j], cur[-1]))
        prev = cur
    return prev[-1]


def rouge_l(hyp: list[str], ref: list[str], beta: float = 1.2) -> float:
    """F-measure of the longest common subsequence, recall weighted by `beta` (1.2, as the
    caption-evaluation toolkit has it)."""
    lcs = _lcs(hyp, ref)
    if lcs == 0:
        return 0.0
    p, r = lcs / len(hyp), lcs / len(ref)
    return ((1 + beta**2) * p * r) / (r + beta**2 * p)


# ---- METEOR (exact matches only) -------------------------------------------------------------


def meteor_exact(hyp: list[str], ref: list[str], alpha: float = 0.9) -> float:
    """METEOR's shape on exact word matches: F-mean with recall weighted (`alpha`), times
    1 - 0.5 * (chunks / matches)^3. Words are aligned greedily, leftmost first."""
    if not hyp or not ref:
        return 0.0
    free: dict[str, list[int]] = {}
    for j, w in enumerate(ref):
        free.setdefault(w, []).append(j)
    aligned: list[int | None] = []
    for w in hyp:
        spots = free.get(w)
        aligned.append(spots.pop(0) if spots else None)
    matches = [a for a in aligned if a is not None]
    if not matches:
        return 0.0
    p, r = len(matches) / len(hyp), len(matches) / len(ref)
    fmean = p * r / (alpha * p + (1 - alpha) * r)
    chunks = 1 + sum(1 for a, b in zip(matches, matches[1:], strict=False) if b != a + 1)
    return fmean * (1 - 0.5 * (chunks / len(matches)) ** 3)


# ---- CIDEr-D ---------------------------------------------------------------------------------


def cider_d(
    hyps: list[list[str]], refs: list[list[str]], n: int = 4, sigma: float = 6.0
) -> list[float]:
    """CIDEr-D of each caption (scaled by 10): tf-idf weighted n-gram cosine similarity with a
    clip on the hypothesis counts and a Gaussian penalty on the length difference. The idf comes
    from the references of this corpus, so a caption's score depends on the other captions; a
    corpus of one has idf 0 everywhere and scores 0."""
    docs = Counter()
    for r in refs:
        docs.update({g for k in range(1, n + 1) for g in _ngrams(r, k)})
    log_n = math.log(len(refs)) if refs else 0.0

    def vector(words: list[str]) -> tuple[list[dict], list[float]]:
        vecs: list[dict] = []
        norms: list[float] = []
        for k in range(1, n + 1):
            vec = {
                g: c * (log_n - math.log(max(1.0, docs[g])))
                for g, c in Counter(_ngrams(words, k)).items()
            }
            vecs.append(vec)
            norms.append(math.sqrt(sum(v * v for v in vec.values())))
        return vecs, norms

    scores = []
    for h, r in zip(hyps, refs, strict=True):
        vh, nh = vector(h)
        vr, nr = vector(r)
        penalty = math.exp(-((len(h) - len(r)) ** 2) / (2 * sigma**2))
        total = 0.0
        for k in range(n):
            val = sum(min(w, vr[k].get(g, 0.0)) * vr[k].get(g, 0.0) for g, w in vh[k].items())
            if nh[k] and nr[k]:
                val /= nh[k] * nr[k]
            total += val * penalty
        scores.append(10.0 * total / n)
    return scores


# ---- VQA -------------------------------------------------------------------------------------


def vqa_counts(
    reference: list[tuple[str, str]],
    predicted: list[tuple[str, str]],
    cannot_tell: str = "Cannot tell",
) -> dict[str, int]:
    """Per sample: of the questions asked (the reference's), how many the answer got right, how many
    it left unanswered (or answered outside the vocabulary, which the service drops), and how many
    times it said "Cannot tell" where the reference had a real answer, and how many times it gave an
    answer where the reference could not tell."""
    given = dict(predicted)
    out = {"asked": len(reference), "correct": 0, "unanswered": 0, "cannot_tell_said": 0,
           "cannot_tell_wrongly": 0, "answered_what_the_reference_could_not_tell": 0}  # fmt: skip
    for qid, truth in reference:
        said = given.get(qid)
        if said is None:
            out["unanswered"] += 1
            continue
        out["correct"] += said == truth
        if said == cannot_tell:
            out["cannot_tell_said"] += 1
            if truth != cannot_tell:
                out["cannot_tell_wrongly"] += 1
        if truth == cannot_tell and said != cannot_tell:
            out["answered_what_the_reference_could_not_tell"] += 1
    return out
