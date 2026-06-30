"""
Manual verification tests for llm_classifier().

Run with:  pytest test_llm_classifier.py -v -s

Expected score ranges are based on planning.md confidence thresholds:
  0.00–0.39  → high_confidence_human
  0.40–0.69  → uncertain
  0.70–1.00  → high_confidence_AI
"""

from classifiers import llm_classifier

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
    "smarter decision is Option 2: Take out the loans only as you need them "
    "(semester by semester).\n\n"
    "The primary reason is a concept called \"Negative Arbitrage.\" Essentially, the interest you "
    "pay on the loan is significantly higher than the interest you can earn in a savings account. "
    "\"Saving\" borrowed money will actively cost you money every single day "
    "it sits in your account.\n\n"
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
        f"  score    : {result['confidence_score']:.3f}  (expected {lo}–{hi})\n"
        f"  reasoning: {result['reasoning']}"
    )


def test_standard_human():
    """Clearly casual human writing — should land in human-leaning range (0.0–0.45).
    Range is wider than the 0.39 label threshold because the LLM signal is one component
    of a two-signal system; the combined score is the authoritative classification."""
    expected = (0.0, 0.45)
    result = llm_classifier(STANDARD_HUMAN)
    _print_result("Standard human (social caption)", result, expected)
    lo, hi = expected
    assert lo <= result["confidence_score"] <= hi, (
        f"Expected score in {lo}–{hi}, got {result['confidence_score']:.3f}. "
        f"Reasoning: {result['reasoning']}"
    )


def test_human_looks_ai():
    """Formal academic writing by a human — may fool the classifier; wide range (0.2–0.69)."""
    expected = (0.2, 0.69)
    result = llm_classifier(HUMAN_LOOKS_AI)
    _print_result("Human that looks AI (academic article)", result, expected)
    lo, hi = expected
    assert lo <= result["confidence_score"] <= hi, (
        f"Expected score in {lo}–{hi}, got {result['confidence_score']:.3f}. "
        f"Reasoning: {result['reasoning']}"
    )


def test_standard_ai():
    """Clearly AI-generated financial advice — should land in high_confidence_AI band (0.7–1.0)."""
    expected = (0.7, 1.0)
    result = llm_classifier(STANDARD_AI)
    _print_result("Standard AI text (Gemini financial advice)", result, expected)
    lo, hi = expected
    assert lo <= result["confidence_score"] <= hi, (
        f"Expected score in {lo}–{hi}, got {result['confidence_score']:.3f}. "
        f"Reasoning: {result['reasoning']}"
    )


def test_ai_poses_as_human():
    """AI instructed to mimic human warmth — should still lean AI (0.45–1.0)."""
    expected = (0.45, 1.0)
    result = llm_classifier(AI_POSES_AS_HUMAN)
    _print_result("AI posing as human (birthday message)", result, expected)
    lo, hi = expected
    assert lo <= result["confidence_score"] <= hi, (
        f"Expected score in {lo}–{hi}, got {result['confidence_score']:.3f}. "
        f"Reasoning: {result['reasoning']}"
    )
