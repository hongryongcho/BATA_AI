#!/bin/bash
# FnG 자동 거래 서비스 시작/관리 스크립트
# 
# 사용법:
#   ./start_services.sh start   - 모든 서비스 시작
#   ./start_services.sh stop    - 모든 서비스 중지
#   ./start_services.sh status  - 서비스 상태 확인
#   ./start_services.sh restart - 모든 서비스 재시작

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
LOG_DIR="$SCRIPT_DIR/logs"
SCHEDULER_LOG="$LOG_DIR/scheduler_fng.log"
PERSONAL_BOT_LOG="$LOG_DIR/personal_bot_daemon.log"

# 로그 디렉토리 생성
mkdir -p "$LOG_DIR"

# ANSI 색상
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

echo_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

echo_error() {
    echo -e "${RED}❌ $1${NC}"
}

echo_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# ────────────────────────────────────────────────────────────
# 스케줄러 데몬 관리
# ────────────────────────────────────────────────────────────

start_scheduler() {
    echo_info "FnG 스케줄러 데몬 시작..."
    
    # 기존 프로세스 확인
    if pgrep -f "scheduler_market_close.py --daemon" > /dev/null; then
        echo_warning "스케줄러가 이미 실행 중입니다."
        return 0
    fi
    
    # 데몬 시작
    cd "$SCRIPT_DIR"
    python3 scheduler_market_close.py --daemon >> "$SCHEDULER_LOG" 2>&1 &
    SCHEDULER_PID=$!
    
    sleep 2
    
    if pgrep -f "scheduler_market_close.py --daemon" > /dev/null; then
        echo_success "스케줄러 시작됨 (PID: $SCHEDULER_PID)"
        echo "   • 프리장(04:00 ET): 현재값 기준 업데이트"
        echo "   • 장마감(16:30 ET): 종가 기준 업데이트"
        echo "   • 로그: $SCHEDULER_LOG"
    else
        echo_error "스케줄러 시작 실패"
        return 1
    fi
}

stop_scheduler() {
    echo_info "FnG 스케줄러 중지..."
    
    if pkill -f "scheduler_market_close.py --daemon"; then
        echo_success "스케줄러 중지됨"
    else
        echo_warning "실행 중인 스케줄러 없음"
    fi
}

restart_scheduler() {
    stop_scheduler
    sleep 1
    start_scheduler
}

# ────────────────────────────────────────────────────────────
# 개인 봇 데몬 관리
# ────────────────────────────────────────────────────────────

start_personal_bot() {
    echo_info "개인 개발 봇 시작..."
    
    # 기존 프로세스 확인
    if pgrep -f "personal_bot.py --daemon" > /dev/null; then
        echo_warning "개인 봇이 이미 실행 중입니다."
        return 0
    fi
    
    # 데몬 시작
    cd "$SCRIPT_DIR"
    python3 personal_bot.py --daemon >> "$PERSONAL_BOT_LOG" 2>&1 &
    BOT_PID=$!
    
    sleep 2
    
    if pgrep -f "personal_bot.py --daemon" > /dev/null; then
        echo_success "개인 봇 시작됨 (PID: $BOT_PID)"
        echo "   • Telegram 명령: /start, /read, /run, /logs, /help"
        echo "   • 로그: $PERSONAL_BOT_LOG"
    else
        echo_error "개인 봇 시작 실패"
        return 1
    fi
}

stop_personal_bot() {
    echo_info "개인 봇 중지..."
    
    if pkill -f "personal_bot.py --daemon"; then
        echo_success "개인 봇 중지됨"
    else
        echo_warning "실행 중인 개인 봇 없음"
    fi
}

restart_personal_bot() {
    stop_personal_bot
    sleep 1
    start_personal_bot
}

# ────────────────────────────────────────────────────────────
# 상태 확인
# ────────────────────────────────────────────────────────────

