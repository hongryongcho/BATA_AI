#!/usr/bin/env python3
"""
WebSocket + Whisper STT 간단한 테스트.
JWT 토큰으로 인증.
"""

import asyncio
import websockets
import json
import base64
import io
import math
import struct
import wave
from security import create_token


def generate_test_wav_base64(seconds: float = 1.2, sample_rate: int = 16000, freq: float = 440.0) -> str:
    frames = int(sample_rate * seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for i in range(frames):
            value = int(0.25 * 32767 * math.sin(2.0 * math.pi * freq * (i / sample_rate)))
            wav_file.writeframes(struct.pack("<h", value))
    return base64.b64encode(buffer.getvalue()).decode()

async def test_ws():
    session_id = 2
    # JWT 토큰 생성
    token = create_token("user-hong", "hong", "counselor")
    uri = f"ws://127.0.0.1:8000/ws/sessions/{session_id}/transcript?token={token}"
    
    try:
        async with websockets.connect(uri) as websocket:
            print(f"✓ WebSocket 연결 성공: {uri}\n")
            
            # 더미 청크 5개 전송
            test_chunks = [
                "오늘 상담 목표를 먼저 정해보겠습니다.",
                "진로 선택이 너무 어렵고 불안합니다.",
                "선택지를 3개로 줄여서 비교해봅시다.",
                "부모님 의견도 많이 신경 쓰입니다.",
                "네 그 부분은 다음 단계에서 같이 정리하겠습니다.",
            ]
            
            for i, text in enumerate(test_chunks):
                wav_audio = generate_test_wav_base64(freq=440.0 + (i * 30.0))
                
                message = {
                    "chunk_index": i,
                    "audio_b64": wav_audio,
                    "audio_format": "audio/wav",
                }
                
                await websocket.send(json.dumps(message))
                print(f"[전송] 청크 {i}: {message}")
                
                # 응답 받기
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=5)
                    result = json.loads(response)
                    print(f"[응답] {result}\n")
                except asyncio.TimeoutError:
                    print(f"[타임아웃] 청크 {i} 응답 없음\n")
                
                # 3.5초 대기 (UI와 동일한 청크 간격)
                await asyncio.sleep(3.5)
            
            print("\n✓ 테스트 완료")
            return True
            
    except Exception as e:
        print(f"✗ 오류: {e}")
        return False

if __name__ == "__main__":
    asyncio.run(test_ws())
