"""Hand-checked values for the PhaVR caption and VQA metrics."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "phavr_caption_metrics", Path(__file__).resolve().parents[1] / "caption_metrics.py"
)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

T = m.tokens


def test_tokens_ignore_case_and_punctuation() -> None:
    assert T("A man, in a RED coat; walking.") == ["a", "man", "in", "a", "red", "coat", "walking"]
    assert T("It's 3 o'clock") == ["it's", "3", "o'clock"]


def test_bleu_of_a_caption_with_one_wrong_word_is_the_hand_computed_value() -> None:
    # unigrams 5/6, bigrams 3/5, trigrams 1/4, 4-grams 0/3 -> smoothed 1/(2*3); no brevity penalty
    hyp, ref = T("the cat sat on the mat"), T("the cat is on the mat")
    assert m.bleu([hyp], [ref]) == pytest.approx((5 / 6 * 3 / 5 * 1 / 4 * 1 / 6) ** 0.25)
    assert m.bleu([ref], [ref]) == pytest.approx(1.0)


def test_bleu_punishes_a_caption_that_is_too_short_and_scores_nothing_for_nothing() -> None:
    ref = T("a b c d e f g h")
    assert m.bleu([ref[:4]], [ref]) == pytest.approx(math.exp(1 - 8 / 4))  # every precision is 1
    assert m.bleu([[]], [ref]) == 0.0
    assert 0 < m.bleu([T("x y z w v u t s")], [ref]) < 0.1  # no overlap at all: tiny, not zero


def test_rouge_l_is_the_longest_common_subsequence_f_measure() -> None:
    assert m.rouge_l(T("the cat sat on the mat"), T("the cat is on the mat")) == pytest.approx(
        5 / 6
    )
    # lcs 3: precision 1, recall 3/5, recall-weighted (beta 1.2)
    assert m.rouge_l(T("a b c"), T("a b c d e")) == pytest.approx(2.44 * 1 * 0.6 / (0.6 + 1.44))
    assert m.rouge_l(T("a b"), T("c d")) == 0.0


def test_meteor_exact_matches_the_formula_and_penalises_scrambling() -> None:
    assert m.meteor_exact(T("a b c d"), T("a b c d")) == pytest.approx(1 - 0.5 * (1 / 4) ** 3)
    # all four words found but in three pieces: 1 - 0.5 * (3/4)^3
    assert m.meteor_exact(T("a b d c"), T("a b c d")) == pytest.approx(1 - 0.5 * (3 / 4) ** 3)
    assert m.meteor_exact(T("a b"), T("c d")) == 0.0
    # half the words, recall-weighted: P = 1, R = 1/2, fmean = 0.5 / (0.9 + 0.05) = 0.5263...
    assert m.meteor_exact(T("a b"), T("a b c d")) == pytest.approx(
        0.5 / 0.95 * (1 - 0.5 * (1 / 2) ** 3)
    )


def test_cider_d_rewards_matching_words_that_are_rare_in_the_corpus() -> None:
    refs = [T("a man in a red coat walks left"), T("two women carry bags towards the door"),
            T("a dog sleeps beside the empty bench")]  # fmt: skip
    assert m.cider_d(refs, refs) == pytest.approx([10.0, 10.0, 10.0])  # a perfect copy
    unrelated = T("zebra quantum violin bicycle ocean marble")
    assert m.cider_d([unrelated, refs[1], refs[2]], refs)[0] == 0.0
    partial = T("a man in a blue coat walks right")
    mid = m.cider_d([partial, refs[1], refs[2]], refs)[0]
    assert 0 < mid < 10.0


def test_cider_d_clips_a_word_repeated_more_often_than_the_reference_has_it() -> None:
    refs = [T("red coat man walks"), T("blue bag woman stands"), T("dog bench sleeps empty")]
    # "red" x4 against "red" x1: unigram cosine = min(4i, i) * i / (4i * 2i) = 1/8, i being the
    # idf of "red"; no bigram matches, equal lengths: 10 * (1/8) / 4. Unclipped: four times that.
    spam = m.cider_d([T("red red red red"), refs[1], refs[2]], refs)[0]
    assert spam == pytest.approx(10 * 0.125 / 4)


def test_cider_d_of_a_corpus_of_one_is_zero_because_every_word_is_in_every_document() -> None:
    ref = T("a man in a red coat walks left")
    assert m.cider_d([ref], [ref]) == [0.0]


def test_vqa_counts_separate_right_wrong_missing_and_not_sure() -> None:
    ref = [("q1", "Yes"), ("q2", "No"), ("q3", "Cannot tell"), ("q4", "Yes")]
    pred = [("q1", "Yes"), ("q2", "Yes"), ("q3", "Yes")]  # q4 never answered
    c = m.vqa_counts(ref, pred)
    assert (c["asked"], c["correct"], c["unanswered"]) == (4, 1, 1)
    assert c["answered_what_the_reference_could_not_tell"] == 1
    assert c["cannot_tell_said"] == 0
    unsure = m.vqa_counts(ref, [("q1", "Cannot tell"), ("q3", "Cannot tell")])
    assert (unsure["correct"], unsure["cannot_tell_said"], unsure["cannot_tell_wrongly"]) == (
        1,
        2,
        1,
    )
    assert unsure["unanswered"] == 2
