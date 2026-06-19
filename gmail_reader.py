import os
import base64
from email.utils import parsedate_to_datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

def get_gmail_service():
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(
            "credentials.json",
            SCOPES
        )
        creds = flow.run_local_server(port=0)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)

def decode_body(payload):
    body = ""

    if "parts" in payload:
        for part in payload["parts"]:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data")
                if data:
                    body += base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    else:
        data = payload.get("body", {}).get("data")
        if data:
            body += base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")

    return body

def fetch_recent_emails(limit=20):
    service = get_gmail_service()

    results = service.users().messages().list(
        userId="me",
        maxResults=limit,
        q="newer_than:90d"
    ).execute()

    messages = results.get("messages", [])
    emails = []

    for msg in messages:
        detail = service.users().messages().get(
            userId="me",
            id=msg["id"],
            format="full"
        ).execute()

        headers = detail["payload"].get("headers", [])

        subject = ""
        sender = ""
        date = ""

        for h in headers:
            if h["name"].lower() == "subject":
                subject = h["value"]
            elif h["name"].lower() == "from":
                sender = h["value"]
            elif h["name"].lower() == "date":
                date = h["value"]

        body = decode_body(detail["payload"])

        emails.append({
            "gmail_id": msg["id"],
            "sender": sender,
            "subject": subject,
            "date": date,
            "body": body[:3000]
        })

    return emails
