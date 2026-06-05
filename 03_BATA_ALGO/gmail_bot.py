"""
Gmail 텔레그램 봇 데몬
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
기능:
  1. Gmail 수신 감지 → 텔레그램으로 요약 알림
  2. "회신 초안" 메시지 → Claude로 답장 초안 작성
  3. "전송해줘" → Gmail API로 실제 발송
  4. "무시" / "보관" → 읽음 처리 및 보관

실행: python3 gmail_bot.py --daemon
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
SCRIPT_DIR = Path(__file__).parent

# ── 환경 설정 ─────────────────────────────────────────────────

def _load_env() -> dict:
    env_path = SCRIPT_DIR / ".env"
    data = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, _, v = s.partition("=")
                data[k.strip()] = v.strip()
    return data

ENV = _load_env()
TG_TOKEN   = ENV.get("TELEGRAM_PERSONAL_BOT_TOKEN", "")
TG_CHAT_ID = ENV.get("TELEGRAM_PERSONAL_CHAT_ID", "")
ANTHROPIC_API_KEY = ENV.get("ANTHROPIC_API_KEY", "")

# 상태 파일 (처리 대기 중인 메일 추적)
STATE_FILE     = SCRIPT_DIR / "gmail_state.json"
BLOCKLIST_FILE = SCRIPT_DIR / "gmail_blocklist.json"
LOG_FILE       = SCRIPT_DIR / "logs" / "gmail_bot.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

CHECK_INTERVAL = 300  # 5분마다 새 메일 확인

# ── 로깅 ─────────────────────────────────────────────────────

def _log(msg: str):
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# ── 상태 관리 ─────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "pending":      {},   # email_id → email dict
        "drafts":       {},   # email_id → draft text
        "last_msg_id":  0,    # 마지막 처리한 텔레그램 message_id
        "notified":     [],   # 이미 알림 보낸 email_id 목록
    }

def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


# ── 차단 목록 ─────────────────────────────────────────────────

def _load_blocklist() -> dict:
    if BLOCKLIST_FILE.exists():
        try:
            return json.loads(BLOCKLIST_FILE.read_text())
        except Exception:
            pass
    return {"senders": [], "domains": [], "keywords": []}


def _save_blocklist(bl: dict):
    BLOCKLIST_FILE.write_text(json.dumps(bl, ensure_ascii=False, indent=2))


def _is_blocked(email: dict) -> tuple[bool, str]:
    """차단 목록에 해당하는지 확인. (차단여부, 이유) 반환"""
    from gmail_service import get_sender_email
    bl = _load_blocklist()
    sender_raw = email.get("from", "")
    sender     = get_sender_email(sender_raw)
    subject    = email.get("subject", "").lower()

    # 발신자 이메일 주소 완전 일치
    for s in bl.get("senders", []):
        if s.lower() in sender:
            return True, f"차단 발신자: {s}"

    # 도메인 일치
    for d in bl.get("domains", []):
        if sender.endswith(d.lower()):
            return True, f"차단 도메인: {d}"

    # 제목 키워드
    for kw in bl.get("keywords", []):
        if kw.lower() in subject:
            return True, f"차단 키워드: {kw}"

    return False, ""

# ── 텔레그램 ─────────────────────────────────────────────────

def _tg_send(text: str, parse_mode: str = "HTML") -> dict:
    if not TG_TOKEN or not TG_CHAT_ID:
        _log("⚠️ 텔레그램 설정 없음")
        return {}
    url  = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    data = json.dumps({
        "chat_id":    TG_CHAT_ID,
        "text":       text,
        "parse_mode": parse_mode,
    }).encode()
    try:
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        _log(f"텔레그램 전송 실패: {e}")
        return {}


def _tg_get_updates(offset: int = 0) -> list[dict]:
    if not TG_TOKEN:
        return []
    url = (f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates"
           f"?offset={offset}&timeout=10")
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read())
            return data.get("result", [])
    except Exception:
        return []

# ── Claude API ────────────────────────────────────────────────

def _claude(prompt: str, system: str = "") -> str:
    if not ANTHROPIC_API_KEY:
        return "❌ ANTHROPIC_API_KEY 미설정"
    url  = "https://api.anthropic.com/v1/messages"
    body = json.dumps({
        "model":      "claude-sonnet-4-6",
        "max_tokens": 1024,
        "system":     system or "You are a helpful email assistant. Reply in Korean.",
        "messages":   [{"role": "user", "content": prompt}],
    }).encode()
    headers = {
        "Content-Type":      "application/json",
        "x-api-key":         ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    try:
        req = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
            return resp["content"][0]["text"]
    except Exception as e:
        return f"Claude API 오류: {e}"


def summarize_email(email: dict) -> str:
    body_preview = email["body"][:2000] if email["body"] else email["snippet"]
    prompt = f"""다음 이메일을 3줄 이내로 한국어로 요약해줘.
