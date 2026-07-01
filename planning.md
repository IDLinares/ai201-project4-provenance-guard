# Project 4 Planning: Provenance Guard

---

## Goal

Create a multi-signal AI content classifcation system that takes submitted text content, determines a confidence score for whether the system believes content is AI or Human generated, provides a transparency label to the user about the content, and allows for appeals from creators who believe their content was misclassified.

The system should also have production safety infrastructue like rate limiting and structured audit logging.

---

## API Endpoints

There will be 3 main API endpoints needed:

### POST /submit

**What it accepts**
A JSON body with text and creator_id fields as follows:

```JSON
{
    "text": (str),
    "creator_id": (str)
}
```

- "text": Holds the content that the user is submitting
- "creator_id": Id of the user submitting the content

**What it returns**
A JSON body with content_id, attribution, confidence, and label fields as follows:

```JSON
{
    "content_id": (str),
    "attribution": "<high_confidence_AI, high_confidence_human, uncertain" (str),
    "confidence": "<0-1>" (number),
    "label": (string)

}
```

- "content_id": An id assigned to a piece of text submitted to the system
- "attribution": A string describing the system's confidence in its label. Will be an enum (high_confidence_AI, high_confidence_human, uncertain)
- "confidence": The actual number between 0 (Does not know at all) and 1 (100% certain) of how confident the system is in its determination of the label for the text
- "label": The actual label that will be provided to the user about their text. Will be an enum as well (High-confidence AI, uncertain, High-confidence Human)

### POST /appeal

**What it accepts**
A JSON body with content_id and reasoning fields as follows:

```JSON
{
    "content_id": (str),
    "creator_id": (str),
    "reasoning": (str)
}
```

- "content_id": The id of the text the user wants to appeal the label of
- "creator_id": Id of the user submitting the appeal
- "reasoning": A string explanation of why the labeling on the text should be changed

**What it returns**
A successful response returns a JSON body with content_id, status, and message fields as follows:

```JSON
{
    "content_id": (str),
    "status": "<under_review, approved, denied, not_appealed>" (str),
    "message": (str)

}
```

An error response for an unauthorized user trying to submit an appeal for an AI/uncertain flagged submission returns a JSON body with an error message:

```JSON
{
    "error": "Unauthorized: creator_id does not match the original submitter for this content"
}
```

- "content_id": The id of the text the user wants to appeal the label of
- "status": A string describing the current status of a piece of text. Will be an enum (under_review, approved, denied, not_appealed)
- "message": A string message for the user explaining the status of the appeal

### GET /logs

**What is accepts**
GET HTTP Method - No request body

**What it returns**
A list of JSONs for each text entry that has been submitted into the system. An example JSON log in the list would look as follows:

```JSON
{
  "content_id": (str),
  "creator_id": (str),
  "timestamp": (datetime),
  "attribution": "<high_confidence_AI, high_confidence_human, uncertain>" (str - enum),
  "confidence": "<0-1>" (number),
  "status": "<under_review, approved, denied, not_appealed>" (str),
}
```

- "content_id": An id assigned to a piece of text submitted to the system
- "creator_id": Id of the user submitting the content
- "timestamp": The datetime of when a piece of text was submitted
- "attribution": A string describing the system's confidence in its label. Will be an enum (high_confidence_AI, high_confidence_human, uncertain)
- "confidence": The actual number between 0 (Does not know at all) and 1 (100% certain) of how confident the system is in its determination of the label for the text
- "status": A string describing the current status of a piece of text. Will be an enum (under_review, approved, denied, not_appealed)

### Rate Limiting

Rate limiting is applied to all three endpoints to prevent abuse and protect the system from being overloaded.

**Limiter**
`flask-limiter` (IP-based via `get_remote_address`)

**/submit limits**
The submit endpoint will have a limit of 10 per minute up to a max of 100 per day. This is a reasonable limit for submitting content to the system from one person without spamming it.

**/appeal limits**
The appeal endpoint has two layers of protection:

