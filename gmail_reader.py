import os
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
SERVICE_ACCOUNT_FILE = 'digest_gmail_account_key.json'  # Ensure this path matches the GitHub Actions secret location

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

def get_service():
    logging.info("Starting Gmail authentication flow")
    creds = None

    # Authenticate using the service account key file
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    logging.info("Using service account for authentication")

    logging.info("Building Gmail API service client")
    service = build("gmail", "v1", credentials=creds)
    logging.info("Gmail API service client created successfully")
    return service

def extract_header(headers, header_name):
    return next(
        (h["value"] for h in headers if h["name"].lower() == header_name.lower()),
        ""
    )

def get_unread_emails():
    try:
        service = get_service()

        query = "is:unread newer_than:1d -category:promotions"
        logging.info("Searching Gmail with query: %s", query)

        results = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=5
        ).execute()

        messages = results.get("messages", [])
        logging.info("Found %d matching messages", len(messages))

        emails = []

        for idx, msg in enumerate(messages, start=1):
            msg_id = msg["id"]
            logging.info("Fetching message %d/%d, id=%s", idx, len(messages), msg_id)

            msg_data = service.users().messages().get(
                userId="me",
                id=msg_id,
                format="full"
            ).execute()

            payload = msg_data.get("payload", {})
            headers = payload.get("headers", [])

            sender = extract_header(headers, "From")
            subject = extract_header(headers, "Subject")
            date = extract_header(headers, "Date")

            email_item = {
                "id": msg_data.get("id", ""),
                "thread_id": msg_data.get("threadId", ""),
                "from": sender,
                "subject": subject,
                "date": date,
                "snippet": msg_data.get("snippet", ""),
                "labels": msg_data.get("labelIds", [])
            }

            emails.append(email_item)

            logging.info(
                "Extracted email: from=%s | subject=%s | labels=%s",
                sender,
                subject,
                email_item["labels"]
            )

        logging.info("Finished fetching emails successfully")
        return emails

    except HttpError:
        logging.exception("Gmail API request failed")
        raise
    except Exception:
        logging.exception("Unexpected error while reading emails")
        raise

if __name__ == "__main__":
    import json
    emails = get_unread_emails()
    print(json.dumps({
        "count": len(emails),
        "emails": emails
    }, ensure_ascii=False))