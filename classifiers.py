import json
import math
import os
import re
import string

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

_groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])

_SYSTEM_PROMPT = """You are an AI content detection analyzer. Your job is to analyze text and determine the likelihood of AI generation versus human authorship.

CRITICAL DIRECTIVE: You must default to a state of complete uncertainty (0.5). Use the following graduated scale to move away from it:
- Multiple clear, corroborating signals pointing in one direction with little or no counterevidence → move to 0.7–0.9 (AI) or 0.1–0.3 (human)
- Some signals pointing in one direction but with meaningful counterevidence or ambiguity → stay in 0.35–0.65
- Genuinely mixed or inconclusive evidence → stay at or near 0.5

Evaluate the text against the following profiles:

1. Clear AI Signals (Moves score towards 1.0):
- Semantic coherence: Perfectly structured logical arguments with flawless, uninterrupted transitions.
- Stylistic homogeneity: Uniformly polished text, heavy use of hedging (e.g., "it is important to note"), and a suspicious lack of structural variance.
- Pragmatics: Overconfident certainty or the presence of plausible but hallucinated claims without signaled doubt.

2. Clear Human Signals (Moves score towards 0.0):
- Natural variance: Logical leaps, minor backtracking, or authentic shifts in thought.
- Imperfect execution: Genuine grammatical quirks or structural inconsistencies that do not break comprehension.

3. Ambiguous Edge Cases (Anchors score between 0.35–0.65):
- Formal human writing: Academic papers, legal documents, or professional reports that legitimately use structured arguments, passive voice, and hedging.
- The "Cyborg" Writer: Human text that has been heavily polished by AI editing tools (e.g., Grammarly).
- Disguised AI: AI output explicitly prompted to include personal pronouns, anecdotes, or fake typos.
- Non-native English: Human writing that relies on rigid structures or repetitive transitions that incidentally mimic AI patterns.

Before scoring, you must extract evidence for BOTH human and AI authorship and base your score off of that.

Return ONLY a JSON object with exactly these two fields:
{
  "confidence_score": <number between 0.0 and 1.0, where 0.0 = certainly human, 1.0 = certainly AI>,
  "reasoning": "<one or two sentences explaining the most prominent signals that drove your score>"
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


def heuristic_classifier(text: str) -> dict:
    """
    Scores how likely the text is AI-generated using pure structural metrics.

    Metrics (all normalized to 0–1 where higher = more likely AI):
      - burstiness_score  : stddev of sentence lengths in words (raw, not normalized)
      - diversity_score   : type-token ratio — len(unique words) / len(all words)
      - punctuation_density: punctuation characters / total characters

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
    sentences = [s.strip() for s in re.split(r'[.!?]+', text) if s.strip()]
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

    # --- Punctuation density ---
    punct_count = sum(1 for c in text if c in string.punctuation)
    punctuation_density = punct_count / len(text) if text else 0.0

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
      0.00–0.39 → high_confidence_human
      0.40–0.69 → uncertain
      0.70–1.00 → high_confidence_AI
    """
    if confidence >= 0.70:
        return {"attribution": "high_confidence_AI", "label": "Most likely AI 🤖"}
    if confidence >= 0.40:
        return {"attribution": "uncertain", "label": "Cannot determine authenticity ❓"}
    return {"attribution": "high_confidence_human", "label": "Most likely authentic 👍🏾"}