1. **Application logic** (`appeal_exists()`): Enforces one appeal per content per creator by checking the audit log before allowing a new appeal. `flask-limiter` cannot enforce content-aware rules natively, so this layer handles the business rule.
2. **IP rate limit**: 5 appeals per minute per IP address as a general DOS protection layer against scripted flooding.

**/logs limits**
The logs endpoint has a limit of 30 requests per minute per IP to prevent bulk log scraping while keeping the endpoint accessible for normal use.

---

## Detection Signals

To classify the text that is submitted to Provenance Guard, two distinct detection signals will score the text and then these scores will be combined to create an overall confidence score:

### LLM Classifier - Semantic signal

**LLM to be used**
Groq - `llama-3.3-70b-versatile` (Free tier)

**What it measures**
It measures semantic and stylistic coherence holistically.

**What the output looks like**
Rather than asking the LLM to jump straight to a number, the prompt forces a procedure: extract evidence for both human and AI authorship, construct the strongest counter-argument against its own leaning, classify how one-sided the evidence is, then pick a score bounded by that classification. This replaced an earlier version that asked for a direct holistic score — that version required constant checklist patches as new topics/genres surfaced patterns not on the list (a form of overfitting to the specific texts it had been tuned against) and it was systematically overconfident, since nothing forced the model to seriously weigh the opposing side before committing to a number.

The LLM returns a structured JSON as follows:

```JSON
    {
        "human_evidence": ["<short factual observation>", ...],
        "ai_evidence": ["<short factual observation>", ...],
        "counterargument": "<the single strongest argument against the model's leaning>",
        "evidence_balance": "<one_sided_ai|leans_ai|mixed|leans_human|one_sided_human>",
        "confidence_score": "(num) <0-1>",
        "reasoning": "<Short explanation of the deciding factor>"
    }
```

- "human_evidence" / "ai_evidence": Concrete observations extracted from the text supporting each side, gathered before any score is picked
- "counterargument": Forces the model to argue against its own leaning before committing to a verdict; if no credible counter-argument exists, that absence is itself treated as a signal of one-sidedness
- "evidence_balance": A categorical verdict (one_sided_ai, leans_ai, mixed, leans_human, one_sided_human) chosen before the numeric score
- "confidence_score": A score between 0 and 1, constrained to a band determined by "evidence_balance" (e.g. "mixed" → 0.40–0.64) so the number reflects a real classification rather than an arbitrary pick
- "reasoning": A short text description of the deciding factor

Only "confidence_score" and "reasoning" are consumed downstream (`app.py`); the other fields exist to structure the model's reasoning process and are not currently persisted to the audit log.

**Differences between AI and Human**

The system prompt treats these as non-exhaustive guidance for evidence-gathering, not a checklist to pattern-match against, since new topics keep surfacing new phrasings of the same underlying tells:

- Stylistic homogeneity: Uniformly polished tone, hedging/connective filler, little variance in rhythm.
- Structural symmetry: Near-equal-length parallel sections covering multiple sub-topics, often opening with a thesis and closing with a restatement of it (the "essay outline" shape) — found to be a real AI tell distinct from sentence-level phrasing (e.g. a Gemini response comparing three presidential administrations in three symmetric paragraphs, bookended by a restated thesis).
- Didactic/assistant framing: Writing AS an assistant answering a reader — direct verdicts, defining terms for the reader, scaffolding that announces its own structure. A strong AI tell even when the content is specific and substantive.
- Natural variance (human signal): Logical leaps, backtracking, authentic shifts in thought, specific lived detail, genuine personal voice.
- Register is not content (human signal, with an override): Formal/academic/technical register alone is NOT evidence of AI — dense, source-grounded content written as authored prose for the record leans human even when polished, UNLESS it also shows structural symmetry or didactic framing, which override register.

