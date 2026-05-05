import json
import logging
import os
import time
import yaml
from google import genai
from google.genai.errors import ClientError

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def _matches_any(text, patterns):
    text_lower = text.lower()
    return any(p.lower() in text_lower for p in patterns)


def pre_filter(emails, config):
    """Split emails into skip / keep based on config rules. Returns (to_analyze, skipped)."""
    skip_senders = config.get("skip_senders", [])
    skip_keywords = config.get("skip_keywords", [])
    skip_labels = set(config.get("skip_labels", []))

    to_analyze = []
    skipped = []

    for email in emails:
        sender = email.get("from", "")
        subject = email.get("subject", "")
        snippet = email.get("snippet", "")
        labels = set(email.get("labels", []))
        combined_text = f"{subject} {snippet}"

        if labels & skip_labels:
            skipped.append(email)
        elif _matches_any(sender, skip_senders):
            skipped.append(email)
        elif _matches_any(combined_text, skip_keywords):
            skipped.append(email)
        else:
            to_analyze.append(email)

    logging.info("Pre-filter: %d to analyze, %d skipped", len(to_analyze), len(skipped))
    return to_analyze, skipped


def hard_flag_urgent(emails, config):
    """Mark emails as urgent if they match config rules. Returns set of urgent email IDs."""
    urgent_senders = config.get("urgent_senders", [])
    urgent_keywords = config.get("urgent_keywords", [])
    urgent_ids = set()

    for email in emails:
        sender = email.get("from", "")
        subject = email.get("subject", "")
        snippet = email.get("snippet", "")
        combined_text = f"{subject} {snippet}"

        if _matches_any(sender, urgent_senders) or _matches_any(combined_text, urgent_keywords):
            urgent_ids.add(email["id"])

    logging.info("Hard-flagged %d emails as urgent", len(urgent_ids))
    return urgent_ids


BATCH_SIZE = 5
BATCH_DELAY_SECONDS = 30
MAX_CHARS_PER_EMAIL = 500


def _build_prompt(email_entries):
    return f"""You are an email triage assistant. Analyze each email and return a JSON array.

For each email, determine:
1. **urgency**: "urgent" (payments due, government, interviews, deadlines, account issues) or "fyi" (informational, can wait)
2. **summary**: One sentence summarizing what the email is about and why it matters.
3. **action**: A short action item if applicable (e.g., "Pay by May 15", "Reply by Friday"), or null if no action needed.
4. **important**: true if the user should definitely see this, false if borderline.

Rules:
- Any email marked "hard_urgent": true MUST be classified as "urgent" and "important": true.
- Newsletters, automated notifications, social media alerts, marketing, welcome emails, and job alerts should be "important": false.
- Payment confirmations (already paid, no action needed) should be "important": false.
- Only mark "important": true if the email requires a response, has a deadline, or contains critical information the user would regret missing.
- When in doubt, lean toward excluding it (important: false).

Return ONLY a valid JSON array, no markdown fences, no explanation. Each object must have: id, urgency, summary, action, important.

Emails to analyze:
{json.dumps(email_entries, ensure_ascii=False)}"""


def _call_gemini(client, prompt):
    for attempt in range(3):
        try:
            response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            break
        except ClientError as e:
            if e.code == 429 and attempt < 2:
                wait = 60 * (attempt + 1)
                logging.warning("Rate limited, retrying in %ds (attempt %d/3)", wait, attempt + 1)
                time.sleep(wait)
            else:
                raise

    raw = response.text.strip()

    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

    try:
        results = json.loads(raw)
    except json.JSONDecodeError:
        logging.error("Failed to parse Gemini response: %s", raw[:500])
        raise RuntimeError("Gemini returned invalid JSON")

    return results


def analyze_with_gemini(emails, hard_urgent_ids):
    """Use Gemini Flash to classify importance and summarize each email."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set")

    client = genai.Client(api_key=api_key)

    email_entries = []
    for e in emails:
        combined_text = f"{e['subject']} {e['snippet']} {e.get('body', '') or ''}"
        if len(combined_text) > MAX_CHARS_PER_EMAIL:
            combined_text = combined_text[:MAX_CHARS_PER_EMAIL]

        entry = {
            "id": e["id"],
            "from": e["from"],
            "text": combined_text,
            "hard_urgent": e["id"] in hard_urgent_ids,
        }
        email_entries.append(entry)

    all_results = []
    batches = [email_entries[i:i + BATCH_SIZE] for i in range(0, len(email_entries), BATCH_SIZE)]
    logging.info("Sending %d emails to Gemini in %d batches of %d", len(email_entries), len(batches), BATCH_SIZE)

    for batch_idx, batch in enumerate(batches):
        if batch_idx > 0:
            logging.info("Waiting %ds before next batch...", BATCH_DELAY_SECONDS)
            time.sleep(BATCH_DELAY_SECONDS)

        prompt = _build_prompt(batch)
        logging.info("Sending batch %d/%d (%d emails)", batch_idx + 1, len(batches), len(batch))
        results = _call_gemini(client, prompt)
        all_results.extend(results)

    logging.info("Gemini analysis complete: %d results", len(all_results))
    return all_results


def analyze_emails(emails):
    """Full pipeline: config pre-filter → hard-flag urgent → Gemini analysis.

    Returns (important_results, skipped_ids) where skipped_ids includes
    both config-skipped and Gemini-marked-not-important email IDs.
    """
    config = load_config()
    to_analyze, skipped = pre_filter(emails, config)

    skipped_ids = [e["id"] for e in skipped]

    if not to_analyze:
        logging.info("No emails to analyze after filtering")
        return [], skipped_ids

    hard_urgent_ids = hard_flag_urgent(to_analyze, config)
    results = analyze_with_gemini(to_analyze, hard_urgent_ids)

    important_results = [r for r in results if r.get("important", True)]
    not_important = [r for r in results if not r.get("important", True)]
    skipped_ids.extend(r["id"] for r in not_important)

    logging.info(
        "Final: %d important, %d skipped (%d config + %d Gemini)",
        len(important_results), len(skipped_ids), len(skipped), len(not_important),
    )
    return important_results, skipped_ids
