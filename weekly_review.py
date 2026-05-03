import logging
import os
import sys
import requests
from gmail_reader import get_service, get_skipped_emails, clear_skipped_label

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


def send_notification(message):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        raise RuntimeError("NTFY_TOPIC not set")

    resp = requests.post(
        f"https://ntfy.sh/{topic}",
        data=message.encode("utf-8"),
        headers={"Title": "Weekly Digest Review"},
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"ntfy send failed: {resp.status_code}")


def write_credential_files():
    client_secret = os.getenv("CLIENT_SECRET")
    if client_secret:
        with open("client_secret.json", "w") as f:
            f.write(client_secret)
    token = os.getenv("GMAIL_TOKEN")
    if token:
        with open("token.json", "w") as f:
            f.write(token)


def main():
    logging.info("=== Weekly Digest Review starting ===")

    try:
        write_credential_files()
    except Exception:
        logging.exception("Failed to write credential files")
        sys.exit(1)

    try:
        service = get_service()
        skipped = get_skipped_emails(service)
    except Exception:
        logging.exception("Failed to fetch skipped emails")
        sys.exit(1)

    logging.info("Found %d skipped emails this week", len(skipped))

    if not skipped:
        send_notification("📋 Weekly Review: nothing was filtered out this week.")
        return

    lines = [
        f"📋 Weekly Review: {len(skipped)} emails were filtered out",
        "If any look important, check your inbox and adjust config.yaml.",
        "",
    ]
    for e in skipped:
        lines.append(f"• {e['subject']}")
        lines.append(f"  From: {e['from']}")
        lines.append("")

    try:
        send_notification("\n".join(lines))
    except Exception:
        logging.exception("Failed to send weekly review")
        sys.exit(1)

    try:
        clear_skipped_label(service, [e["id"] for e in skipped])
        logging.info("Cleared Digest-Skipped label from %d emails", len(skipped))
    except Exception:
        logging.exception("Failed to clear skipped labels (non-fatal)")

    logging.info("=== Weekly Digest Review finished ===")


if __name__ == "__main__":
    main()