**What it misses**
While the LLM understands semantic context, it does not provide the mathematical precision to detect specific structural anomalies. Provenance can be deliberately masked (AI told to add typos/anecdotes, or human text heavily AI-polished), and such text may be genuinely indistinguishable from its disguise — the prompt treats that as a reason to land in "mixed" rather than guess, but a well-disguised case can still land human-leaning (an accepted, documented limitation rather than something to keep chasing).

### Stylometric Heuristics - Structural signal

**How it will be implemented**
Pure Python functions will compute this

**What it measures**
It measures statistical properties that differ between human and AI writing. Metrics include:

- Sentence length variance
- Type-token ratio (vocabulary diversity)
- Punctuation density

**What the output looks like**
I will have my function return a JSON with an overall confidence score, burstiness score, diversity score, and punctuation density score as follows:

```JSON
{
    "confidence_score": "<0-1>",
    "burstiness_score": "<stddev of sentence lengths>",
    "diversity_score": "<0-1, type-token ratio>",
    "punctuation_density": "<0-1, density of em dashes/semicolons per word, scaled>"
}
```

- "confidence_score": A score between 0 and 1 evaluating how confident that classifier is that the whole text is AI-generated with 1 being 100% certain
- "burstiness_score": A score measuring the standard deviation of sentence lengths with scores closer to 0 meaning every sentence is roughly the same length (more likely AI generated). Sentence splitting protects initialisms and common abbreviations (U.S., Dr., vs.) from being mistaken for sentence boundaries — without this, "U.S." fragments into garbage 1-word "sentences" that inflate the stddev and bias the score away from AI.
- "diversity_score": A score between 0 and 1 measuring the richness of the vocabulary (lower scores tend to lean AI generated because of repetitive and safe vocabulary; len(set(tokens)) / len(tokens))
- "punctuation_density": A score between 0 and 1 measuring the density of em dashes and semicolons specifically (marks disproportionately overused by LLMs), not punctuation overall. Overall punctuation density (periods/commas) sits at a near-constant ~0.02 regardless of authorship and carries no signal, which was wasting this metric's weight in the combined score. Density is computed as (count of em dashes + semicolons) / word count, scaled so ~1 per 15 words reaches the 1.0 ceiling.

**How the confidence score is calculated**
Each metric is first normalized to a 0–1 scale where the closer to 1 = more likely AI:

- burstiness_contribution = 1 - min(burstiness_score / 20.0, 1.0): low variance in sentence length signals AI; the raw stddev is capped at 20 words as a practical ceiling before inverting. Note: burstiness is a weak structural separator — human and AI prose both tend to fall in the ~5–10 stddev band, so this signal alone cannot reliably distinguish them. A lower cap (e.g. 9) was tried but only shifted every score downward toward "human" rather than improving separation, so the cap stays at 20
- diversity_contribution = 1 - diversity_score: low vocabulary diversity signals AI; TTR is already 0–1 so just invert it
- punctuation_contribution = punctuation_density: higher punctuation density signals AI; already 0–1, no inversion needed
  Then the weighted average:

confidence_score = (0.50 × burstiness_contribution) + (0.35 × diversity_contribution) + (0.15 × punctuation_contribution)

**Differences between AI and Human**

- Burstiness: Sentence length and structure tends to be much more uniform when AI generated. Human writing tends to have a mix of short, punchy sentences wiht long, complex ones.
- Diversity: Vocabulary richness tends to be much safer and more repetitive when AI generated compared to the unpredictability of human writing.
- Punctuation: AI-generated text tends to overuse em dash and has very uniform and perfect punctuation usage, while human writing has natural inconsistencies and intentional hesitations.

**What it misses**
Since this is strictly structural, it cannot capture nuance such as context, intent, and meaning that aids in determining the likelihood of a text being human-generated or not.

### Combining Scores

For this dual signal setup I will use a dynamic weighted average to combine the scores since the length of the text affects the efficacy of each signal. Shorter text is less useful to the structural signal since there's just less "struture" to analyze so the LLM should have a stronger weight in those situations. As text becomes longer, structural patterns become more apparent, so it can take over a larger weight.

