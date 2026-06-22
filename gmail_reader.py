import base64
from email.utils import parsedate_to_datetime
from gmail_oauth_web import get_gmail_service_web

def get_gmail_service(user_id=None, company_id=None):
    if user_id is None or company_id is None:
        raise ValueError("user_id / company_id がないためGmailサービスを取得できません。")
    return get_gmail_service_web(user_id=user_id, company_id=company_id)

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

def fetch_recent_emails(limit=20, user_id=None, company_id=None):
    try:
        from gmail_oauth_web import load_credentials
        from googleapiclient.discovery import build

        creds = load_credentials(user_id=user_id, company_id=company_id)
        if creds:
            service = build("gmail", "v1", credentials=creds)
        else:
            service = get_gmail_service(user_id=user_id, company_id=company_id)
    except Exception:
        service = get_gmail_service(user_id=user_id, company_id=company_id)

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
