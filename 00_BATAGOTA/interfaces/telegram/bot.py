"""
BATAGOTA Telegram Bot
텔레그램 채널을 통한 에이전트 접근 및 동적 명령 처리
"""
import os
import json
import shlex
import sys
import asyncio
import html
from pathlib import Path

try:
    from telegram import Update, InputFile
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
except ImportError:
    print("[telegram-bot] telegram 패키지 미설치. pip install python-telegram-bot")
    exit(1)

from dotenv import load_dotenv

# 프로젝트 루트 경로 설정
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MQTT_ROOT = PROJECT_ROOT.parent / "02_BATA_MQTT"

# core 패키지 import 가능하도록 경로 추가
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 환경변수 로드 (BATAGOTA 전용 .env가 있으면 우선 사용, 없으면 MQTT .env 사용)
load_dotenv(PROJECT_ROOT / "config" / ".env")
load_dotenv(MQTT_ROOT / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ALLOWED_USER_ID = os.getenv("TELEGRAM_ALLOWED_USER_ID", "")
TELEGRAM_NOTIFY_CHAT_ID = os.getenv("TELEGRAM_NOTIFY_CHAT_ID", "")

# 마스터 에이전트 라우터 임포트
from core.agent.main import route_intent
from core.agent.llm_intent_router import route_natural_language


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """시작 명령"""
    await update.message.reply_text(
        "🤖 BATAGOTA AI Agent\n\n"
        "<b>사용 가능한 명령:</b>\n\n"
        "<b>MQTT 관련:</b>\n"
        "/mqtt_report - MQTT 상태 조회\n"
        "/mqtt_connection_info - MQTT 브로커 주소/포트 조회\n"
        "/mqtt_clients - 현재 MQTT 동시 접속자 수\n"
        "/db_recent 20 - DB 최근 저장 20건 조회\n"
        "/topic_list - 관리 중인 Machine Topic 목록\n"
        "/topic_add 2 - Machine number 추가 (1~999)\n"
        "/topic_remove 2 - Machine number 제거\n"
        "/backup_status - 백업 현황\n"
        "/retention_status - 정리 현황\n\n"
        "<b>데이터 리포트:</b>\n"
        "/data_report stock monthly graph - 주식 월간 그래프\n"
        "/data_report stock yearly csv - 주식 연간 CSV\n"
        "/data_report crypto daily table - 암호화폐 일일 테이블\n\n"
        "<b>사용자 정의 요청:</b>\n"
        "/request &lt;action&gt; &lt;param1&gt; &lt;param2&gt; ... - 커스텀 요청\n",
        parse_mode="HTML"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """메시지 처리 및 동적 명령 파싱"""
    user_id = str(update.effective_user.id)
    
    # 허용된 사용자만
    if TELEGRAM_ALLOWED_USER_ID and user_id != TELEGRAM_ALLOWED_USER_ID:
        await update.message.reply_text("❌ 접근 권한이 없습니다.")
        return
    
    text = update.message.text.strip()
    print(f"[telegram-bot] incoming user={user_id} text={text}")
    
    # 고정 명령어 처리
    if text.startswith("/mqtt_report"):
        intent = "mqtt_report"
        params = {}
    elif text.startswith("/mqtt_connection_info"):
        intent = "mqtt_connection_info"
        params = {}
    elif text.startswith("/mqtt_clients"):
        intent = "mqtt_clients"
        params = {}
    elif text.startswith("/db_recent"):
        intent = "db_recent"
        params = _parse_db_recent_command(text)
    elif text.startswith("/topic_list"):
        intent = "mqtt_topic_list"
        params = {}
    elif text.startswith("/topic_add"):
        intent = "mqtt_topic_add"
        params = _parse_machine_no_command(text)
    elif text.startswith("/topic_remove"):
        intent = "mqtt_topic_remove"
        params = _parse_machine_no_command(text)
    elif text.startswith("/backup_status"):
        intent = "backup_status"
        params = {}
    elif text.startswith("/retention_status"):
        intent = "retention_status"
        params = {}
    elif text.startswith("/data_report"):
        # 동적 데이터 리포트 처리
        # 예: /data_report stock monthly graph [optional_params]
        intent = "data_report"
        params = _parse_data_report_command(text)
    elif text.startswith("/request"):
        # 범용 요청 처리
        intent, params = _parse_request_command(text)
    else:
        # 자연어 요청은 LLM intent 라우터로 해석
        nl_result = route_natural_language(text)
        if nl_result.get("status") != "ready":
            suggestion = nl_result.get("suggested_payload")
            suggestion_line = ""
            if suggestion:
                suggestion_line = (
                    "\n\n🧩 실행 제안:\n"
                    f"intent={suggestion.get('intent')}\n"
                    f"params={json.dumps(suggestion.get('params', {}), ensure_ascii=False)}"
                )
            await update.message.reply_text(
                "❓ 요청 해석이 필요합니다.\n"
                f"{nl_result.get('message', '요청을 더 구체적으로 입력해 주세요.')}"
                f"{suggestion_line}"
            )
            return

        intent = nl_result["intent"]
        params = nl_result.get("params", {})
        print(
            "[telegram-bot] nl-route "
            f"source={nl_result.get('source')} intent={intent} confidence={nl_result.get('confidence')}"
        )
    
    # 인텐트 라우팅 실행
    try:
        await update.message.chat.send_action("typing")
        
        result = route_intent(intent, params, auto_upload=True)
        print(f"[telegram-bot] intent={intent} status={result.get('status')}")
        
        if result.get("status") == "error":
            await update.message.reply_text(f"❌ 오류: {result.get('error')}")
        else:
            # 결과를 포맷팅해서 전송
            msg = format_result(intent, result)

            # 자연어 라우팅에서 들어온 요청이면 해석 정보를 함께 표시
            if not text.startswith("/"):
                msg = (
                    "🧠 <b>요청 해석</b>\n"
                    f"intent: {intent}\n"
                    f"params: {json.dumps(params, ensure_ascii=False)}\n\n"
                ) + msg
            
            # 파일이 있으면 함께 전송
            if result.get("output_file") and Path(result["output_file"]).exists():
                try:
                    with open(result["output_file"], "rb") as f:
                        await update.message.reply_document(
                            document=f,
                            caption=msg,
                            parse_mode="HTML"
                        )
                except Exception as e:
                    await update.message.reply_text(
                        msg + f"\n\n⚠️ 파일 전송 실패: {str(e)}",
                        parse_mode="HTML"
                    )
            else:
                await update.message.reply_text(msg, parse_mode="HTML")
    
    except Exception as e:
        await update.message.reply_text(f"❌ 처리 오류: {str(e)}")


def _parse_data_report_command(text: str) -> dict:
    """
    /data_report 명령 파싱
    예: /data_report stock monthly graph
    """
    parts = text.split()
    
    params = {}
    if len(parts) > 1:
        params["data_type"] = parts[1]  # stock, crypto, etc
    if len(parts) > 2:
        params["time_range"] = parts[2]  # daily, monthly, yearly
    if len(parts) > 3:
        params["format"] = parts[3]  # graph, table, csv
    
    # 추가 파라미터가 있으면 커스텀 파라미터로
    if len(parts) > 4:
        params["custom_params"] = {
            "extra": " ".join(parts[4:])
        }
    
    return params


def _parse_request_command(text: str) -> tuple:
    """
    /request 명령 파싱
    예: /request stock_compare symbols=AAPL,MSFT metric=price
    """
    parts = text.split(maxsplit=1)
    
    if len(parts) < 2:
        return "request", {}
    
    command_parts = parts[1].split()
    
    # 첫 부분: 인텐트
    intent = command_parts[0] if command_parts else "request"
    
    # 나머지: 파라미터
    params = {}
    for part in command_parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            # 값이 리스트인지 확인
            if "," in value:
                params[key] = value.split(",")
            else:
                params[key] = value
        else:
            params[part] = True
    
    return intent, params


def _parse_machine_no_command(text: str) -> dict:
    parts = text.split()
    if len(parts) < 2:
        return {}
    try:
        return {"machine_no": int(parts[1])}
    except ValueError:
        return {}


def _parse_db_recent_command(text: str) -> dict:
    parts = text.split()
    if len(parts) < 2:
        return {"limit": 20}
    try:
        return {"limit": int(parts[1])}
    except ValueError:
        return {"limit": 20}


def format_result(intent: str, result: dict) -> str:
    """결과를 텔레그램 메시지로 포맷팅"""
    status = result.get("status", "unknown")
    
    if status == "error":
        return f"❌ <b>오류</b>\n{result.get('error') or '요청 처리 실패(상세 오류 없음)'}"
    
    if status == "not_implemented":
        return f"🚧 <b>준비 중</b>\n{result.get('error', 'Feature not yet implemented')}"
    
    # intent별 포맷팅
    if intent == "mqtt_report":
        return _format_mqtt_report(result)
    elif intent == "mqtt_connection_info":
        return _format_mqtt_connection_info(result)
    elif intent == "mqtt_clients":
        return _format_mqtt_clients(result)
    elif intent == "db_recent":
        return _format_db_recent(result)
    elif intent == "mqtt_topic_list":
        return _format_topic_list(result)
    elif intent == "mqtt_topic_add":
        return _format_topic_add_remove(result, action="add")
    elif intent == "mqtt_topic_remove":
        return _format_topic_add_remove(result, action="remove")
    elif intent == "backup_status":
        return _format_backup_status(result)
    elif intent == "retention_status":
        return _format_retention_status(result)
    elif intent == "data_report":
        return _format_data_report(result)
    else:
        # 기본 포맷
        return f"📊 <b>{intent}</b>\n{json.dumps(result.get('result', {}), ensure_ascii=False, indent=2)}"


def _unwrap_result_payload(result: dict) -> dict:
    """
    route_intent 응답의 중첩 result 구조를 평탄화한다.
    예) result -> {status,intent,result:{status,intent,result:{...}}}
    """
    payload = result.get("result", {})
    while isinstance(payload, dict) and "result" in payload and isinstance(payload.get("result"), dict):
        payload = payload.get("result", {})
    return payload if isinstance(payload, dict) else {}


def _format_mqtt_report(result: dict) -> str:
    """MQTT 리포트 포맷"""
    health = _unwrap_result_payload(result)
    db = health.get("db", {})
    
    msg = (
        "📊 <b>MQTT 상태 리포트</b>\n\n"
        f"<b>데이터베이스:</b>\n"
        f"  총 로그: {db.get('total_logs', 'N/A')}개\n"
        f"  최근 1시간: {db.get('last_hour', 'N/A')}개\n"
        f"  최근 24시간: {db.get('last_24h', 'N/A')}개\n"
        f"  마지막 메시지: {db.get('last_message_at', 'N/A')}\n"
    )
    
    # 최근 백업 정보
    latest_backup = health.get("latest_backup", {})
    if latest_backup:
        msg += f"\n<b>최근 백업:</b>\n  {latest_backup.get('file', 'N/A')}"
    
    # 최근 정리 정보
    latest_retention = health.get("latest_retention", {})
    if latest_retention:
        msg += (
            f"\n<b>최근 정리:</b>\n"
            f"  삭제: {latest_retention.get('deleted_count', 'N/A')}개\n"
            f"  남은 로그: {latest_retention.get('total_after', 'N/A')}개"
        )
    
    return msg


def _format_backup_status(result: dict) -> str:
    """백업 상태 포맷"""
    logs = _unwrap_result_payload(result).get("backup_logs", [])
    
    if logs:
        latest = logs[0]
        return (
            "💾 <b>최근 백업</b>\n\n"
            f"상태: {latest.get('status')}\n"
            f"연월: {latest.get('year_month')}\n"
            f"시간: {latest.get('executed_at')}"
        )
    else:
        return "💾 <b>백업 기록</b>\n\n백업 기록이 없습니다."


def _format_mqtt_connection_info(result: dict) -> str:
    """MQTT 브로커 접속 정보 포맷"""
    info = _unwrap_result_payload(result)
    return (
        "🔌 <b>MQTT 접속 정보</b>\n\n"
        f"호스트: {info.get('host', 'N/A')}\n"
        f"포트: {info.get('port', 'N/A')}\n"
        f"기본 토픽: {info.get('topic', 'N/A')}\n"
        f"아이디 설정: {'예' if info.get('username_set') else '아니오'}\n"
        f"TLS 사용: {'예' if info.get('tls_enabled') else '아니오'}"
    )


def _format_mqtt_clients(result: dict) -> str:
    info = _unwrap_result_payload(result)
    clients = info.get("connected_clients", "N/A")
    note = info.get("note")
    msg = (
        "👥 <b>MQTT 동시 접속자 수</b>\n\n"
        f"현재 접속: {clients}\n"
        f"브로커: {info.get('host', 'N/A')}:{info.get('port', 'N/A')}\n"
        f"조회 토픽: {info.get('topic', '$SYS/broker/clients/connected')}"
    )
    if note:
        msg += f"\n참고: {note}"
    return msg


def _format_db_recent(result: dict) -> str:
    info = _unwrap_result_payload(result)
    rows = info.get("rows", [])
    limit = info.get("limit", 20)
    total_logs = info.get("total_logs", "N/A")
    last_5m_count = info.get("last_5m_count", "N/A")
    latest = info.get("latest") or {}

    if not rows:
        return (
            "🧾 <b>DB 최근 로그</b>\n\n"
            f"요청 건수: {limit}\n"
            "조회 결과가 없습니다."
        )

    header = "ID | TS(UTC) | TOPIC | PAYLOAD"
    body_lines = []
    for r in rows:
        rid = str(r.get("id", ""))
        ts = str(r.get("ts_utc", ""))[:19]
        topic = str(r.get("topic", ""))[:24]
        payload = str(r.get("payload_preview", "")).replace("\n", " ")[:52]
        body_lines.append(f"{rid:>6} | {ts:<19} | {topic:<24} | {payload}")

    table = "\n".join([header] + body_lines)
    return (
        "🧾 <b>DB 최근 로그</b>\n\n"
        f"요청/조회: {limit}/{len(rows)}건\n"
        f"총 로그: {total_logs}\n"
        f"최근 5분: {last_5m_count}\n"
        f"최신: {latest.get('ts_utc', 'N/A')} ({latest.get('topic', 'N/A')})\n\n"
        f"<pre>{html.escape(table)}</pre>"
    )


def _format_retention_status(result: dict) -> str:
    """정리 상태 포맷"""
    logs = _unwrap_result_payload(result).get("retention_logs", [])
    
    if logs:
        latest = logs[0]
        return (
            "🗑️ <b>최근 정리</b>\n\n"
            f"상태: {latest.get('status')}\n"
            f"삭제: {latest.get('deleted_count')}개\n"
            f"남은 로그: {latest.get('total_after')}개\n"
            f"시간: {latest.get('executed_at')}"
        )
    else:
        return "🗑️ <b>정리 기록</b>\n\n정리 기록이 없습니다."


def _format_topic_list(result: dict) -> str:
    info = _unwrap_result_payload(result)
    machines = info.get("machine_numbers", [])
    topics = info.get("topics", [])
    topic_lines = "\n".join([f"- {t}" for t in topics]) if topics else "- 없음"
    return (
        "🧩 <b>MQTT Topic 관리 목록</b>\n\n"
        f"Machine 수: {info.get('count', 0)} / 최대 {info.get('max_machines', 100)}\n"
        f"Machine 번호: {machines}\n"
        f"패턴: {info.get('topic_pattern', 'N/A')}\n\n"
        f"<b>Topics:</b>\n{topic_lines}"
    )


def _format_topic_add_remove(result: dict, action: str) -> str:
    info = _unwrap_result_payload(result)
    machine_no = info.get("machine_no", "N/A")
    topic = info.get("topic", "N/A")
    machines = info.get("machine_numbers", [])
    if action == "add":
        exists = info.get("already_exists", False)
        state_line = "이미 등록되어 있습니다." if exists else "추가되었습니다."
        title = "✅ <b>Topic 추가</b>"
    else:
        existed = info.get("existed", False)
        state_line = "제거되었습니다." if existed else "원래 목록에 없었습니다."
        title = "🧹 <b>Topic 제거</b>"

    return (
        f"{title}\n\n"
        f"Machine: M{machine_no}\n"
        f"Topic: {topic}\n"
        f"결과: {state_line}\n"
        f"현재 Machine 목록: {machines}"
    )


def _format_data_report(result: dict) -> str:
    """데이터 리포트 포맷"""
    data_type = result.get("result", {}).get("data_type", "unknown")
    status = result.get("result", {}).get("status", "unknown")
    
    if status == "not_implemented":
        return (
            f"🚧 <b>{data_type.upper()} 리포트</b>\n\n"
            f"준비 중입니다.\n\n"
            f"<b>예상 파라미터:</b>\n"
            f"{json.dumps(result.get('result', {}).get('expected_output', {}), ensure_ascii=False, indent=2)}"
        )
    else:
        file_path = result.get("output_file", "N/A")
        file_type = result.get("result", {}).get("output_type", "N/A")
        
        return (
            f"📈 <b>{data_type.upper()} 리포트</b>\n\n"
            f"형식: {file_type}\n"
            f"파일: {Path(file_path).name if file_path != 'N/A' else 'N/A'}"
        )


async def send_periodic_status(context: ContextTypes.DEFAULT_TYPE) -> None:
    """5분 주기 운영 상태 요약 알림"""
    if not TELEGRAM_NOTIFY_CHAT_ID:
        return

    try:
        report = route_intent("mqtt_report", {}, auto_upload=False)
        clients = route_intent("mqtt_clients", {}, auto_upload=False)
        recent = route_intent("db_recent", {"limit": 1}, auto_upload=False)

        db = _unwrap_result_payload(report).get("db", {})
        clients_info = _unwrap_result_payload(clients)
        recent_info = _unwrap_result_payload(recent)
        latest = recent_info.get("latest") or {}

        msg = (
            "⏱️ <b>5분 상태 요약</b>\n\n"
            f"총 로그: {db.get('total_logs', 'N/A')}\n"
            f"최근 5분 저장: {recent_info.get('last_5m_count', 'N/A')}\n"
            f"마지막 메시지: {db.get('last_message_at', 'N/A')}\n"
            f"현재 접속자: {clients_info.get('connected_clients', 'N/A')}\n"
            f"최신 토픽: {latest.get('topic', 'N/A')}"
        )

        target_chat = int(TELEGRAM_NOTIFY_CHAT_ID) if TELEGRAM_NOTIFY_CHAT_ID.isdigit() else TELEGRAM_NOTIFY_CHAT_ID
        await context.bot.send_message(chat_id=target_chat, text=msg, parse_mode="HTML")
    except Exception as e:
        print(f"[telegram-bot] periodic status send failed: {e}")


def main() -> None:
    """봇 시작"""
    if not TELEGRAM_BOT_TOKEN:
        print("[telegram-bot] TELEGRAM_BOT_TOKEN 미설정")
        return

    # Python 3.14에서는 기본 이벤트 루프가 자동 생성되지 않는다.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # 명령어 핸들러
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("mqtt_report", handle_message))
    app.add_handler(CommandHandler("mqtt_connection_info", handle_message))
    app.add_handler(CommandHandler("mqtt_clients", handle_message))
    app.add_handler(CommandHandler("db_recent", handle_message))
    app.add_handler(CommandHandler("topic_list", handle_message))
    app.add_handler(CommandHandler("topic_add", handle_message))
    app.add_handler(CommandHandler("topic_remove", handle_message))
    app.add_handler(CommandHandler("backup_status", handle_message))
    app.add_handler(CommandHandler("retention_status", handle_message))
    app.add_handler(CommandHandler("data_report", handle_message))
    app.add_handler(CommandHandler("request", handle_message))
    
    # 모든 텍스트 메시지 처리
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    if TELEGRAM_NOTIFY_CHAT_ID and app.job_queue:
        app.job_queue.run_repeating(send_periodic_status, interval=300, first=20, name="periodic_status_summary")
        print(f"[telegram-bot] periodic summary enabled (chat_id={TELEGRAM_NOTIFY_CHAT_ID})")
    elif TELEGRAM_NOTIFY_CHAT_ID:
        print("[telegram-bot] TELEGRAM_NOTIFY_CHAT_ID set, but job queue is unavailable")
    
    print("[telegram-bot] starting...")
    app.run_polling()


if __name__ == "__main__":
    main()

