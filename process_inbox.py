import logging
import os
import sys
import requests
from gmail_reader import get_unread_emails, apply_digest_label
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


def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Telegram has a 4096-char limit per message
    chunks = [message[i:i + 4000] for i in range(0, len(message), 4000)]

    for chunk in chunks:
        resp = requests.post(url, data={"chat_id": chat_id, "text": chunk}, timeout=30)
        if not resp.ok:
            logging.error("Telegram API error %d: %s", resp.status_code, resp.text)
            raise RuntimeError(f"Telegram send failed: {resp.status_code}")

    logging.info("Telegram message sent (%d chars, %d chunks)", len(message), len(chunks))


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
            send_telegram("📭 No unread emails in the last 24 hours.")
        except Exception:
            logging.exception("Failed to send empty-inbox Telegram message")
        return

    try:
        analysis = analyze_emails(emails)
    except Exception:
        logging.exception("Failed to analyze emails with Gemini")
        # Fallback: send raw subject list so user isn't left with nothing
        fallback = "⚠️ Gemini analysis failed. Raw unread emails:\n\n"
        for e in emails[:15]:
            fallback += f"• {e['subject']}\n  From: {e['from']}\n\n"
        try:
            send_telegram(fallback)
        except Exception:
            logging.exception("Failed to send fallback Telegram message")
        sys.exit(1)

    msg = build_message(analysis, total_fetched=len(emails))

    try:
        send_telegram(msg)
    except Exception:
        logging.exception("Failed to send digest via Telegram")
        sys.exit(1)

    # Label processed emails so they don't appear in the next run
    processed_ids = [r["id"] for r in analysis]
    try:
        apply_digest_label(service, processed_ids)
        logging.info("Labeled %d emails as Digested", len(processed_ids))
    except Exception:
        logging.exception("Failed to apply Digested label (non-fatal)")

    logging.info("=== Gmail Digest Agent finished ===")


if __name__ == "__main__":
    main()