- Shorter text (< 300 words): LLM weight = 80%, Stylometry = 20%
- Medium text (> 300 words & < 750): LLM weight = 60%, Stylometry = 40%
- Longer text (> 750 words): LLM weight = 40%, Stylometry = 60%

---

## Uncertainty Representation

### Combined Confidence Score Thresholds

**0-0.30**
Fairly confident that the text is not AI-generated.

**0.31-0.69**
Unsure whether the text is AI-generated or not

**0.7-1.0**
Fairly confident that the text is AI-generated.

---

## Transparency Label Design

### 0-0.30 Label

The system returns to the user "Most likely authentic 👍🏾"
Attribution: "high_confidence_human"

### 0.31-0.69 Label

The system returns to the user "Cannot determine authenticity ❓"
Attribution: "uncertain"

### 0.7-1.0 Label

The system returns to the user "Most likely AI 🤖"
Attribution: "high_confidence_AI"

---

## Appeals Workflow

### Submitting an Appeal

**For text flagged as AI or uncertain**
Only the creator of the submitted text can submit an appeal with their reasoning as to why they would like a reevaluation (trying to resolve a potential false positive). This makes the most sense since text flagged as AI is most detrimental to the creator, and they would be the only ones who could reasonably argue the authenticity of their text.

**For text flagged as authentic**
Any user can submit an appeal for text flagged authentic since the appeal is most likely to raise an issue exposing why this text is actually AI-generated (catching a false negative).

**Rate Limiting**
In both situations, we would not want the system to get spammed with appeals so `Flask-limiter` will be used to set a limt of one appeal per content per creator.

**Necessary Information**
A creator will have to submit their `creator_id`, `content_id`, and `reasoning` for the appeal for a submission that is flagged as AI or uncertain. If the provided `creator_id` does not match the `creator_id` of the submission, then an error is thrown:

{ "error": "Unauthorized: creator_id does not match the original submitter for this content" }

For a submission that is flagged as human, anyone is able to request an appeal on that content to double check its authenticity.

### System Response to an Appeal

**Status Changes**
The status field of a content submission automatically changes to `under_review` after an appeal is submitted through the `/appeal` endpoint.

For this project, appeal status (`under_review` → `approved/denied`) is updated via a direct write to the audit log, simulating a human reviewer action.

**Logs**
The logs update with a brand new log with a `timestamp` of when the appeal was submitted and the status becomes `under_review`. All other fields should match when the text was originally submitted.

**Client Side View**
An appeal queue should show a list of all current appeals that still have status `under_review` with the `creator_id` of who submitted the appeal, `content_id` for the id of the submitted text, and `reasoning` for the appeal.

### False Positive Trace

Here is an example scenario of a false positive occurring in the system:

"A student submits a formal academic essay. The stylometric signal returns 0.72 because the sentences are uniform. The LLM returns 0.65 because of hedged language. The weighted average lands at 0.68, which falls in the uncertain band. The label reads 'Cannot determine authenticity.' The creator submits an appeal with their correct `creator_id` for that `content_id` with the reasoning being that they are as student writing an academic paper following strict guidelines. The system creates a log setting the status of the content to `under_review`. The user sees a message that their post is now under review."

## Anticipated Edge Cases

**Short text without much structure (<300 words)**
I could see this being a difficult case to classify accurately and consistently because the heavy lifting will be on the LLM without much actual text to structurally analyze. As such, the LLM will be generating the majority of the weight for the overall confidence score and even then, the shorter the text the less semantics and context the LLM has to use, so I could imagine it having to make more assumptions as well.

**Technical text with clear cut strcture**
A lot of technical text (such as manuals) tend to have very strict structure and neutral tone regardless of whether it is written by a human or AI, so even with a dynamic weighted average for the overall confidence score, I could see the system mislabeling these as well or consistently returning an uncertain result.

## System Architecture

### Submit Endpoint Pipeline

