import uuid
from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from classifiers import (
    llm_classifier,
    heuristic_classifier,
    overall_confidence,
    generate_transparency_label,
)
from logger import log_submission, log_appeal, get_submission, appeal_exists, read_recent_logs

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

_CREATOR_REQUIRED_ATTRIBUTIONS = {"uncertain", "high_confidence_AI"}


@app.route("/")
def home():
    return "Provenance Guard is running."


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    data = request.get_json()

    if not data or not data.get("text") or not data.get("creator_id"):
        return jsonify({"error": "Missing required fields: text and creator_id"}), 400

    text = data.get("text")
    creator_id = data.get("creator_id")
    content_id = str(uuid.uuid4())

    try:
        llm_result = llm_classifier(text)
    except Exception as e:
        return jsonify({"error": f"LLM classifier failed: {str(e)}"}), 502

    heuristic_result = heuristic_classifier(text)

    confidence = overall_confidence(
        text,
        llm_score=llm_result["confidence_score"],
        heuristic_score=heuristic_result["confidence_score"],
    )
    label_result = generate_transparency_label(confidence)

    log_submission(
        content_id=content_id,
        creator_id=creator_id,
        attribution=label_result["attribution"],
        confidence=confidence,
        llm_score=llm_result["confidence_score"],
        heuristic_score=heuristic_result["confidence_score"],
    )

    return jsonify({
        "content_id": content_id,
        "attribution": label_result["attribution"],
        "confidence": confidence,
        "label": label_result["label"],
    })


@app.route("/appeal", methods=["POST"])
@limiter.limit("5 per minute")
def appeal():
    data = request.get_json()

    content_id = data.get("content_id") if data else None
    reasoning = data.get("reasoning") if data else None

    if not content_id or not reasoning:
        return jsonify({"error": "Missing required fields: content_id and reasoning"}), 400

    submission = get_submission(content_id)
    if submission is None:
        return jsonify({"error": "Content not found: no submission exists for this content_id"}), 404

    attribution = submission["attribution"]
    creator_id = data.get("creator_id")

    if attribution in _CREATOR_REQUIRED_ATTRIBUTIONS:
        if not creator_id:
            return jsonify({"error": "Missing required field: creator_id is required to appeal AI or uncertain content"}), 400
        if creator_id != submission["creator_id"]:
            return jsonify({"error": "Unauthorized: creator_id does not match the original submitter for this content"}), 401
    else:
        creator_id = creator_id or "anonymous"

    if appeal_exists(content_id, creator_id):
        return jsonify({"error": "Appeal already submitted: an appeal for this content from this creator is already under review"}), 409

    log_appeal(
        content_id=content_id,
        creator_id=creator_id,
        attribution=attribution,
        confidence=submission["confidence"],
        llm_score=submission["llm_score"],
        heuristic_score=submission["heuristic_score"],
        reasoning=reasoning,
    )

    return jsonify({
        "content_id": content_id,
        "status": "under_review",
        "message": "Your appeal has been received and is now under review.",
    })


@app.route("/logs", methods=["GET"])
@limiter.limit("30 per minute")
def logs():
    return jsonify(read_recent_logs())


if __name__ == "__main__":
    app.run(port=5000, debug=True)