발신자: {email['from']}
제목: {email['subject']}
내용: {body_preview}

요약:"""
    return _claude(prompt, system="이메일을 간결하게 3줄 이내로 한국어 요약. 핵심 내용과 요청사항만.")


def generate_draft(email: dict, instruction: str = "") -> str:
    body_preview = email["body"][:2000] if email["body"] else email["snippet"]
    extra = f"\n추가 지시사항: {instruction}" if instruction else ""
    prompt = f"""다음 이메일에 대한 한국어 회신 초안을 작성해줘.
발신자: {email['from']}
제목: {email['subject']}
원문 내용: {body_preview}{extra}

회신 초안 (인사말 포함, 자연스러운 한국어):"""
    return _claude(
        prompt,
        system="전문적이고 친절한 한국어 이메일 회신 초안 작성. 실제 바로 사용할 수 있게."
    )

# ── 메일 알림 ─────────────────────────────────────────────────

def notify_new_email(email: dict, summary: str, state: dict):
    from_short = email["from"].split("<")[0].strip() or email["from"]
    msg = (
        f"📧 <b>새 메일 도착</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>발신:</b> {from_short}\n"
        f"📌 <b>제목:</b> {email['subject']}\n"
        f"📅 <b>날짜:</b> {email['date'][:25]}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 <b>요약:</b>\n{summary}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 <b>명령어:</b>\n"
        f"  • <code>회신 초안</code> — 답장 초안 작성\n"
        f"  • <code>삭제</code> — 휴지통으로 이동\n"
        f"  • <code>이 발신자 차단</code> — 차단+삭제\n"
        f"  • <code>무시</code> — 읽음 처리\n"
        f"  • <code>보관</code> — 받은편지함에서 제거\n"
        f"  • <code>라벨 [이름]</code> — 라벨 적용"
    )
    _tg_send(msg)
    state["pending"][email["id"]] = email
    state["notified"].append(email["id"])
    _save_state(state)
    _log(f"알림 전송: {email['subject'][:50]}")


# ── 텔레그램 명령어 처리 ──────────────────────────────────────

def handle_commands(state: dict):
    updates = _tg_get_updates(offset=state["last_msg_id"] + 1)
    if not updates:
        return

    for upd in updates:
        state["last_msg_id"] = upd["update_id"]
        msg = upd.get("message", {})
        text = msg.get("text", "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))

        if not text or chat_id != TG_CHAT_ID:
            _save_state(state)
            continue

        _log(f"명령 수신: {text[:60]}")

        # 처리 대기 중인 메일 없으면 Gmail 관련 명령 무시
        pending = state.get("pending", {})
        last_email_id = list(pending.keys())[-1] if pending else None

        text_lower = text.lower().strip()

        # ── 회신 초안 ─────────────────────────────────────────
        if any(kw in text_lower for kw in ["회신 초안", "초안", "draft", "답장 써줘", "회신"]):
            if not last_email_id:
                _tg_send("📭 처리 대기 중인 메일이 없습니다.")
            else:
                email = pending[last_email_id]
                extra_instruction = text if len(text) > 10 else ""
                _tg_send("✍️ 초안 작성 중...")
                draft = generate_draft(email, extra_instruction)
                state["drafts"][last_email_id] = draft
                _save_state(state)
                _tg_send(
                    f"📋 <b>회신 초안</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"{draft}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"💬 <code>전송해줘</code> — 이대로 발송\n"
                    f"💬 <code>수정: [내용]</code> — 내용 수정 후 재작성\n"
                    f"💬 <code>취소</code> — 취소"
                )

        # ── 전송 ──────────────────────────────────────────────
        elif any(kw in text_lower for kw in ["전송", "보내줘", "send", "발송"]):
            if not last_email_id or last_email_id not in state.get("drafts", {}):
                _tg_send("📭 전송할 초안이 없습니다. 먼저 '회신 초안'을 요청하세요.")
            else:
                draft = state["drafts"][last_email_id]
                email = pending[last_email_id]
                try:
                    from gmail_service import send_reply, mark_as_read
                    send_reply(email, draft)
                    mark_as_read(last_email_id)
                    del state["pending"][last_email_id]
                    del state["drafts"][last_email_id]
                    _save_state(state)
                    _tg_send(f"✅ <b>발송 완료!</b>\n받는 사람: {email['from']}\n제목: Re: {email['subject']}")
                    _log(f"메일 발송 완료: {email['subject'][:50]}")
                except Exception as e:
                    _tg_send(f"❌ 발송 실패: {e}")

        # ── 수정 ──────────────────────────────────────────────
        elif text_lower.startswith("수정:") or text_lower.startswith("수정 "):
            if not last_email_id:
                _tg_send("📭 처리 대기 중인 메일이 없습니다.")
            else:
                instruction = text[3:].strip()
                email = pending[last_email_id]
                _tg_send("✍️ 수정 중...")
                draft = generate_draft(email, instruction)
                state["drafts"][last_email_id] = draft
                _save_state(state)
                _tg_send(
                    f"📋 <b>수정된 초안</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"{draft}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"💬 <code>전송해줘</code> 또는 <code>수정: [내용]</code>"
                )

        # ── 무시 ──────────────────────────────────────────────
        elif any(kw in text_lower for kw in ["무시", "skip", "읽음"]):
            if last_email_id:
                try:
                    from gmail_service import mark_as_read
                    mark_as_read(last_email_id)
                    email = pending.pop(last_email_id, {})
                    state["drafts"].pop(last_email_id, None)
                    _save_state(state)
                    _tg_send(f"✅ 읽음 처리: {email.get('subject', '')[:50]}")
                except Exception as e:
                    _tg_send(f"❌ 오류: {e}")

        # ── 보관 ──────────────────────────────────────────────
        elif any(kw in text_lower for kw in ["보관", "archive"]):
            if last_email_id:
                try:
                    from gmail_service import archive_email
                    archive_email(last_email_id)
                    email = pending.pop(last_email_id, {})
                    state["drafts"].pop(last_email_id, None)
                    _save_state(state)
                    _tg_send(f"📁 보관 완료: {email.get('subject', '')[:50]}")
                except Exception as e:
                    _tg_send(f"❌ 오류: {e}")

        # ── 라벨 ──────────────────────────────────────────────
        elif text_lower.startswith("라벨"):
            label_name = text[2:].strip()
            if last_email_id and label_name:
                try:
                    from gmail_service import apply_label
                    apply_label(last_email_id, label_name)
                    _tg_send(f"🏷️ 라벨 적용: [{label_name}]")
                except Exception as e:
                    _tg_send(f"❌ 오류: {e}")

        # ── 취소 ──────────────────────────────────────────────
        elif any(kw in text_lower for kw in ["취소", "cancel"]):
            if last_email_id:
                state["drafts"].pop(last_email_id, None)
                _save_state(state)
                _tg_send("🚫 초안이 취소되었습니다.")

        # ── 삭제 (현재 메일 휴지통) ───────────────────────────
        elif any(kw in text_lower for kw in ["삭제", "delete", "휴지통"]):
            if last_email_id:
                try:
                    from gmail_service import trash_email
                    email = pending.pop(last_email_id, {})
                    trash_email(last_email_id)
                    state["drafts"].pop(last_email_id, None)
                    _save_state(state)
                    _tg_send(f"🗑️ 삭제됨: {email.get('subject', '')[:50]}")
                except Exception as e:
                    _tg_send(f"❌ 오류: {e}")
            else:
                _tg_send("📭 삭제할 메일이 없습니다.")

        # ── 차단 추가 ─────────────────────────────────────────
        elif text_lower.startswith("차단 ") and not "목록" in text_lower and not "해제" in text_lower:
            target = text[3:].strip()
            if not target:
                _tg_send("사용법: <code>차단 이메일@주소.com</code> 또는 <code>차단 @도메인.com</code>")
            else:
                bl = _load_blocklist()
                if target.startswith("@"):
                    domain = target[1:]
                    if domain not in bl["domains"]:
                        bl["domains"].append(domain)
                        _save_blocklist(bl)
                        _tg_send(f"🚫 도메인 차단 추가: @{domain}")
                    else:
                        _tg_send(f"이미 차단됨: @{domain}")
                else:
                    if target not in bl["senders"]:
                        bl["senders"].append(target.lower())
                        _save_blocklist(bl)
                        _tg_send(f"🚫 발신자 차단 추가: {target}")
                    else:
                        _tg_send(f"이미 차단됨: {target}")
                # 현재 대기 중인 메일이 이 발신자면 함께 삭제
                if last_email_id:
                    blocked, _ = _is_blocked(pending.get(last_email_id, {}))
                    if blocked:
                        from gmail_service import trash_email
                        trash_email(last_email_id)
                        pending.pop(last_email_id, None)
                        state["drafts"].pop(last_email_id, None)
                        _save_state(state)
                        _tg_send("↳ 현재 메일도 자동 삭제됨")

        # ── 차단 발신자 자동 등록 (현재 메일 발신자) ────────────
        elif text_lower in ["이 발신자 차단", "발신자 차단", "차단"]:
            if last_email_id and last_email_id in pending:
                email = pending[last_email_id]
                from gmail_service import get_sender_email, trash_email
                sender = get_sender_email(email["from"])
                bl = _load_blocklist()
                if sender not in bl["senders"]:
                    bl["senders"].append(sender)
                    _save_blocklist(bl)
                trash_email(last_email_id)
                pending.pop(last_email_id, None)
                state["drafts"].pop(last_email_id, None)
                _save_state(state)
                _tg_send(f"🚫 차단 + 삭제 완료\n발신자: {sender}")
            else:
                _tg_send("📭 처리 대기 중인 메일이 없습니다.")

        # ── 차단 해제 ─────────────────────────────────────────
        elif "차단 해제" in text_lower:
            target = text_lower.replace("차단 해제", "").strip()
            bl = _load_blocklist()
            removed = False
            if target.startswith("@"):
                domain = target[1:]
                if domain in bl["domains"]:
                    bl["domains"].remove(domain); _save_blocklist(bl); removed = True
            else:
                t = target.lower()
                if t in bl["senders"]:
                    bl["senders"].remove(t); _save_blocklist(bl); removed = True
            _tg_send("✅ 차단 해제됨" if removed else "❌ 목록에 없습니다.")

        # ── 차단 목록 조회 ────────────────────────────────────
        elif any(kw in text_lower for kw in ["차단 목록", "/blocklist"]):
            bl = _load_blocklist()
            senders = bl.get("senders", [])
            domains = bl.get("domains", [])
            keywords = bl.get("keywords", [])
            if not senders and not domains and not keywords:
                _tg_send("차단 목록이 비어있습니다.")
            else:
                lines = ["🚫 <b>차단 목록</b>\n"]
                if senders:
                    lines.append("👤 발신자:")
                    lines += [f"  • {s}" for s in senders]
                if domains:
                    lines.append("🌐 도메인:")
                    lines += [f"  • @{d}" for d in domains]
                if keywords:
                    lines.append("🔑 키워드:")
                    lines += [f"  • {k}" for k in keywords]
                lines.append("\n💬 <code>차단 해제 [이메일/도메인]</code>")
                _tg_send("\n".join(lines))

        # ── 대기 목록 ─────────────────────────────────────────
        elif any(kw in text_lower for kw in ["/gmail", "메일 목록", "받은 메일"]):
            if not pending:
                _tg_send("📭 처리 대기 중인 메일이 없습니다.")
            else:
                lines = ["📬 <b>대기 중인 메일</b>\n"]
                for eid, em in list(pending.items())[-5:]:
                    lines.append(f"• {em['subject'][:40]} ({em['from'][:25]})")
                _tg_send("\n".join(lines))

    _save_state(state)


# ── 새 메일 체크 ──────────────────────────────────────────────

def check_new_emails(state: dict):
    try:
        from gmail_service import get_unread_emails, trash_email
        emails = get_unread_emails(max_results=10)
        notified  = state.get("notified", [])
        new_count = 0
        blocked_count = 0

        for email in emails:
            if email["id"] in notified:
                continue

            # 차단 목록 확인 → 조용히 휴지통
            blocked, reason = _is_blocked(email)
            if blocked:
                trash_email(email["id"])
                state["notified"].append(email["id"])
                blocked_count += 1
                _log(f"자동 삭제 [{reason}]: {email['subject'][:50]}")
                continue

            _log(f"새 메일: {email['subject'][:50]} from {email['from'][:40]}")
            summary = summarize_email(email)
            notify_new_email(email, summary, state)
            new_count += 1

        if new_count == 0 and blocked_count == 0:
            _log("새 메일 없음")
        elif blocked_count > 0:
            _log(f"자동 삭제 {blocked_count}건, 새 알림 {new_count}건")

        # 알림 목록 최대 200개 유지
        if len(state["notified"]) > 200:
            state["notified"] = state["notified"][-100:]
        _save_state(state)
    except Exception as e:
        _log(f"메일 체크 오류: {e}")
        import traceback; traceback.print_exc()


# ── 메인 루프 ─────────────────────────────────────────────────

def run_daemon():
    _log("=" * 50)
    _log("Gmail 봇 시작")
    _log(f"텔레그램 Chat ID: {TG_CHAT_ID or '미설정'}")
    _log(f"Anthropic API: {'설정됨' if ANTHROPIC_API_KEY else '미설정'}")
    _log("=" * 50)

    state = _load_state()
    _tg_send("🤖 <b>Gmail 봇 시작됨</b>\n새 메일 도착 시 요약을 보내드립니다.")

    last_check = 0
    while True:
        try:
            # 텔레그램 명령 처리 (매 10초)
            handle_commands(state)
            state = _load_state()

            # 새 메일 체크 (5분마다)
            now = time.time()
            if now - last_check >= CHECK_INTERVAL:
                check_new_emails(state)
                state = _load_state()
                last_check = now

            time.sleep(10)
        except KeyboardInterrupt:
            _log("봇 종료")
            break
        except Exception as e:
            _log(f"루프 오류: {e}")
            time.sleep(30)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--test",   action="store_true", help="새 메일 1회 체크")
    args = parser.parse_args()

    if args.test:
        state = _load_state()
        _log("[테스트] 새 메일 체크")
        check_new_emails(state)
    else:
        run_daemon()


if __name__ == "__main__":
    main()