```
                                                            User Submission

                                                                   │
                                                                   │    {text: str, creator_id: str}
                                                                   │
                                                  ───────────────── ──────────────────
                                                 │                                    │
                                                 │                                    │
                                                 │                                    │
                                                 ▼                                    ▼
                                       llm_classifier(text)                  heuristic_classifier(text)

                                                 │                                    │
                                                 │                                    │
                                                 │                                    │
{confidence_score: <0-1> (num), reasoning: str}  │                                    │ {confidence_score: <0-1>...}
                                                 └───────────────── ──────────────────┘
                                                                   │
                                                                   │
                                                                   ▼
                                                overall_confidence(llm_score,heuristic_score)
                                                                   │
                                                                   │   {overall_confidence_score: <0-1> (num)}
                                                                   ▼
                                                    generate_transparency_label(overall_confidence_score)

                                                                   │
                                                                   │   {content_id: str,
                                                                   │    attribution: <high_confidence_AI, high_confidence_human, uncertain>,
                                                                   │    confidence: <0-1> (num),
                                                                   │    label: str}
                                                                   │
                                                                   │
                                                                   │
                                                                   │
                                                                   ├────► log_interaction()    ◄──── Side effect: appends to logs/audit.jsonl
                                                                   │
                                                                   │
                                                                   │
                                                                   ▼
```

The submission flow takes a user text submission through the `/submit` endpoint and passes it through the LLM classifier and a heuristic classifier. Together, the two scores from those classifiers are passed into an overall confidence calculator to generate a transparency label. The label is returned to the user and this interaction is logged with the content of the text, label, and attribution together.

### Appeals Endpoint Pipeline

(Not fully implementing the reevaluation of the text, just the generation and logging of an appeal)

```
            User Appeal
                 │
                 │  {content_id: str, creator_id: str, reasoning: str}
                 │
                 ▼
create_appeal(content_id,creator_id,reasoning)

                 │
                 │  {content_id:str, status: <under_review,approved,denied,not_appealed>,message:str}
                 │
                 ├──────►   log_interaction()  ◄─── Side effect: Appends appeal to logs/audit.jsonl
                 │
                 ▼
Return message about appeal status to user
```

The appeal flow takes a content_id from the user and the reasoning for the appeal and passes it into a system that generates an appeal. The appeal is logged and the user gets a message about the status of the appeal (which will be under review since they submitted an appeal).

## AI Tool Plan

### Milestone 3 - Submission Endpoint and First Signal

1. AI tool used: Claude

2. Input: I will provide my `/submit` endpoint in my API endpoints section, my llm classifier detection signal, and my submit endpoint pipeline ASCII diagram and ask it to generate a Flask app skeleton and function for the first detection signal.

3. Verifying Output: I will create 4 test inputs: a standard human generated text, a human generated text that looks AI, a standard AI generated text, and an AI generated text that I ask to pose as human and evalute the scores that are returned by this first signal function (making sure the different texts have different confidence scores). Then, I will wire it up to the endpoint.

### Milestone 4 - Second signal and Confidence Scoring

1. AI tool used: Claude

2. Input: I will provide my `/submit` endpoint in my API endpoints section, my stylometric heuristics detection signal, my uncertainty representation, and my ASCII diagram and ask it to generate the second function signal logic and overall confidence scoring logic.

3. Verifying Output: I will provide the same 4 test inputs: a standard human generated text, a human generated text that looks AI, a standard AI generated text, and an AI generated text that I ask to pose as human and evalute the scores that are returned by this second signal function and then the overall confidence scores. I will check to make sure the scores line up as expected between clearly AI text and clearly human text for the second signal and the math calculates properly for the overall calcuation. Then, I will wire it up to the endpoint.

### Milestone 5 - Production Layer

1. AI tool used: Claude

2. Input: I will provide the transparency label design, my appeals workflow, and my appeals endpoint pipeline ASCII diagram and ask it to generate my label generation logic and the `/appeal` endpoint.

3. Verifying Output: I will test the output by making sure all 3 labels are reachable using the inputs I created before and that when an appeal happens, I can see the updated status in the logs and a message returned to the user.
