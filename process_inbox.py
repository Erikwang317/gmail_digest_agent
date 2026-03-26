import json
import os
import subprocess
import sys
import requests
from dotenv import load_dotenv

# Ensure that environment variables are loaded
load_dotenv()

# Retrieve Telegram Bot Token and Chat ID from environment variables
telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

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

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError("Failed to parse JSON from the output of gmail_reader.py")

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

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    requests.post(url, data={
        "chat_id": chat_id,
        "text": message
    })

if __name__ == "__main__":
    # Write service account JSON from GitHub secret to a file
    with open("service_account.json", "w") as f:
        f.write(os.getenv("DIGEST_GMAIL_ACCOUNT_KEY"))

    data = get_emails()
    msg = build_message(data)
    send_telegram(msg)