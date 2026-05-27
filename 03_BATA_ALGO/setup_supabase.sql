-- ============================================================
-- BATA Dashboard — Supabase 테이블 초기 설정
-- Supabase → SQL Editor 에서 전체 복사 후 실행
-- ============================================================

-- 1. accounts 테이블 (계좌 관리, 최대 10개/유저)
CREATE TABLE IF NOT EXISTS public.accounts (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID REFERENCES auth.users NOT NULL,
  name         TEXT NOT NULL,
  broker       TEXT DEFAULT '',
  initial_cash NUMERIC DEFAULT 0,
  created_at   TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, name)
);
ALTER TABLE public.accounts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "users own accounts" ON public.accounts;
CREATE POLICY "users own accounts" ON public.accounts
  FOR ALL USING (auth.uid() = user_id);

-- 2. trades 테이블 (거래 내역 — 주식 + 현금 거래)
CREATE TABLE IF NOT EXISTS public.trades (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID REFERENCES auth.users NOT NULL,
  account_id  UUID REFERENCES public.accounts(id) ON DELETE SET NULL,
  trade_date  DATE NOT NULL,
  ticker      TEXT NOT NULL,
  action      TEXT NOT NULL,   -- BUY | SELL | DEPOSIT | WITHDRAWAL | TRANSFER
  shares      NUMERIC NOT NULL DEFAULT 0,
  price       NUMERIC NOT NULL,
  notes       TEXT DEFAULT '',
  created_at  TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE public.trades ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "users own trades" ON public.trades;
CREATE POLICY "users own trades" ON public.trades
  FOR ALL USING (auth.uid() = user_id);

-- 3. journal 테이블 (투자 일지)
CREATE TABLE IF NOT EXISTS public.journal (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID REFERENCES auth.users NOT NULL,
  entry_date  DATE NOT NULL,
  strategy    TEXT DEFAULT '',
  resolution  TEXT DEFAULT '',
  created_at  TIMESTAMPTZ DEFAULT now(),
  updated_at  TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, entry_date)
);
ALTER TABLE public.journal ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "users own journal" ON public.journal;
CREATE POLICY "users own journal" ON public.journal
  FOR ALL USING (auth.uid() = user_id);

-- 완료 확인
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('accounts', 'trades', 'journal')
ORDER BY table_name;