check_status() {
    echo_info "서비스 상태 확인"
    echo ""
    
    # 스케줄러 상태
    if pgrep -f "scheduler_market_close.py --daemon" > /dev/null; then
        SCHED_PID=$(pgrep -f "scheduler_market_close.py --daemon")
        echo_success "FnG 스케줄러: 실행 중 (PID: $SCHED_PID)"
        SCHED_MEM=$(ps -p $SCHED_PID -o %mem=)
        echo "           메모리 사용: $SCHED_MEM%"
        echo "           함수: 프리장(04:00 ET) & 장마감(16:30 ET) 자동 실행"
    else
        echo_error "FnG 스케줄러: 중지됨"
    fi
    
    echo ""
    
    # 개인 봇 상태
    if pgrep -f "personal_bot.py --daemon" > /dev/null; then
        BOT_PID=$(pgrep -f "personal_bot.py --daemon")
        echo_success "개인 개발 봇: 실행 중 (PID: $BOT_PID)"
        BOT_MEM=$(ps -p $BOT_PID -o %mem=)
        echo "           메모리 사용: $BOT_MEM%"
        echo "           함수: Telegram /start, /read, /run 등"
    else
        echo_error "개인 개발 봇: 중지됨"
    fi
    
    echo ""
    echo_info "마지막 로그 5줄"
    echo "─────────────────────────────────────────"
    if [ -f "$SCHEDULER_LOG" ]; then
        echo "📊 스케줄러:"
        tail -3 "$SCHEDULER_LOG"
        echo ""
    fi
    if [ -f "$PERSONAL_BOT_LOG" ]; then
        echo "🤖 개인 봇:"
        tail -3 "$PERSONAL_BOT_LOG"
    fi
}

# ────────────────────────────────────────────────────────────
# 메인 루프
# ────────────────────────────────────────────────────────────

main() {
    case "${1:-status}" in
        start)
            echo ""
            echo "════════════════════════════════════════════════════════════"
            echo "🚀 FnG 투자 자동화 서비스 시작"
            echo "════════════════════════════════════════════════════════════"
            echo ""
            start_scheduler
            echo ""
            start_personal_bot
            echo ""
            echo_info "모든 서비스가 백그라운드에서 실행 중입니다."
            echo "   • 프리장(04:00 ET): 현재값 기준 자동 거래"
            echo "   • 장마감(16:30 ET): 종가 기준 자동 거래"
            echo "   • Telegram 개인 봇: 언제든 /start 명령 가능"
            echo ""
            sleep 3
            check_status
            ;;
        stop)
            echo ""
            echo "════════════════════════════════════════════════════════════"
            echo "🛑 서비스 중지"
            echo "════════════════════════════════════════════════════════════"
            echo ""
            stop_scheduler
            echo ""
            stop_personal_bot
            echo ""
            echo_success "모든 서비스가 중지되었습니다."
            ;;
        restart)
            echo ""
            echo "════════════════════════════════════════════════════════════"
            echo "🔄 서비스 재시작"
            echo "════════════════════════════════════════════════════════════"
            echo ""
            restart_scheduler
            echo ""
            restart_personal_bot
            echo ""
            sleep 3
            check_status
            ;;
        status)
            echo ""
            echo "════════════════════════════════════════════════════════════"
            echo "📋 서비스 상태"
            echo "════════════════════════════════════════════════════════════"
            echo ""
            check_status
            ;;
        *)
            echo ""
            echo "════════════════════════════════════════════════════════════"
            echo "📖 사용법"
            echo "════════════════════════════════════════════════════════════"
            echo ""
            echo "  ./start_services.sh start    - 모든 서비스 시작"
            echo "  ./start_services.sh stop     - 모든 서비스 중지"
            echo "  ./start_services.sh status   - 서비스 상태 확인 (기본값)"
            echo "  ./start_services.sh restart  - 모든 서비스 재시작"
            echo ""
            echo "════════════════════════════════════════════════════════════"
            echo ""
            ;;
    esac
}

main "$@"
