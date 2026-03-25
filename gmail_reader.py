import os
import logging
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)


def get_service():
    logging.info("Starting Gmail authentication flow")
    creds = None

    if os.path.exists("token.json"):
        logging.info("Found existing token.json, loading saved credentials")
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    else:
        logging.info("No token.json found")

    if not creds or not creds.valid:
        logging.info("Credentials missing or invalid, starting OAuth login")
        flow = InstalledAppFlow.from_client_secrets_file(
            "client_secret.json",
            SCOPES
        )
        creds = flow.run_local_server(port=0)

        logging.info("OAuth completed, saving token.json")
        with open("token.json", "w") as token:
            token.write(creds.to_json())
    else:
        logging.info("Using existing valid credentials")

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