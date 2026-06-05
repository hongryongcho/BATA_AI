"""
Gmail API 서비스 래퍼
━━━━━━━━━━━━━━━━━━━━
- 읽지 않은 메일 조회
- 메일 읽음 처리
- 회신 발송
- 라벨 적용
"""
from __future__ import annotations

import base64
import pickle
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

from googleapiclient.discovery import build
from google.auth.transport.requests import Request

BASE       = Path(__file__).parent
TOKEN_PATH = (BASE / "../02_BATA_MQTT/config/gmail_token.json").resolve()

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]


def _get_service():
    with open(TOKEN_PATH, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)
    return build("gmail", "v1", credentials=creds)


def get_unread_emails(max_results: int = 10) -> list[dict]:
    """읽지 않은 메일 목록 반환"""
    svc = _get_service()
    res = svc.users().messages().list(
        userId="me",
        q="is:unread in:inbox",
        maxResults=max_results,
    ).execute()

    messages = res.get("messages", [])
    emails = []
    for m in messages:
        detail = svc.users().messages().get(
            userId="me", id=m["id"], format="full"
        ).execute()
        emails.append(_parse_email(detail))
    return emails


def _parse_email(msg: dict) -> dict:
    headers = {h["name"]: h["value"] for h in msg["payload"].get("headers", [])}
    body = _extract_body(msg["payload"])
    return {
        "id":        msg["id"],
        "thread_id": msg["threadId"],
        "subject":   headers.get("Subject", "(제목 없음)"),
        "from":      headers.get("From", ""),
        "to":        headers.get("To", ""),
        "date":      headers.get("Date", ""),
        "snippet":   msg.get("snippet", ""),
        "body":      body,
    }


def _extract_body(payload: dict) -> str:
    """멀티파트/단일파트 모두 처리해 텍스트 추출"""
    if payload.get("mimeType", "").startswith("text/plain"):
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")

    if payload.get("mimeType", "").startswith("text/html"):
        data = payload.get("body", {}).get("data", "")
        if data:
            html = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
            return re.sub(r"<[^>]+>", " ", html).strip()

    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text
    return ""


def mark_as_read(email_id: str):
    """메일 읽음 처리"""
    svc = _get_service()
    svc.users().messages().modify(
        userId="me",
        id=email_id,
        body={"removeLabelIds": ["UNREAD"]},
    ).execute()


def apply_label(email_id: str, label_name: str):
    """라벨 적용 (없으면 생성)"""
    svc = _get_service()
    labels = svc.users().labels().list(userId="me").execute().get("labels", [])
    label_id = next((l["id"] for l in labels if l["name"] == label_name), None)
    if label_id is None:
        new_label = svc.users().labels().create(
            userId="me", body={"name": label_name}
        ).execute()
        label_id = new_label["id"]
    svc.users().messages().modify(
        userId="me", id=email_id,
        body={"addLabelIds": [label_id]},
    ).execute()


def send_reply(email: dict, body_text: str) -> dict:
    """해당 메일에 회신 발송"""
    svc = _get_service()

    to_addr = email["from"]
    subject = email["subject"]
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject

    msg = MIMEMultipart()
    msg["To"]         = to_addr
    msg["Subject"]    = subject
    msg["In-Reply-To"] = email["id"]
    msg["References"]  = email["id"]
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    result = svc.users().messages().send(
        userId="me",
        body={"raw": raw, "threadId": email["thread_id"]},
    ).execute()
    return result


def archive_email(email_id: str):
    """메일 보관 (받은편지함에서 제거)"""
    svc = _get_service()
    svc.users().messages().modify(
        userId="me",
        id=email_id,
        body={"removeLabelIds": ["INBOX", "UNREAD"]},
    ).execute()


def trash_email(email_id: str):
    """메일 휴지통 이동 (30일 후 자동 삭제)"""
    svc = _get_service()
    svc.users().messages().trash(userId="me", id=email_id).execute()


def delete_email_permanently(email_id: str):
    """메일 영구 삭제 (복구 불가)"""
    svc = _get_service()
    svc.users().messages().delete(userId="me", id=email_id).execute()


def get_sender_email(from_header: str) -> str:
    """From 헤더에서 이메일 주소만 추출 ('이름 <email>' → 'email')"""
    m = re.search(r"<([^>]+)>", from_header)
    if m:
        return m.group(1).lower().strip()
    return from_header.lower().strip()


def get_my_email() -> str:
    """내 Gmail 주소 반환"""
    svc = _get_service()
    profile = svc.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "")
