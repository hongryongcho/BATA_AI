"""
개인용 개발 봇 + Claude AI 대화
────────────────────────────────────────────────────────

사용법:
    python3 personal_bot.py --daemon

텔레그램 명령어:
    /start              - 봇 초기화 및 Chat ID 등록
    /read <파일>        - 파일 내용 읽기
    /run <명령어>       - 스크립트 실행
    /logs               - 최근 로그 확인
    /reset              - Claude 대화 기록 초기화
    /help               - 도움말 표시

Claude AI 대화:
    명령어(/로 시작) 가 아닌 일반 텍스트 → Claude에게 전달
    이전 대화 문맥 유지 (최근 20개 메시지)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).parent.resolve()
KST = ZoneInfo("Asia/Seoul")

# ─────────────────────────────────────────────────────────────
# 환경 설정 로드
# ─────────────────────────────────────────────────────────────

def _load_env() -> dict:
    env_path = SCRIPT_DIR / ".env"
    data = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                data[k.strip()] = v.strip()
    return data

ENV = _load_env()
BOT_TOKEN         = ENV.get("TELEGRAM_PERSONAL_BOT_TOKEN", "")
ALLOWED_CHAT_ID   = ENV.get("TELEGRAM_PERSONAL_CHAT_ID", "")
ANTHROPIC_API_KEY = ENV.get("ANTHROPIC_API_KEY", "")

# 대화 기록 파일
HISTORY_FILE = SCRIPT_DIR / "claude_history.json"
MAX_HISTORY  = 20   # 유지할 최대 메시지 수

# ─────────────────────────────────────────────────────────────
# 로깅
# ─────────────────────────────────────────────────────────────

LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "personal_bot.log"

def _log(msg: str):
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{now}] {msg}"
    print(line)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# ─────────────────────────────────────────────────────────────
# 텔레그램 메시지 송수신
# ─────────────────────────────────────────────────────────────

def _send_tg_message(chat_id: str, text: str) -> dict:
    """텔레그램 메시지 전송"""
    if not chat_id or not BOT_TOKEN:
        raise ValueError("Chat ID 또는 Bot Token이 없습니다.")
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    body = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            if not data.get("ok"):
                raise RuntimeError(f"텔레그램 전송 실패: {data}")
            return data
    except Exception as e:
        _log(f"❌ 텔레그램 전송 오류: {e}")
        raise

def _get_updates(offset: int = 0) -> list:
    """텔레그램 메시지 폴링"""
    if not BOT_TOKEN:
        return []
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    body = {"offset": offset, "timeout": 30}
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw)
            return data.get("result", [])
    except Exception as e:
        _log(f"⚠️ 폴링 오류: {e}")
        return []

# ─────────────────────────────────────────────────────────────
# 파일 작업
# ─────────────────────────────────────────────────────────────

def _cmd_read(chat_id: str, args: str):
    """파일 읽기"""
    file_path = args.strip()
    if not file_path:
        _send_tg_message(chat_id, "❌ 파일 경로를 지정해주세요.\n예: /read scheduler_market_close.py")
        return
    
    target = SCRIPT_DIR / file_path
    if not target.exists():
        _send_tg_message(chat_id, f"❌ 파일을 찾을 수 없습니다: {file_path}")
        return
    
    try:
        content = target.read_text()
        lines = content.splitlines()
        
        # 3500자씩 청크로 분할
        chunks = []
        current_chunk = ""
        for line in lines:
            if len(current_chunk) + len(line) + 1 > 3500:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = line + "\n"
            else:
                current_chunk += line + "\n"
        if current_chunk:
            chunks.append(current_chunk)
        
        # 첫 번째 청크만 전송
        msg = f"📄 {file_path} (총 {len(lines)}줄)\n```\n{chunks[0][:3500]}\n```"
        if len(chunks) > 1:
            msg += f"\n\n📌 이후 {len(chunks)-1}개 부분 더 있음"
        _send_tg_message(chat_id, msg)
        _log(f"✅ 파일 읽기: {file_path}")
    except Exception as e:
        _send_tg_message(chat_id, f"❌ 파일 읽기 오류: {e}")

def _cmd_run(chat_id: str, args: str):
    """스크립트 실행"""
    cmd = args.strip()
    if not cmd:
        _send_tg_message(chat_id, "❌ 실행할 명령어를 지정해주세요.\n예: /run python3 scheduler_market_close.py --dry-run")
        return
    
    try:
        _send_tg_message(chat_id, f"⏳ 실행 중...\n\n```\n{cmd}\n```")
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=str(SCRIPT_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )
        
        output = result.stdout if result.returncode == 0 else result.stderr
        output = output[-3000:] if len(output) > 3000 else output
        
        status = "✅ 성공" if result.returncode == 0 else f"❌ 실패 (exit {result.returncode})"
        msg = f"{status}\n\n```\n{output}\n```"
        _send_tg_message(chat_id, msg)
        _log(f"✅ 명령 실행: {cmd}")
    except subprocess.TimeoutExpired:
        _send_tg_message(chat_id, f"⏱️ 타임아웃 (300초 초과)")
    except Exception as e:
        _send_tg_message(chat_id, f"❌ 실행 오류: {e}")

def _cmd_logs(chat_id: str):
    """최근 로그 확인"""
    if not LOG_FILE.exists():
        _send_tg_message(chat_id, "📋 아직 로그가 없습니다.")
        return
    
    try:
        lines = LOG_FILE.read_text().splitlines()
        recent = "\n".join(lines[-20:])
        msg = f"📋 최근 로그 (최근 20줄)\n\n```\n{recent}\n```"
        _send_tg_message(chat_id, msg)
    except Exception as e:
        _send_tg_message(chat_id, f"❌ 로그 읽기 오류: {e}")

def _cmd_help(chat_id: str):
    """도움말"""
    help_text = """🤖 BataMain_Bot (개발봇 + Claude AI)

