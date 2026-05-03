import logging
import os
import sys
import requests
from gmail_reader import get_unread_emails, apply_digest_label, apply_skipped_label
from email_analyzer import analyze_emails

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

GMAIL_BASE_URL = "https://mail.google.com/mail/u/0/#inbox"


def build_message(analysis_results, total_fetched):
    if not analysis_results:
        return "📭 No important emails in your inbox right now."

    urgent = [r for r in analysis_results if r.get("urgency") == "urgent"]
    fyi = [r for r in analysis_results if r.get("urgency") != "urgent"]

    lines = [
        f"📬 Gmail Digest: {len(analysis_results)} important out of {total_fetched} unread",
        "",
    ]

    if urgent:
        lines.append(f"🔴 URGENT ({len(urgent)})")
        lines.append("─" * 25)
        for r in urgent:
            lines.append(f"• {r.get('summary', 'No summary')}")
            if r.get("action"):
                lines.append(f"  ⚡ Action: {r['action']}")
            link = f"{GMAIL_BASE_URL}/{r['id']}"
            lines.append(f"  🔗 {link}")
            lines.append("")

    if fyi:
        lines.append(f"🟡 FYI ({len(fyi)})")
        lines.append("─" * 25)
        for r in fyi:
            lines.append(f"• {r.get('summary', 'No summary')}")
            if r.get("action"):
                lines.append(f"  ⚡ Action: {r['action']}")
            link = f"{GMAIL_BASE_URL}/{r['id']}"
            lines.append(f"  🔗 {link}")
            lines.append("")

    return "\n".join(lines)


def send_notification(message):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        raise RuntimeError("NTFY_TOPIC not set")

    resp = requests.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={"Title": "Gmail Digest"},
        timeout=30,
    )
    if not resp.ok:
        logging.error("ntfy error %d: %s", resp.status_code, resp.text)
        raise RuntimeError(f"ntfy send failed: {resp.status_code}")

    logging.info("Notification sent via ntfy (%d chars)", len(message))


def write_credential_files():
    client_secret = os.getenv("CLIENT_SECRET")
    if client_secret:
        with open("client_secret.json", "w") as f:
            f.write(client_secret)
        logging.info("Wrote client_secret.json from environment")
    token = os.getenv("GMAIL_TOKEN")
    if token:
        with open("token.json", "w") as f:
            f.write(token)
        logging.info("Wrote token.json from environment")


def main():
    logging.info("=== Gmail Digest Agent starting ===")

    try:
        write_credential_files()
    except Exception:
        logging.exception("Failed to write credential files")
        sys.exit(1)

    try:
        service, emails = get_unread_emails(include_body=True)
    except Exception:
        logging.exception("Failed to fetch emails from Gmail")
        sys.exit(1)

    logging.info("Fetched %d unread emails", len(emails))

    if not emails:
        try:
            send_notification("📭 No unread emails in the last 24 hours.")
        except Exception:
            logging.exception("Failed to send empty-inbox notification")
        return

    try:
        analysis, skipped_ids = analyze_emails(emails)
    except Exception:
        logging.exception("Failed to analyze emails with Gemini")
        fallback = "⚠️ Gemini analysis failed. Raw unread emails:\n\n"
        for e in emails[:15]:
            fallback += f"• {e['subject']}\n  From: {e['from']}\n\n"
        try:
            send_notification(fallback)
        except Exception:
            logging.exception("Failed to send fallback notification")
        sys.exit(1)

    msg = build_message(analysis, total_fetched=len(emails))

    try:
        send_notification(msg)
    except Exception:
        logging.exception("Failed to send digest notification")
        sys.exit(1)

    important_ids = [r["id"] for r in analysis]
    all_ids = important_ids + skipped_ids
    try:
        apply_digest_label(service, all_ids)
        logging.info("Labeled %d emails as Digested", len(all_ids))
    except Exception:
        logging.exception("Failed to apply Digested label (non-fatal)")

    try:
        apply_skipped_label(service, skipped_ids)
        logging.info("Labeled %d emails as Digest-Skipped", len(skipped_ids))
    except Exception:
        logging.exception("Failed to apply Digest-Skipped label (non-fatal)")

    logging.info("=== Gmail Digest Agent finished ===")


if __name__ == "__main__":
    main()
