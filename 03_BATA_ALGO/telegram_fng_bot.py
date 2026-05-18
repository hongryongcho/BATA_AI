"""
FnG 투자 정보 텔레그램 봇
──────────────────────────────────────────────────────────────
미국 프리장 열리면 TQQQ/SOXL의 매수/매도 신호를 텔레그램으로 전송
"""

import os
import logging
from datetime import datetime
from typing import Optional

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes

from _env_loader import load_env_config


# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FnGTelegramBot:
    """FnG 투자 정보 텔레그램 봇"""

    def __init__(self):
        """봇 초기화"""
        env = load_env_config()
        self.bot_token = env.get("TELEGRAM_FNG_BOT_TOKEN")
        self.chat_id = env.get("TELEGRAM_FNG_CHAT_ID")
        
        if not self.bot_token:
            raise ValueError("❌ TELEGRAM_FNG_BOT_TOKEN 환경변수가 없습니다")
        
        self.bot = Bot(token=self.bot_token)
        self.application = Application.builder().token(self.bot_token).build()
        
        # 명령어 핸들러 등록
        self.application.add_handler(CommandHandler("start", self.handle_start))
        self.application.add_handler(CommandHandler("chatid", self.handle_chatid))
        self.application.add_handler(CommandHandler("test", self.handle_test))

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /start 명령어 처리
        - 사용자의 채팅방 정보 기록
        """
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        
        msg = (
            f"🤖 FnG 투자 봇 시작\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📱 Chat ID: `{chat_id}`\n"
            f"👤 User ID: `{user_id}`\n"
            f"📅 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"💡 명령어:\n"
            f"• `/chatid` - 현재 채팅방 ID 확인\n"
            f"• `/test` - 테스트 메시지 전송\n"
        )
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        
        # .env 파일에 Chat ID 저장하도록 유도
        logger.info(f"📌 새로운 사용자: Chat ID={chat_id}, User ID={user_id}")

    async def handle_chatid(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /chatid 명령어 처리
        - 현재 채팅방 ID 표시
        """
        chat_id = update.effective_chat.id
        
        msg = (
            f"📌 현재 채팅방 정보\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Chat ID: `{chat_id}`\n\n"
            f"💾 .env 파일에 저장:\n"
            f"```\n"
            f"TELEGRAM_FNG_CHAT_ID={chat_id}\n"
            f"```"
        )
        
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def handle_test(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        /test 명령어 처리
        - 테스트 메시지 전송
        """
        msg = (
            f"✅ FnG 봇 정상 작동\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} (미국 동부시간)\n"
        )
        
        await update.message.reply_text(msg, parse_mode="Markdown")

    async def send_trading_signal(
        self,
        ticker: str,
        signal: str,
        rsi_value: float,
        fng_value: int,
        price: float,
        buy_price: Optional[float] = None,
        sell_price: Optional[float] = None,
    ):
        """
        매매 신호 전송
        
        Args:
            ticker: 종목 (TQQQ, SOXL 등)
            signal: 신호 (BUY, SELL, HOLD)
            rsi_value: RSI(2) 값
            fng_value: Fear & Greed 지수 (0~100)
            price: 현재가
            buy_price: 매수 기준가 (선택)
            sell_price: 매도 기준가 (선택)
        """
        if not self.chat_id:
            logger.warning("⚠️  TELEGRAM_FNG_CHAT_ID가 설정되지 않았습니다")
            return
        
        # 신호에 따른 이모지
        signal_emoji = {
            "BUY": "🟢",
            "SELL": "🔴",
            "HOLD": "⏸️",
        }.get(signal, "❓")
        
        # Fear & Greed 단계
        fng_text = self._get_fng_text(fng_value)
        
        msg = (
            f"{signal_emoji} *{signal} 신호* - {ticker}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 RSI(2): {rsi_value:.2f}\n"
            f"😨 Fear & Greed: {fng_value}/100 {fng_text}\n"
            f"💵 현재가: ${price:,.2f}\n"
        )
        
        if buy_price:
            msg += f"🛒 매수기준가: ${buy_price:,.2f}\n"
        
        if sell_price:
            msg += f"💰 매도기준가: ${sell_price:,.2f}\n"
        
        msg += f"\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S (Eastern)')}\n"
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=msg,
                parse_mode="Markdown",
            )
            logger.info(f"✅ 메시지 전송 완료: {ticker} {signal}")
        except Exception as e:
            logger.error(f"❌ 메시지 전송 실패: {e}")

    async def send_daily_summary(self, summary: str):
        """
        일일 요약 전송
        
        Args:
            summary: 요약 텍스트
        """
        if not self.chat_id:
            logger.warning("⚠️  TELEGRAM_FNG_CHAT_ID가 설정되지 않았습니다")
            return
        
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=summary,
                parse_mode="Markdown",
            )
            logger.info("✅ 일일 요약 전송 완료")
        except Exception as e:
            logger.error(f"❌ 일일 요약 전송 실패: {e}")

    @staticmethod
    def _get_fng_text(fng_value: int) -> str:
        """Fear & Greed 텍스트 변환"""
        if fng_value <= 24:
            return "(Extreme Fear 😱)"
        elif fng_value <= 44:
            return "(Fear 😟)"
        elif fng_value <= 54:
            return "(Neutral 😐)"
        elif fng_value <= 74:
            return "(Greed 🤑)"
        else:
            return "(Extreme Greed 🚀)"

    async def start_polling(self):
        """폴링 모드로 봇 시작"""
        logger.info("🚀 FnG 텔레그램 봇 시작 (폴링 모드)")
        async with self.application:
            await self.application.start()
            await self.application.updater.start_polling()
            logger.info("✅ 봇 실행 중... (Ctrl+C로 종료)")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 독립 실행 모드 (테스트용)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    import asyncio
    
    print("\n" + "="*60)
    print("🤖 FnG 텔레그램 봇 - 테스트 모드")
    print("="*60)
    print("\n📌 사용 방법:")
    print("1. 텔레그램에서 @BataFnG_bot을 검색하여 그룹에 추가")
    print("2. 그룹에서 /start 명령 입력")
    print("3. Chat ID 확인 및 .env 파일에 저장")
    print("\n💡 테스트 명령어:")
    print("   /chatid - 현재 채팅방 ID 확인")
    print("   /test   - 테스트 메시지 전송")
    print("="*60 + "\n")
    
    try:
        bot = FnGTelegramBot()
        asyncio.run(bot.start_polling())
    except KeyboardInterrupt:
        logger.info("\n🛑 봇 중지됨")
    except Exception as e:
        logger.error(f"❌ 오류: {e}")
