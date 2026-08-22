"""
Gmail SMTP로 PPT 파일 이메일 발송
"""

import smtplib
import os
import sys
import getpass
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders

SENDER = "hongryong.cho@gmail.com"
RECEIVER = "hongryong.cho@gmail.com"
ATTACH_FILE = os.path.join(os.path.dirname(__file__), "investor_strategy_comparison.pptx")

SUBJECT = "[BATA] TQQQ 룰 기반 9전략 비교 + FnG+RSI(2) 알고리즘 타당성 검증 PPT"
BODY = """안녕하세요,

첨부 파일은 전 세계 유명 개인투자자 전략 비교 + BATA FnG+RSI(2) 알고리즘 타당성 검증 자료입니다.

주요 내용:
 - BATA FnG+RSI(2) 전략 (S7): TQQQ 단일 종목 룰 기반 9전략 중 최적 검증
 - 기간별 백테스트: 2011~2024 (14년) vs 2021~2024 (최근 4년)
 - S7 최근 4년: 총수익 +684.8% / CAGR 67.7% / MDD -30.3% / Sharpe 1.37
 - 2022년 하락장에서 S7만 +61.3% 달성 (골든크로스 전략 -37.9% 대비)
 - S8 신전략 실험 (골든크로스 필터 + FnG RSI 결합): S7보다 열등함 확인
 - HFEA, Dual Momentum GEM, 강환국 VAA/BAA, 일본·싱가포르·독일 전략 비교

좋은 투자 되세요!
"""

def send():
    if not os.path.exists(ATTACH_FILE):
        print(f"[ERROR] 첨부 파일 없음: {ATTACH_FILE}")
        sys.exit(1)

    app_password = os.environ.get("APP_PASS", "").replace(" ", "")
    if not app_password:
        print(f"Gmail 앱 비밀번호를 입력하세요 (16자리, 공백 없이)")
        print(f"  발급: https://myaccount.google.com/apppasswords")
        print(f"  또는 환경변수: APP_PASS=xxxx python3 send_ppt_email.py")
        app_password = getpass.getpass("앱 비밀번호: ").replace(" ", "")

    msg = MIMEMultipart()
    msg["From"] = SENDER
    msg["To"] = RECEIVER
    msg["Subject"] = SUBJECT
    msg.attach(MIMEText(BODY, "plain", "utf-8"))

    filename = os.path.basename(ATTACH_FILE)
    with open(ATTACH_FILE, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
    msg.attach(part)

    print(f"\n{RECEIVER} 으로 발송 중 ...")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER, app_password)
        server.sendmail(SENDER, RECEIVER, msg.as_string())

    print("[완료] 이메일 발송 성공!")
    print(f"  받는 사람: {RECEIVER}")
    print(f"  첨부 파일: {filename}")

if __name__ == "__main__":
    send()
