import os
import base64
import logging
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]

CLIENT_SECRET_FILE = os.getenv("CLIENT_SECRET_FILE", "client_secret.json")
TOKEN_FILE = os.getenv("TOKEN_FILE", "token.json")
DIGEST_LABEL = "Digested"


def get_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("gmail", "v1", credentials=creds)


def extract_header(headers, header_name):
    return next(
        (h["value"] for h in headers if h["name"].lower() == header_name.lower()),
        "",
    )


def _get_body_text(payload):
    """Extract plain-text body from a Gmail message payload."""
    mime = payload.get("mimeType", "")

    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        text = _get_body_text(part)
        if text:
            return text

    return ""


def _ensure_label(service, label_name):
    """Get or create a Gmail label, return its ID."""
    results = service.users().labels().list(userId="me").execute()
    for label in results.get("labels", []):
        if label["name"] == label_name:
            return label["id"]

    created = service.users().labels().create(
        userId="me",
        body={"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
    ).execute()
    logging.info("Created Gmail label: %s", label_name)
    return created["id"]


def apply_digest_label(service, message_ids):
    """Apply the Digested label to a list of message IDs."""
    if not message_ids:
        return
    label_id = _ensure_label(service, DIGEST_LABEL)
    for msg_id in message_ids:
        try:
            service.users().messages().modify(
                userId="me",
                id=msg_id,
                body={"addLabelIds": [label_id]},
            ).execute()
        except HttpError:
            logging.exception("Failed to label message %s", msg_id)


def get_unread_emails(include_body=False):
    """Fetch all unread, un-digested emails from the last 24h (excluding promotions)."""
    try:
        service = get_service()
        query = "is:unread newer_than:1d -category:promotions -label:Digested"
        logging.info("Searching Gmail with query: %s", query)

        all_messages = []
        page_token = None

        while True:
            results = service.users().messages().list(
                userId="me", q=query, maxResults=100, pageToken=page_token
            ).execute()
            all_messages.extend(results.get("messages", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                break

        logging.info("Found %d matching messages", len(all_messages))
        emails = []

        for idx, msg in enumerate(all_messages, start=1):
            msg_id = msg["id"]
            fmt = "full" if include_body else "metadata"
            msg_data = service.users().messages().get(
                userId="me", id=msg_id, format=fmt
            ).execute()

            payload = msg_data.get("payload", {})
            headers = payload.get("headers", [])

            body_text = ""
            if include_body:
                body_text = _get_body_text(payload)
                if len(body_text) > 3000:
                    body_text = body_text[:3000]

            email_item = {
                "id": msg_data.get("id", ""),
                "thread_id": msg_data.get("threadId", ""),
                "from": extract_header(headers, "From"),
                "subject": extract_header(headers, "Subject"),
                "date": extract_header(headers, "Date"),
                "snippet": msg_data.get("snippet", ""),
                "labels": msg_data.get("labelIds", []),
                "body": body_text,
            }
            emails.append(email_item)

            logging.info(
                "Fetched %d/%d: %s", idx, len(all_messages), email_item["subject"]
            )

        logging.info("Finished fetching %d emails", len(emails))
        return service, emails

    except HttpError:
        logging.exception("Gmail API request failed")
        raise
    except Exception:
        logging.exception("Unexpected error while reading emails")
        raise


if __name__ == "__main__":
    import json
    _, emails = get_unread_emails()
    print(json.dumps({"count": len(emails), "emails": emails}, ensure_ascii=False))
