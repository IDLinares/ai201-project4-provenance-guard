"""
Manual verification tests for heuristic_classifier().

Run with:  pytest test_heuristic_classifier.py -v -s

Expected score ranges are based on planning.md confidence thresholds:
  0.00–0.39  → high_confidence_human
  0.40–0.69  → uncertain
  0.70–1.00  → high_confidence_AI

Note: the heuristic signal measures structure only, not semantics. Ranges are wider
than the LLM tests and the edge cases may behave differently:
  - Academic article: uniformly long sentences + repeated domain vocabulary score
    structurally similar to AI, so the ceiling is higher than you might expect.
  - AI birthday message: mimics conversational rhythm and sentence variety, so
    structurally it may read more human than the LLM signal found.
"""

import pytest
from classifiers import heuristic_classifier

STANDARD_HUMAN = (
    "Year in Review: Honestly a slower, chill year spending time with friends and family. "
    "Getting closer to the people and things that matter and really figuring out what I want "
    "to do. Picking up new skills, trying new things, but finding routine and simplicity. "
    "Definitely looking forward to next year moving up and more growth with the people I love. "
    "🎊🎉🎊🎉"
)

HUMAN_LOOKS_AI = (
    "Cross-sectional analyses revealed significant relationships of drug abuse/dependence and "
    "disruptive behavior disorders with adolescent smoking, even after the co-occurrence of all "
    "other disorders was controlled. Prospectively, smoking was found to increase the risk of "
    "developing an episode of MDD and drug abuse/dependence, after adjusting for other disorders. "
    "Finally, only lifetime prevalence of MDD remained a significant predictor of smoking onset, "
    "after controlling for other disorders. Gender did not moderate any of the relationships "
    "between psychopathology and smoking."
)

STANDARD_AI = (
    "Based on the current interest rate environment and how student loans work, the financially "
    "smarter decision is Option 2: Take out the loans only as you need them (semester by semester).\n\n"
    "The primary reason is a concept called \"Negative Arbitrage.\" Essentially, the interest you "
    "pay on the loan is significantly higher than the interest you can earn in a savings account. "
    "\"Saving\" borrowed money will actively cost you money every single day it sits in your account.\n\n"
    "Here is a detailed breakdown of why waiting is the better financial move, along with the pros "
    "and cons of each option."
)

AI_POSES_AS_HUMAN = (
    "Happy 50th Birthday, Mom!\n\n"
    "Half a century looks absolutely incredible on you. I wanted to take a moment today just to "
    "pause and say thank you for everything. Raising me on your own couldn't have been easy, but "
    "you always found a way to make it work. Between the exhausting hours at work, making sure "
    "there was always a warm dinner on the table, and keeping the house running on top of it "
    "all—you sacrificed so much to give me the best life possible.\n\n"
    "I know I probably don't say it nearly enough, but I recognize everything you did to shape me "
    "into the man I am today. Your strength and unconditional love mean the world to me. I hope "
    "you take today to finally kick back, relax, and celebrate yourself for a change. You've more "
    "than earned it.\n\nHave the best birthday. I love you so much!"
)


def _print_result(label: str, result: dict, expected_range: tuple):
    lo, hi = expected_range
    within = lo <= result["confidence_score"] <= hi
    status = "PASS" if within else "FAIL"
    print(
        f"\n[{status}] {label}\n"
        f"  confidence        : {result['confidence_score']:.4f}  (expected {lo}–{hi})\n"
        f"  burstiness_score  : {result['burstiness_score']:.4f}  (stddev of sentence lengths; closer to 0 = AI)\n"
        f"  diversity_score   : {result['diversity_score']:.4f}  (type-token ratio; lower = more AI-like)\n"
        f"  punctuation_density: {result['punctuation_density']:.4f}  (higher = more AI-like)"
    )


def test_standard_human():
    """Casual social caption — varied short sentences, high vocab diversity, low punctuation.
    Should score low (high_confidence_human band: 0.0–0.39)."""
    expected = (0.0, 0.45)
    result = heuristic_classifier(STANDARD_HUMAN)
    _print_result("Standard human (social caption)", result, expected)
    lo, hi = expected
    assert lo <= result["confidence_score"] <= hi, (
        f"Expected score in {lo}–{hi}, got {result['confidence_score']:.4f}.\n"
        f"  burstiness={result['burstiness_score']}, diversity={result['diversity_score']}, "
        f"punctuation={result['punctuation_density']}"
    )


def test_human_looks_ai():
    """Academic article — uniformly long sentences (low burstiness) and repeated domain
    vocabulary (low TTR) both push structural score high. Wide range expected. (0.4–0.80)"""
    expected = (0.40, 0.80)
    result = heuristic_classifier(HUMAN_LOOKS_AI)
    _print_result("Human that looks AI (academic article)", result, expected)
    lo, hi = expected
    assert lo <= result["confidence_score"] <= hi, (
        f"Expected score in {lo}–{hi}, got {result['confidence_score']:.4f}.\n"
        f"  burstiness={result['burstiness_score']}, diversity={result['diversity_score']}, "
        f"punctuation={result['punctuation_density']}"
    )


def test_standard_ai():
    """Clearly AI-generated financial advice — structured paragraphs, moderate sentence
    variety. Should score in uncertain-to-AI band (0.35–0.70)."""
    expected = (0.35, 0.70)
    result = heuristic_classifier(STANDARD_AI)
    _print_result("Standard AI text (Gemini financial advice)", result, expected)
    lo, hi = expected
    assert lo <= result["confidence_score"] <= hi, (
        f"Expected score in {lo}–{hi}, got {result['confidence_score']:.4f}.\n"
        f"  burstiness={result['burstiness_score']}, diversity={result['diversity_score']}, "
        f"punctuation={result['punctuation_density']}"
    )


def test_ai_poses_as_human():
    """AI mimicking human warmth — conversational rhythm and sentence variety may read
    structurally human. Wider lower floor than standard AI. (0.25–0.65)"""
    expected = (0.25, 0.65)
    result = heuristic_classifier(AI_POSES_AS_HUMAN)
    _print_result("AI posing as human (birthday message)", result, expected)
    lo, hi = expected
    assert lo <= result["confidence_score"] <= hi, (
        f"Expected score in {lo}–{hi}, got {result['confidence_score']:.4f}.\n"
        f"  burstiness={result['burstiness_score']}, diversity={result['diversity_score']}, "
        f"punctuation={result['punctuation_density']}"
    )
