import json
import math
import os
import re

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

_SYSTEM_PROMPT = """You are an AI content detection analyzer. Follow this exact procedure — do not skip to a score.

1. EXTRACT EVIDENCE. List concrete observations from the text that suggest human authorship, and separately, observations that suggest AI authorship. Base each item on something actually present in the text, not on assumptions about its topic.

2. COMPARE EVIDENCE. Before committing to a verdict, compare evidences for both sides. Not all pieces of evidence are weighed equally, but no signle feature should dominate the decision. If there are signficantly more evidence for one side than another, the score should reflect this.

3. CLASSIFY THE BALANCE — choose exactly one:
   - "one_sided_ai": AI evidence dominates; no credible human counter-argument.
   - "leans_ai": AI evidence dominates but a real counter-argument exists.
   - "mixed": genuinely comparable evidence on both sides, or too little signal to judge. This is a normal, common outcome, not a fallback for text you simply find hard.
   - "leans_human": human evidence dominates but a real counter-argument exists.
   - "one_sided_human": human evidence dominates; no credible AI counter-argument.

4. SCORE WITHIN THE BAND for your chosen category (0.0 = certainly human, 1.0 = certainly AI). The category determines the band — do not pick a number outside it:
   - one_sided_ai: 0.85–0.97
   - leans_ai: 0.65–0.84
   - mixed: 0.40–0.64
   - leans_human: 0.16–0.39
   - one_sided_human: 0.03–0.15

FACTOR TO CONSIDER while gathering evidence (guidance for step 1, not a checklist to match against — new topics will show these in new, unnamed ways, so weigh what's actually in the text over whether it fits a label below):
- Lexical diversity and vocabulary variation
- Sentence length, rhythm, and syntactic diversity
- Stylistic consistency throughout the text
- Predictability and use of common or formulaic phrasing
- Repetition of words, phrases, or rhetorical patterns
- Organizational structure and overall polish
- Information density and variation in detail
- Originality versus generic or templated language
- Presence of concrete personal experiences, sensory details, or idiosyncratic observations
- Natural imperfections such as self-corrections, digressions, uneven pacing, or shifts in focus
- Use of hedging, balanced qualifiers, or overly neutral language

Return ONLY a JSON object with exactly these fields:
{
  "human_evidence": ["<short factual observation>", ...],
  "ai_evidence": ["<short factual observation>", ...],
  "counterargument": "<the single strongest argument against your leaning>",
  "evidence_balance": "<one_sided_ai|leans_ai|mixed|leans_human|one_sided_human>",
  "confidence_score": <number 0.0-1.0, two decimal places, within the band for evidence_balance>,
  "reasoning": "<one or two sentences summarizing the deciding factor>"
}"""


def llm_classifier(text: str) -> dict:
    """
    Calls Groq llama-3.3-70b-versatile to score how likely the text is AI-generated.

    Returns:
        {"confidence_score": float (0–1), "reasoning": str}

    Raises:
        ValueError: if the model response cannot be parsed into the expected schema
        groq.APIError (and subclasses): on any Groq API failure
    """
    response = _groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        temperature=0.0,
    )

    raw = response.choices[0].message.content
    result = json.loads(raw)

    if "confidence_score" not in result or "reasoning" not in result:
        raise ValueError(f"Unexpected response schema from LLM classifier: {raw}")

    result["confidence_score"] = float(result["confidence_score"])
    return result


_ABBREVIATIONS = (
    "mr", "mrs", "ms", "dr", "jr", "sr", "prof", "vs", "etc", "eg", "ie",
    "no", "st", "ave", "fig", "gen", "col", "capt", "gov", "rep", "sen",
)

_DISTINCTIVE_PUNCTUATION = ("—", "–", ";")


def _protect_abbreviation_periods(text: str) -> str:
    """
    Strips periods from initialisms (U.S., U.K., D.C., F.B.I.) and common
    abbreviations (Dr., vs., e.g.) so they aren't mistaken for sentence
    boundaries. Without this, "Data from U.S. Immigration..." splits into
    garbage fragments ("Data from U", "S") that distort the burstiness stddev.
    """
    text = re.sub(r'\b(?:[A-Za-z]\.){2,}', lambda m: m.group(0).replace('.', ''), text)
    pattern = r'\b(' + '|'.join(_ABBREVIATIONS) + r')\.'
    return re.sub(pattern, r'\1', text, flags=re.IGNORECASE)


