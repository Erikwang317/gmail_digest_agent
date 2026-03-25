import json
import os
import subprocess
import sys

def get_emails():
    result = subprocess.run(
        [sys.executable, "gmail_reader.py"],
        capture_output=True,
        text=True
    )
    print("STDOUT:", result.stdout)
    print("STDERR:", result.stderr)

    if result.returncode != 0:
        raise RuntimeError(f"gmail_reader.py failed with exit code {result.returncode}")

    if not result.stdout.strip():
        raise RuntimeError("gmail_reader.py returned empty output")

    return json.loads(result.stdout)

def build_message(data):
    emails = data.get("emails", [])
    count = data.get("count", 0)

    if count == 0:
        return "📭 No unread emails"

    lines = [f"📬 Gmail Digest: {count} unread"]

    for e in emails[:5]:
        subject = e.get("subject", "No subject")
        sender = e.get("from", "Unknown")

        lines.append(f"• {subject}\n  ↳ {sender}")

    return "\n".join(lines)

def send_telegram(message):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    import requests

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    requests.post(url, data={
        "chat_id": chat_id,
        "text": message
    })

if __name__ == "__main__":
    data = get_emails()
    msg = build_message(data)
    send_telegram(msg)