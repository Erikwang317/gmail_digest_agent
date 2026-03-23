from fastapi import FastAPI
from gmail_reader import get_unread_emails
import logging

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Server is running. Use /emails"}

@app.get("/emails")
def read_emails():
    logging.info("API called: /emails")
    emails = get_unread_emails()
    return {
        "count": len(emails),
        "emails": emails
    }