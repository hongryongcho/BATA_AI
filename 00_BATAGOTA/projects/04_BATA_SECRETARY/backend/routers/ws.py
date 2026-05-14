import json
import base64
from urllib.parse import parse_qs

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from database import db_cursor
from stt import transcribe_audio_bytes

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
            audio_format: str = data.get("audio_format", "webm")

            if not audio_b64:
                continue

            chunks_received += 1

            # Base64 디코딩 → 바이너리 오디오
            try:
                audio_bytes = base64.b64decode(audio_b64)
                transcript_text = transcribe_audio_bytes(
                    audio_bytes,
                    chunk_index=chunk_index,
                    audio_format=audio_format,
                    language="ko",
                )

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
