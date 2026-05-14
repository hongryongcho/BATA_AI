#!/usr/bin/env python3
"""
BATA Secretary 자동화 테스트 스위트.
- JWT 토큰 생성/검증
- WebSocket + STT 파이프라인
- 승인 워크플로우 (confirm1 → confirm2)
- API 권한 검증
"""

import asyncio
import json
import requests
import websockets
import base64
import io
import math
import struct
import wave
from datetime import datetime

BASE_URL = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000"


def generate_test_wav_base64(seconds: float = 1.2, sample_rate: int = 16000, freq: float = 440.0) -> str:
    """간단한 테스트 WAV 파일 생성."""
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


class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.jwt_token = None
        self.approver_token = None
    
    def assert_eq(self, actual, expected, msg: str):
        if actual == expected:
            print(f"  ✓ {msg}")
            self.passed += 1
        else:
            print(f"  ✗ {msg} (expected {expected}, got {actual})")
            self.failed += 1
    
    def assert_true(self, condition, msg: str):
        if condition:
            print(f"  ✓ {msg}")
            self.passed += 1
        else:
            print(f"  ✗ {msg}")
            self.failed += 1
    
    async def run(self):
        print("\n" + "="*60)
        print("BATA Secretary 자동화 테스트")
        print("="*60)
        
        await self.test_jwt_login()
        await self.test_jwt_validation()
        await self.test_ws_with_jwt()
        await self.test_approval_workflow()
        
        print("\n" + "="*60)
        print(f"결과: {self.passed} 통과, {self.failed} 실패")
        print("="*60)
    
    async def test_jwt_login(self):
        print("\n[테스트 1] JWT 로그인")
        
        # 상담자 로그인
        resp = requests.post(
            f"{BASE_URL}/auth/login",
            json={"username": "hong", "password": "hong123"}
        )
        self.assert_eq(resp.status_code, 200, "상담자 로그인 상태 코드")
        
        data = resp.json()
        self.assert_true("access_token" in data, "access_token 필드 존재")
        self.assert_eq(data.get("token_type"), "bearer", "token_type이 'bearer'")
        self.assert_eq(data.get("username"), "hong", "username이 'hong'")
        
        self.jwt_token = data.get("access_token")
        
        # 승인자 로그인
        resp = requests.post(
            f"{BASE_URL}/auth/login",
            json={"username": "kim", "password": "kim456"}
        )
        self.assert_eq(resp.status_code, 200, "승인자 로그인 상태 코드")
        self.approver_token = resp.json().get("access_token")
    
    async def test_jwt_validation(self):
        print("\n[테스트 2] JWT 토큰 검증")
        
        # 유효한 토큰으로 헬스 체크
        resp = requests.get(f"{BASE_URL}/")
        self.assert_eq(resp.status_code, 200, "헬스 체크 상태 코드")
        
        # 잘못된 토큰으로 승인 API 호출
        resp = requests.post(
            f"{BASE_URL}/api/v1/sessions/2/approvals/confirm1",
            headers={"Authorization": "Bearer invalid-token"}
        )
        self.assert_eq(resp.status_code, 401, "잘못된 토큰 거부 (401)")
        
        # 올바른 토큰으로 승인 API 호출
        resp = requests.post(
            f"{BASE_URL}/api/v1/sessions/2/approvals/confirm1",
            json={"note": "테스트 승인"},
            headers={"Authorization": f"Bearer {self.approver_token}"}
        )
        self.assert_eq(resp.status_code, 200, "올바른 토큰 승인 (200)")
    
    async def test_ws_with_jwt(self):
        print("\n[테스트 3] WebSocket + JWT 토큰")
        
        session_id = 2
        uri = f"{WS_URL}/ws/sessions/{session_id}/transcript?token={self.jwt_token}"
        
        try:
            async with websockets.connect(uri) as websocket:
                self.assert_true(True, "WebSocket 연결 성공")
                
                # 테스트 청크 1개 전송
                wav_audio = generate_test_wav_base64(freq=440.0)
                message = {
                    "chunk_index": 0,
                    "audio_b64": wav_audio,
                    "audio_format": "audio/wav",
                }
                
                await websocket.send(json.dumps(message))
                print("  → 청크 0 전송")
                
                # 응답 수신
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=10)
                    result = json.loads(response)
                    
                    self.assert_true(result.get("saved"), "오디오 저장됨")
                    self.assert_eq(result.get("chunk_index"), 0, "청크 인덱스 일치")
                    self.assert_true(len(result.get("transcript", "")) > 0, "전사 결과 수신")
                    
                except asyncio.TimeoutError:
                    self.assert_true(False, "WebSocket 응답 타임아웃 (10초)")
                
        except Exception as e:
            self.assert_true(False, f"WebSocket 오류: {e}")
    
    async def test_approval_workflow(self):
        print("\n[테스트 4] 승인 워크플로우")
        
        session_id = 2
        
        # 1차 승인
        resp = requests.post(
            f"{BASE_URL}/api/v1/sessions/{session_id}/approvals/confirm1",
            json={"note": "1차 승인"},
            headers={"Authorization": f"Bearer {self.approver_token}"}
        )
        self.assert_eq(resp.status_code, 200, "1차 승인 요청 (confirm1)")
        
        # 2차 승인
        resp = requests.post(
            f"{BASE_URL}/api/v1/sessions/{session_id}/approvals/confirm2",
            json={"note": "2차 승인"},
            headers={"Authorization": f"Bearer {self.approver_token}"}
        )
        self.assert_eq(resp.status_code, 200, "2차 승인 요청 (confirm2)")
        
        # 거절 (재시작)
        resp = requests.post(
            f"{BASE_URL}/api/v1/sessions/{session_id}/approvals/revise",
            json={"note": "수정 필요"},
            headers={"Authorization": f"Bearer {self.approver_token}"}
        )
        self.assert_eq(resp.status_code, 200, "수정 요청 (revise)")


async def main():
    runner = TestRunner()
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
