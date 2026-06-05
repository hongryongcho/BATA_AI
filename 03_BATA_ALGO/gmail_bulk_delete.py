"""
Gmail 대량 영구 삭제 스크립트
사용: python3 gmail_bulk_delete.py --before 2025/12/05
"""
import argparse
import pickle
import time
from pathlib import Path
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

TOKEN_PATH = (Path(__file__).parent / "../02_BATA_MQTT/config/gmail_token.json").resolve()

def get_service():
    with open(TOKEN_PATH, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds)

def bulk_delete(before_date: str, dry_run: bool = False):
    svc = get_service()
    query = f"before:{before_date}"
    print(f"조건: {query}")
    print(f"모드: {'미리보기(실제삭제 안함)' if dry_run else '영구 삭제'}")
    print("-" * 50)

    total = 0
    page_token = None
    batch_size = 1000  # Gmail 배치 최대 1000개

    while True:
        kwargs = {"userId": "me", "q": query, "maxResults": batch_size}
        if page_token:
            kwargs["pageToken"] = page_token

        res = svc.users().messages().list(**kwargs).execute()
        messages = res.get("messages", [])
        if not messages:
            break

        ids = [m["id"] for m in messages]
        print(f"  {total + 1} ~ {total + len(ids)}건 처리 중...")

        if not dry_run:
            svc.users().messages().batchDelete(
                userId="me",
                body={"ids": ids}
            ).execute()
            time.sleep(0.3)  # API 속도 제한 방지

        total += len(ids)
        page_token = res.get("nextPageToken")
        if not page_token:
            break

    print("-" * 50)
    action = "삭제 예정" if dry_run else "영구 삭제 완료"
    print(f"총 {total:,}건 {action}")
    return total

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", required=True, help="삭제 기준 날짜 (예: 2025/12/05)")
    parser.add_argument("--dry-run", action="store_true", help="실제 삭제 없이 건수만 확인")
    args = parser.parse_args()
    bulk_delete(args.before, dry_run=args.dry_run)
