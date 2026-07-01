# Provenance Guard - Project 4

Provenance Guard is multi-signal AI content classifcation system that takes submitted text content, determines a confidence score for whether the system believes the content was made by AI or a human, provides a transparency label to the user about the content, and allows for appeals for submissions that may have been misclassified.

The system should also has production safety infrastructue like rate limiting and structured audit logging.

---

## System Architecture

### Submission Endpoint Pipeline

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

---

## Detection Signals

To classify the text that is submitted to Provenance Guard, two distinct detection signals score the text and then these scores combine to create an overall confidence score:

### LLM Classifier - Semantic signal

**LLM used**
Groq - `llama-3.3-70b-versatile` (Free tier)

**What it measures**
It measures semantic and stylistic coherence holistically.

**Differences between AI and Human Text for the LLM**

- Semantic coherence: AI text is consistent with very structured logical arguments, while humans tend to make more logical leaps or pivots in thought process.
- Stylistic Homogenity: AI text tends to use hedging language and stays overly polished in ways humans rarely use in casual or academic settings.
- Pragmatics: AI tends to hallucinate and state things with absolute confidence that is not possible or logically sound.

**What it misses**
While the LLM understands semantic context, it does not provide the mathematical precision to detect specific structural anomalies. It can be fooled by the framing of the text, such as by adding typos, colloquialisms, or personal anecdotes.

### Stylometric Heuristics - Structural signal

**How it was implemented**
Pure Python functions will compute this

**What it measures**
It measures statistical properties that differ between human and AI writing. Metrics include:

- Sentence length variance (Burstiness)
- Type-token ratio (Vocabulary Diversity)
- Punctuation density

**Differences between AI and Human Heuristically**

- Burstiness: Sentence length and structure tends to be much more uniform when AI generated. Human writing tends to have a mix of short, punchy sentences with long, complex ones.
- Diversity: Vocabulary richness tends to be much safer and more repetitive when AI generated compared to the unpredictability of human writing.
- Punctuation: AI-generated text tends to overuse em dash and has very uniform and perfect punctuation usage, while human writing has natural inconsistencies and intentional hesitations.

**What it misses**
Since this is strictly structural, it cannot capture nuance such as context, intent, and meaning that aids in determining the likelihood of a text being human-generated or not.

---

## Confidence Scoring with Uncertainty

### Combining Scores

For this dual signal setup I will use a dynamic weighted average to combine the scores since the length of the text affects the efficacy of each signal. Shorter text is less useful to the structural signal since there's just less "struture" to analyze so the LLM should have a stronger weight in those situations. As text becomes longer, structural patterns become more apparent, so it can take over a larger weight.

- Shorter text (< 300 words): LLM weight = 80%, Stylometry = 20%
- Medium text (> 300 words & < 750): LLM weight = 60%, Stylometry = 40%
- Longer text (> 750 words): LLM weight = 40%, Stylometry = 60%

### Combined Confidence Score Thresholds

**0-0.30**
Fairly confident that the text is not AI-generated.

**0.31-0.69**
Unsure whether the text is AI-generated or not

**0.7-1.0**
Fairly confident that the text is AI-generated.

### Example Scores

**High Confidence Score**

- Text: "The system processes information in a structured manner — the system evaluates every input carefully. The system then generates a response based on the input; the system relies on patterns it has learned. It is important to note that the system applies logic consistently — logic that the system uses across every task. The system must consider these patterns; the system cannot ignore any pattern without risking errors. The system therefore produces reliable output — output that reflects the patterns the system processed."
- Confidence Score: 0.7487
- LLM Score: 0.78
- Heuristic Score: 0.6235

Log:

```JSON
{"content_id": "63945b1d-5015-4e0f-afa0-e6eb190e7e66", "creator_id": "AI_test", "timestamp": "2026-07-01T03:53:51.750588+00:00", "attribution": "high_confidence_AI", "confidence": 0.7487, "llm_score": 0.78, "heuristic_score": 0.6235, "status": "not_appealed"}
```

**Low Confidence Score**

- Text: "ok so i finally tried that new ramen place downtown and honestly? underwhelming. the broth was fine but they put WAY too much sodium in it and i was thirsty for like three hours after. my friend got the spicy version and said it was better. probably won't go back unless someone drags me there"
- Confidence Score: 0.2721
- LLM Score: 0.23
- Heuristic Score: 0.4407

Log:

```JSON
{"content_id": "55d73461-52d0-4a5b-979c-1f01204b3927", "creator_id": "human_generated", "timestamp": "2026-07-01T03:47:28.488352+00:00", "attribution": "high_confidence_human", "confidence": 0.2721, "llm_score": 0.23, "heuristic_score": 0.4407, "status": "not_appealed"}
```

---

## Transparency Label

### 0-0.30 Label

