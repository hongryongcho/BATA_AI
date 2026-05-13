import json
import io
import base64
from datetime import datetime, timezone

import whisper
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session as DBSession

from database import SessionLocal
from models import Transcript, Session as SessionModel

router = APIRouter(tags=["websocket"])

# Whisper 모델 로드 (첫 요청 시만, 이후 캐싱)
WHISPER_MODEL = None


def get_whisper_model():
    global WHISPER_MODEL
    if WHISPER_MODEL is None:
        print("[STT] Whisper 모델 로드 중... (base)")
        WHISPER_MODEL = whisper.load_model("base")
    return WHISPER_MODEL


@router.websocket("/ws/sessions/{session_id}/transcript")
async def ws_transcript(session_id: int, websocket: WebSocket):
    """
    실시간 음성 전사 WebSocket.
    클라이언트: { "chunk_index": 0, "audio_b64": "..." }  (base64 인코딩 오디오)
    서버 응답:  { "saved": true, "chunk_index": 0, "transcript": "..." }

    - 각 청크가 수신될 때마다 Whisper로 실시간 전사
    - raw 레이어에는 transcribed 텍스트 누적 저장
    - 연결 종료 시 세션 status → processing 자동 전환
    """
    await websocket.accept()
    db: DBSession = SessionLocal()
    chunks_received = 0

    try:
        print(f"[WS] 세션 {session_id} 연결됨")
        model = get_whisper_model()

        while True:
            raw_data = await websocket.receive_text()
            data = json.loads(raw_data)
            chunk_index: int = data.get("chunk_index", 0)
            audio_b64: str = data.get("audio_b64", "")

            if not audio_b64:
                continue

            chunks_received += 1

            # Base64 디코딩 → 바이너리 오디오
            try:
                audio_bytes = base64.b64decode(audio_b64)
                
                # MVP 테스트: 더미 텍스트 반환
                # 실제 구현: librosa로 WAV 로드 → Whisper transcribe()
                test_transcripts = [
                    "오늘 상담 목표를 먼저 정해보겠습니다.",
                    "진로 선택이 너무 어렵고 불안합니다.",
                    "선택지를 3개로 줄여서 비교해봅시다.",
                    "부모님 의견도 많이 신경 쓰입니다.",
                    "네 그 부분은 다음 단계에서 같이 정리하겠습니다.",
                ]
                transcript_text = test_transcripts[chunk_index % len(test_transcripts)]

                # 기존 raw 텍스트 조회 (있으면 누적)
                existing_raw = (
                    db.query(Transcript)
                    .filter(
                        Transcript.session_id == session_id,
                        Transcript.layer == "raw",
                        Transcript.is_latest == True,
                    )
                    .first()
                )

                if existing_raw:
                    # 기존 텍스트 + 새 전사
                    combined = existing_raw.content + "\n" + transcript_text if transcript_text else existing_raw.content
                    existing_raw.content = combined
                    db.commit()
                else:
                    # 새로운 raw 텍스트
                    new_raw = Transcript(
                        session_id=session_id,
                        layer="raw",
                        version=1,
                        content=transcript_text,
                        edited_by=None,
                        is_latest=True,
                    )
                    db.add(new_raw)
                    db.commit()

                # 클라이언트에 응답
                await websocket.send_text(
                    json.dumps({
                        "saved": True,
                        "chunk_index": chunk_index,
                        "transcript": transcript_text,
                        "total_chunks": chunks_received,
                    })
                )

                print(f"[STT] 세션 {session_id}, 청크 {chunk_index}: {transcript_text}")

            except Exception as e:
                print(f"[ERROR] Whisper 전사 실패: {e}")
                await websocket.send_text(
                    json.dumps({
                        "saved": False,
                        "chunk_index": chunk_index,
                        "error": str(e),
                    })
                )

    except WebSocketDisconnect:
        print(f"[WS] 세션 {session_id} 연결 종료 (청크 수: {chunks_received})")
        session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
        if session and session.status == "recording":
            session.status = "processing"
            db.commit()
    except Exception as e:
        print(f"[ERROR] WebSocket 오류: {e}")
    finally:
        db.close()
