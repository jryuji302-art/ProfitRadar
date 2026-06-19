import base64
from email.utils import parsedate_to_datetime
from gmail_oauth_web import get_gmail_service_web

def get_gmail_service():
    return get_gmail_service_web(user_id=1, company_id=1)

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
            name = h.get("name", "").lower()
            if name == "subject":
                subject = h.get("value", "")
            elif name == "from":
                sender = h.get("value", "")
            elif name == "date":
                date = h.get("value", "")

        body = decode_body(detail["payload"])

        emails.append({
            "gmail_id": msg["id"],
            "sender": sender,
            "subject": subject,
            "date": date,
            "body": body[:3000]
        })

    return emails