🧠 Claude AI 대화
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
명령어(/로 시작)가 아닌 일반 텍스트는
모두 Claude AI에게 전달됩니다.
이전 대화 문맥이 유지됩니다.

예시:
  "TQQQ 현재 RSI가 몇이야?"
  "오늘 시장 어떻게 봐?"
  "파이썬 코드 리뷰해줘"

🔄 /reset  — 대화 기록 초기화

개발 명령어
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📖 /read <파일>  — 파일 읽기
▶️ /run <명령어>  — 스크립트 실행
📋 /logs         — 최근 로그 확인
❓ /help         — 이 도움말
"""
    _send_tg_message(chat_id, help_text)

# ─────────────────────────────────────────────────────────────
# Claude AI 대화
# ─────────────────────────────────────────────────────────────

CLAUDE_SYSTEM = """당신은 BATAGOTA 시스템의 AI 비서입니다. 사용자는 한국인 투자자이자 개발자입니다.

주요 운영 시스템:
- FnG RSI(2) 투자 알고리즘: TQQQ/SOXL 자동 매매 신호 (RSI<15 매수, RSI>75/90 매도)
- QQQ Crash Guard: QQQ -5% 하락 시 강제 매도 + 10일 쿨다운
- GC(골든크로스) 매도지연: 보유중 QQQ MA50>MA200 발생 시 +12일 지연
- TQQQ 수익목표: 15% 달성 시 즉시 매도
- 서버: M4 Mac mini (24시간 운영, macOS)
- 도메인: batagota.com (stock.batagota.com: 투자 대시보드)

항상 한국어로 답변하고, 간결하고 명확하게 답변하세요."""


def _load_history() -> list:
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text())
        except Exception:
            pass
    return []


def _save_history(history: list):
    # 최대 MAX_HISTORY개 유지
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2))


def _claude_chat(chat_id: str, user_text: str):
    """Claude API 호출 및 응답 반환"""
    if not ANTHROPIC_API_KEY:
        _send_tg_message(chat_id, "❌ ANTHROPIC_API_KEY가 설정되지 않았습니다.")
        return

    history = _load_history()
    history.append({"role": "user", "content": user_text})

    url  = "https://api.anthropic.com/v1/messages"
    body = json.dumps({
        "model":      "claude-sonnet-4-6",
        "max_tokens": 2048,
        "system":     CLAUDE_SYSTEM,
        "messages":   history,
    }).encode()
    headers = {
        "Content-Type":      "application/json",
        "x-api-key":         ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }

    try:
        req = urllib.request.Request(url, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r:
            resp    = json.loads(r.read())
            answer  = resp["content"][0]["text"]
    except Exception as e:
        _send_tg_message(chat_id, f"❌ Claude 오류: {e}")
        _log(f"Claude API 오류: {e}")
        return

    history.append({"role": "assistant", "content": answer})
    _save_history(history)

    # 4000자 초과 시 분할 전송
    if len(answer) <= 4000:
        _send_tg_message(chat_id, answer)
    else:
        for i in range(0, len(answer), 4000):
            _send_tg_message(chat_id, answer[i:i+4000])

    _log(f"Claude 응답: {answer[:60]}...")


def _cmd_reset(chat_id: str):
    """Claude 대화 기록 초기화"""
    _save_history([])
    _send_tg_message(chat_id, "🔄 대화 기록이 초기화되었습니다. 새로운 대화를 시작하세요.")
    _log("Claude 대화 기록 초기화")


def _cmd_start(chat_id: str):
    """봇 초기화 및 Chat ID 저장"""
    try:
        env_path = SCRIPT_DIR / ".env"
        content = env_path.read_text()
        
        lines = content.splitlines()
        new_lines = []
        found = False
        for line in lines:
            if line.startswith("TELEGRAM_PERSONAL_CHAT_ID="):
                new_lines.append(f"TELEGRAM_PERSONAL_CHAT_ID={chat_id}")
                found = True
            else:
                new_lines.append(line)
        
        if not found:
            new_lines.append(f"TELEGRAM_PERSONAL_CHAT_ID={chat_id}")
        
        env_path.write_text("\n".join(new_lines) + "\n")
        
        msg = f"""✅ 봇 초기화 완료!

