#!/usr/bin/env python3
"""
FnG 텔레그램 봇 - Chat ID 획득 및 테스트
──────────────────────────────────────────────────────────────
1. 테스트 메시지 전송
2. Chat ID 자동 감지
"""

import asyncio
from datetime import datetime
from telegram import Bot
from _env_loader import load_env_config


async def send_test_message():
    """테스트 메시지 전송"""
    env = load_env_config()
    bot_token = env.get("TELEGRAM_FNG_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_FNG_CHAT_ID")
    
    if not bot_token:
        print("❌ TELEGRAM_FNG_BOT_TOKEN이 설정되지 않았습니다")
        return
    
    bot = Bot(token=bot_token)
    
    # 봇 정보 확인
    try:
        me = await bot.get_me()
        print(f"\n✅ 봇 연결 성공!")
        print(f"   봇 이름: @{me.username}")
        print(f"   봇 ID: {me.id}\n")
    except Exception as e:
        print(f"❌ 봇 연결 실패: {e}")
        return
    
    if not chat_id:
        print("⚠️  TELEGRAM_FNG_CHAT_ID가 설정되지 않았습니다")
        print("\n📌 설정 방법:")
        print("1. 텔레그램에서 새 그룹 생성")
        print("2. @BataFnG_bot을 그룹에 초대")
        print("3. 그룹에서 /start 명령 입력")
        print("4. 그룹에서 /chatid 명령 입력")
        print("5. 출력된 Chat ID를 .env 파일에 저장\n")
        return
    
    try:
        # 테스트 메시지
        msg = (
            f"✅ FnG 투자 봇 테스트 메시지\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 봇 이름: @{me.username}\n"
            f"📱 Chat ID: {chat_id}\n"
            f"📅 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"🎯 이 메시지가 보인다면 텔레그램 연동 완료!\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        
        await bot.send_message(
            chat_id=chat_id,
            text=msg,
        )
        print(f"✅ 테스트 메시지 전송 완료!")
        print(f"   Chat ID: {chat_id}\n")
        
    except Exception as e:
        print(f"❌ 메시지 전송 실패: {e}\n")


async def send_trading_example():
    """매매 신호 예제 전송 - CNN 실제 F&G 값 사용"""
    env = load_env_config()
    bot_token = env.get("TELEGRAM_FNG_BOT_TOKEN")
    chat_id = env.get("TELEGRAM_FNG_CHAT_ID")
    
    if not bot_token or not chat_id:
        return
    
    # CNN 실제 Fear & Greed 값 조회
    import sys, os
    sys.path.insert(0, os.path.dirname(__file__))
    from fear_greed import fetch_fear_greed
    fng = fetch_fear_greed()
    fng_value = fng["value"]
    fng_label = fng["label"].title()
    fng_source = fng["source"].upper()
    
    bot = Bot(token=bot_token)
    
    # FnG 단계 이모지
    if fng_value <= 24:
        fng_emoji = "😱"
    elif fng_value <= 44:
        fng_emoji = "😟"
    elif fng_value <= 54:
        fng_emoji = "😐"
    elif fng_value <= 74:
        fng_emoji = "🤑"
    else:
        fng_emoji = "🚀"
    
    # 예제 메시지 (실제 CNN F&G 값 반영)
    msg_buy = (
        f"🟢 BUY 신호 - TQQQ\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 RSI(2): 12.50\n"
        f"😨 Fear & Greed: {fng_value}/100 ({fng_label} {fng_emoji}) [{fng_source}]\n"
        f"💵 현재가: $75.32\n"
        f"🛒 매수기준가: $74.50\n"
        f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S (Eastern)')}\n"
    )
    
    try:
        await bot.send_message(chat_id=chat_id, text=msg_buy)
        print(f"✅ BUY 신호 예제 전송 완료 (CNN F&G: {fng_value} {fng_label})")
    except Exception as e:
        print(f"❌ 예제 전송 실패: {e}")


async def main():
    """메인 함수"""
    print("\n" + "="*60)
    print("🤖 FnG 텔레그램 봇 - 테스트 모드")
    print("="*60)
    
    await send_test_message()
    
    # Chat ID가 설정되었으면 예제도 전송
    env = load_env_config()
    if env.get("TELEGRAM_FNG_CHAT_ID"):
        print("\n📨 매매 신호 예제 전송...")
        await send_trading_example()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 중지됨")
    except Exception as e:
        print(f"❌ 오류: {e}")
