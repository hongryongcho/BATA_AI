import json
import base64
from urllib.parse import parse_qs

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from database import db_cursor

router = APIRouter(tags=["websocket"])

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
    token = (parse_qs(websocket.scope.get("query_string", b"").decode()).get("token", [""])[0]).strip()
    if not token.startswith("demo-token-"):
        await websocket.close(code=1008)
        return

    with db_cursor() as conn:
        session = conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not session:
            await websocket.close(code=1008)
            return

    await websocket.accept()
    chunks_received = 0

    try:
        print(f"[WS] 세션 {session_id} 연결됨")

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
                _audio_bytes = base64.b64decode(audio_b64)

                # MVP 테스트: 더미 텍스트 반환
                test_transcripts = [
                    "오늘 상담 목표를 먼저 정해보겠습니다.",
                    "진로 선택이 너무 어렵고 불안합니다.",
                    "선택지를 3개로 줄여서 비교해봅시다.",
                    "부모님 의견도 많이 신경 쓰입니다.",
                    "네 그 부분은 다음 단계에서 같이 정리하겠습니다.",
                ]
                transcript_text = test_transcripts[chunk_index % len(test_transcripts)]

                with db_cursor() as conn:
                    row = conn.execute(
                        "SELECT id, content FROM transcripts WHERE session_id = ? AND layer = 'raw' AND is_latest = 1 ORDER BY version DESC LIMIT 1",
                        (session_id,),
                    ).fetchone()

                    if row:
                        combined = f"{row['content']}\n{transcript_text}" if transcript_text else row["content"]
                        conn.execute(
                            "UPDATE transcripts SET content = ? WHERE id = ?",
                            (combined, row["id"]),
                        )
                    else:
                        conn.execute(
                            "INSERT INTO transcripts (session_id, layer, version, content, edited_by, is_latest) VALUES (?, 'raw', 1, ?, NULL, 1)",
                            (session_id, transcript_text),
                        )
                    conn.commit()

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
        with db_cursor() as conn:
            session = conn.execute(
                "SELECT id, status FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if session and session["status"] == "recording":
                conn.execute(
                    "UPDATE sessions SET status = 'processing' WHERE id = ?",
                    (session_id,),
                )
                conn.commit()
    except Exception as e:
        print(f"[ERROR] WebSocket 오류: {e}")
    finally:
        pass