🎉 Your Chat ID: {chat_id}
🤖 Bot: @BataMain_Bot
📂 Directory: {SCRIPT_DIR}

이제 모든 명령어를 사용할 수 있습니다.
/help를 입력하면 명령어를 확인할 수 있습니다."""
        _send_tg_message(chat_id, msg)
        _log(f"✅ 봇 초기화: Chat ID {chat_id}")
    except Exception as e:
        _send_tg_message(chat_id, f"❌ 초기화 오류: {e}")
        _log(f"❌ 초기화 실패: {e}")

# ─────────────────────────────────────────────────────────────
# 메인 폴링 루프
# ─────────────────────────────────────────────────────────────

def polling_loop():
    """텔레그램 메시지 폴링 및 처리"""
    if not BOT_TOKEN:
        _log("❌ BOT_TOKEN이 설정되지 않았습니다.")
        return
    
    _log("🟢 개인용 봇 시작 (polling mode)")
    offset = 0
    
    while True:
        try:
            updates = _get_updates(offset=offset)
            
            for update in updates:
                offset = max(offset, update.get("update_id", 0) + 1)
                
                msg = update.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                text = msg.get("text", "").strip()
                
                if not chat_id or not text:
                    continue
                
                # 승인 확인
                if ALLOWED_CHAT_ID and chat_id != ALLOWED_CHAT_ID and not text.startswith("/start"):
                    _send_tg_message(chat_id, "❌ 승인되지 않은 사용자입니다. /start를 입력해주세요.")
                    continue
                
                # 명령어 처리
                if text.startswith("/start"):
                    _cmd_start(chat_id)
                elif text.startswith("/read "):
                    _cmd_read(chat_id, text[6:].strip())
                elif text.startswith("/run "):
                    _cmd_run(chat_id, text[5:].strip())
                elif text == "/logs":
                    _cmd_logs(chat_id)
                elif text in ("/reset", "/clear", "/초기화"):
                    _cmd_reset(chat_id)
                elif text == "/help":
                    _cmd_help(chat_id)
                else:
                    # 명령어가 아닌 일반 텍스트 → Claude에게 전달
                    _log(f"Claude 질문: {text[:60]}")
                    _claude_chat(chat_id, text)
            
            time.sleep(1)
        
        except KeyboardInterrupt:
            _log("🟠 봇 종료 (Ctrl+C)")
            break
        except Exception as e:
            _log(f"⚠️ 폴링 루프 오류: {e}")
            time.sleep(5)

# ─────────────────────────────────────────────────────────────
# CLI 인터페이스
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="개인용 개발 봇")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--daemon", action="store_true", help="daemon 모드 시작")
    group.add_argument("--test", action="store_true", help="테스트 메시지 전송")
    args = parser.parse_args()
    
    if args.daemon:
        polling_loop()
    elif args.test:
        if not BOT_TOKEN or not ALLOWED_CHAT_ID:
            print("❌ 먼저 /start를 텔레그램에서 보내주세요.")
            return
        _send_tg_message(ALLOWED_CHAT_ID, "✅ 봇이 정상 작동 중입니다!")
        print("✅ 테스트 메시지 전송 완료")

if __name__ == "__main__":
    main()