The system returns to the user "Most likely authentic 👍🏾"
Attribution: "high_confidence_human"

### 0.31-0.69 Label

The system returns to the user "Cannot determine authenticity ❓"
Attribution: "uncertain"

### 0.7-1.0 Label

The system returns to the user "Most likely AI 🤖"
Attribution: "high_confidence_AI"

![transparency_label_varients](screenshots\Transparency_Label_Variants.png)

---

## Rate Limiting

Rate limiting is applied to all three endpoints to prevent abuse and protect the system from being overloaded.

**Limiter**
`flask-limiter` (IP-based via `get_remote_address`)

**/submit endpoint limits**
The submit endpoint will have a limit of 10 per minute up to a max of 100 per day. This is a reasonable limit for submitting content to the system from one person without spamming it since a legit creator checking their work or drafts wouldn't reasonably be checking more than 100 drafts a day.

**/appeal endpoint limits**
The appeal endpoint has two layers of protection:

1. **Application logic** (`appeal_exists()`): Enforces one appeal per content per creator by checking the audit log before allowing a new appeal. If an appeal is already in for a piece of content from a specific creator and it is under review, there is no need for the system to continuously receive more requests for appeals for the same submission.
2. **IP rate limit**: 5 appeals per minute per IP address as a general DOS protection layer against scripted flooding, if one person is trying to pose as a bunch of different creators to get some content appealed, it could overflood the system, so a max of 5 per IP is reasonable.

**/logs endpoint limits**
The logs endpoint has a limit of 30 requests per minute per IP to prevent bulk log scraping while keeping the endpoint accessible for normal use.

---

## Known Limitations

**Short text without much structure (<300 words)**

This has been a difficult case to classify accurately and consistently in my system because the heavy lifting is on the LLM without much actual text to structurally analyze. As such, the LLM will be generating the majority of the weight for the overall confidence score and even then, the shorter the text the less semantics and context the LLM has to use, so it has to make heavy assumptions as well.

**Technical text with clear cut strcture**
A lot of technical text, such as manuals or academic journals, tend to have very strict structure and neutral tone regardless of whether it is written by a human or AI, so even with a dynamic weighted average for the overall confidence score, the system struggles to label these accurately. The attribution for these tend to be uncertain leaning towards AI-generated since formal documents follow similar patterns to that of AI text.

## Spec Reflection

**One way the spec helped you during implementation:**

My spec was very thorough, so I had a very clear understanding of how data flowed through my system (from my endpoints to the responses and logging) and all the necessary requirements that I needed to implement in my system. I had fully thought out the calculations for the confidence scoring ahead of time making it straight forward to implement during the actual function generation.

**One way your implementation diverged from the spec, and why:**

Initially, I planned on including a Perplexity as a metric underneath the heuristics, but upon further research, I realized I would need more than just standard Python functions for that as it compares text against a language model's probability distribution. As such, that would not make sense to add under heuristics using pure Python and I removed that metric from the calculation.

## AI Usage

### Instance 1

**What I gave Claude:** I gave Claude my `/submit` endpoint in my API endpoints section, my llm classifier detection signal, and my submit endpoint pipeline ASCII diagram and ask it to generate a Flask app skeleton and function for the first detection signal.

**What it produced:** Claude successfully implemented the `llm_classifier` function and initial flask skeleton following my planning doc.

**What I changed or overrode:** It initially was going to default to a fallback neutral confidence score of 0.5 if the Groq API failed but I had it just return an error instead as I didn't want an arbitrary LLM score included in the overall confidence score unknowingly with no error. It also gave me a terminal function to run tests manually, but then I had it take my 4 provided examples and create a test file that I could run instead.

### Instance 2

**What I gave Claude:** I gave Claude my `/submit` endpoint in my API endpoints section, my stylometric heuristics detection signal, my uncertainty representation, and my ASCII diagram and asked it to generate the second function signal logic and overall confidence scoring logic.

**What it produced:** Claude successfully implemented the `heuristic_classifier` function and the `overall_confidence` scoring logic according to my planning doc.

**What I changed or overrode:** It gave me a terminal function to run tests manually for my examples, but I again had it take my 4 provided examples and create a test file instead for this detection signal.

### Instance 3

**What I gave Claude:** I gave Claude the transparency label design, my appeals workflow, and my appeals endpoint pipeline ASCII diagram and asked it to generate my label generation logic and the `/appeal` endpoint.

**What it produced:** Claude successfully implemented the `appeals` endpoint and adding the transparency label generation to the end of the classification pipeline.

**What I changed or overrode:** It initially was going to require a creator_id for all appeals, but I pivoted and decided to specify that creator_id is only required for uncertain or AI-generated statuses appeals since it makes most sense that the only person who could argue why a post is not AI would be the person who actually submitted it. So I added conditionals to how the appeals endpoint is done.
