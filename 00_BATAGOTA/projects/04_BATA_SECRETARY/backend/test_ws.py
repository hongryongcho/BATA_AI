#!/usr/bin/env python3
"""
WebSocket + Whisper STT 간단한 테스트.
"""

import asyncio
import websockets
import json
import base64

async def test_ws():
    session_id = 2
    uri = f"ws://127.0.0.1:8000/ws/sessions/{session_id}/transcript"
    
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
                # 더미 base64 오디오
                dummy_audio = base64.b64encode(b"dummy_audio_" + str(i).encode()).decode()
                
                message = {
                    "chunk_index": i,
                    "audio_b64": dummy_audio,
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
                
                # 2초 대기
                await asyncio.sleep(2)
            
            print("\n✓ 테스트 완료")
            
    except Exception as e:
        print(f"✗ 오류: {e}")

if __name__ == "__main__":
    asyncio.run(test_ws())