def heuristic_classifier(text: str) -> dict:
    """
    Scores how likely the text is AI-generated using pure structural metrics.

    Metrics (all normalized to 0–1 where higher = more likely AI):
      - burstiness_score  : stddev of sentence lengths in words (raw, not normalized)
      - diversity_score   : type-token ratio — len(unique words) / len(all words)
      - punctuation_density: density of em dashes/semicolons (marks LLMs overuse),
        NOT overall punctuation — periods/commas are used near-identically by
        humans and AI and carry no signal (see planning.md)

    Confidence score formula (from planning.md):
      burstiness_contribution  = 1 - min(burstiness_score / 20.0, 1.0)
      diversity_contribution   = 1 - diversity_score
      punctuation_contribution = punctuation_density
      confidence_score = (0.50 * burstiness) + (0.35 * diversity) + (0.15 * punctuation)

    Returns:
        {
            "confidence_score": float (0–1),
            "burstiness_score": float (raw stddev of sentence lengths),
            "diversity_score": float (0–1, type-token ratio),
            "punctuation_density": float (0–1),
        }
    """
    # --- Sentence splitting ---
    # Split on sentence-ending punctuation AND line breaks, since list items and
    # paragraphs often lack terminal punctuation; without this a bulleted block
    # collapses into one oversized "sentence" and distorts the burstiness stddev.
    # Abbreviation/initialism periods are protected first so they aren't
    # mistaken for sentence boundaries.
    protected_text = _protect_abbreviation_periods(text)
    raw_units = re.split(r'[.!?]+|\n+', protected_text)
    sentences = []
    for unit in raw_units:
        # Strip leading list markers (-, *, •, "1.", "2)") so they aren't counted as words.
        unit = re.sub(r'^\s*(?:[-*•]|\d+[.)])\s*', '', unit).strip()
        if unit:
            sentences.append(unit)
    sentence_lengths = [len(s.split()) for s in sentences]

    if len(sentence_lengths) < 2:
        burstiness_score = 0.0
    else:
        mean = sum(sentence_lengths) / len(sentence_lengths)
        variance = sum((l - mean) ** 2 for l in sentence_lengths) / len(sentence_lengths)
        burstiness_score = math.sqrt(variance)

    # --- Type-token ratio (vocabulary diversity) ---
    words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
    diversity_score = len(set(words)) / len(words) if words else 0.0

    # --- Punctuation density (em dashes/semicolons only) ---
    # Overall punctuation density sits at a near-constant ~0.02 regardless of
    # authorship (periods/commas don't discriminate), wasting this signal's
    # weight. Em dashes and semicolons are disproportionately overused by
    # LLMs, so density is measured over those marks per word instead, scaled
    # so a heavy user (~1 per 15 words) reaches the 1.0 ceiling.
    distinctive_count = sum(text.count(mark) for mark in _DISTINCTIVE_PUNCTUATION)
    punctuation_density = min(distinctive_count / len(words) * 15.0, 1.0) if words else 0.0

    # --- Weighted confidence score ---
    burstiness_contribution = 1.0 - min(burstiness_score / 20.0, 1.0)
    diversity_contribution = 1.0 - diversity_score
    punctuation_contribution = punctuation_density

    confidence_score = (
        0.50 * burstiness_contribution
        + 0.35 * diversity_contribution
        + 0.15 * punctuation_contribution
    )

    return {
        "confidence_score": round(confidence_score, 4),
        "burstiness_score": round(burstiness_score, 4),
        "diversity_score": round(diversity_score, 4),
        "punctuation_density": round(punctuation_density, 4),
    }


def overall_confidence(text: str, llm_score: float, heuristic_score: float) -> float:
    """
    Combines LLM and heuristic scores using a dynamic weighted average.

    Weight tiers (from planning.md):
      < 300 words : LLM 80%, heuristic 20%
      300–749 words: LLM 60%, heuristic 40%
      750+ words  : LLM 40%, heuristic 60%
    """
    word_count = len(text.split())
    if word_count < 300:
        llm_weight, heuristic_weight = 0.80, 0.20
    elif word_count < 750:
        llm_weight, heuristic_weight = 0.60, 0.40
    else:
        llm_weight, heuristic_weight = 0.40, 0.60
    return round(llm_weight * llm_score + heuristic_weight * heuristic_score, 4)


def generate_transparency_label(confidence: float) -> dict:
    """
    Maps a combined confidence score to an attribution enum and user-facing label.

    Thresholds (from planning.md):
      0.00–0.30 → high_confidence_human
      0.31–0.69 → uncertain
      0.70–1.00 → high_confidence_AI
    """
    if confidence >= 0.70:
        return {"attribution": "high_confidence_AI", "label": "Most likely AI 🤖"}
    if confidence >= 0.31:
        return {"attribution": "uncertain", "label": "Cannot determine authenticity ❓"}
    return {"attribution": "high_confidence_human", "label": "Most likely authentic 👍🏾"}
