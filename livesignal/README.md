# livesignal — full-auto S/R bounce trading service

เทรดกลยุทธ์ S/R bounce reversal บน **ETH/USDT (Binance, 4H)** อัตโนมัติเต็มรูปแบบ
พร้อมแจ้งเตือนทุกเหตุการณ์ผ่าน Telegram — BTC/USDT รันแบบ **signal-only**
(แจ้งเตือนอย่างเดียว ไม่เปิดไม้)

หลักการที่ห้ามละเมิด: **live logic == backtest logic** — zone detection และ
candle confirmation import ตรงจากแพ็กเกจ `srbounce`
(`ZoneTracker`, `confirm`, `evaluate_setup`, `evaluate_exit`) ไม่มีการ
copy/reimplement ใด ๆ

Config ที่ validate แล้ว (sweep 40 combos + walk-forward): IS PF 1.65 / OOS PF 1.81,
~2 ไม้/เดือน, max DD ~4% — อย่าแก้ `config.yaml` ส่วน strategy/risk
โดยไม่รัน sweep ใหม่

## ติดตั้ง (dev)

```bash
pip install -e ~/         # srbounce (จากโปรเจกต์ backtester)
pip install -e .          # livesignal
cp .env.example .env      # ใส่ TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
python -m livesignal.trader
```

## Acceptance test (ต้องผ่านก่อน deploy ทุกครั้งที่แตะโค้ด)

```bash
python tests/replay_parity.py --bars 2000
# ต้องจบด้วย "PARITY OK"
```

Replay ประวัติ ETH ผ่าน decision path เดียวกับ live loop (window 800 แท่ง)
แล้ว diff กับ `srbounce.engine.run_backtest` — ทุกไม้ต้องตรงกัน (เวลาเข้า, ทิศทาง,
entry/SL/TP/exit ภายใน rounding, R-multiple)

## Deploy (Docker บน Proxmox)

```bash
./build.sh                # vendor srbounce เข้า build context + build image
docker compose up -d      # restart: unless-stopped, SQLite อยู่ใน ./data
```

ต้องออก network ไป `api.binance.com` และ `api.telegram.org`

## โหมดการทำงาน

- **Phase 1 (ตอนนี้): `paper: true`** — จำลองไม้กับ paper equity, ไม่ส่ง order จริง
  รัน 2–3 เดือน (~5–8 สัญญาณ) แล้วเทียบ trade log กับ distribution ของ backtest
- **Phase 2: `paper: false`** — ส่ง market order จริงผ่าน ccxt
  ต้องใส่ `BINANCE_API_KEY`/`BINANCE_SECRET` ใน `.env`
  (key แบบ trade-only, ห้ามมีสิทธิ์ withdraw, IP-restricted)

## Telegram

แจ้งเตือน: trade opened/closed, BTC signal-only, weekly summary (จันทร์),
system events (start, pause, daily-loss-limit, errors)

คำสั่ง: `/status` `/zones` `/pause` `/resume`

## Risk controls

- risk ต่อไม้ 0.5% ของ equity
- daily loss limit 2%/วัน (UTC) — หยุดเปิดไม้ใหม่ ไม้เดิมยังถูก manage ต่อ
- `/pause` หยุดเปิดไม้ใหม่ทันที
- state ทั้งหมด (ไม้ที่เปิด, equity, paused) อยู่ใน SQLite — restart แล้วไม่หาย
  ไม่เปิดซ้ำ
- unhandled exception ใน loop = ไม่เปิดไม้ใหม่, แจ้ง Telegram, loop ทำงานต่อ

## Layout

```
livesignal/
  config.py    # โหลด yaml + .env + validate
  broker.py    # ccxt: fetch_ohlcv / fetch_last_price / (live) market order
  paper.py     # คณิตศาสตร์ fill เหมือน engine.py เป๊ะ (fee/slippage/sizing)
  trader.py    # signal loop — import strategy จาก srbounce
  notify.py    # Telegram ส่งข้อความ + poll คำสั่ง
  store.py     # SQLite: trades / state / zones_snapshot
  risk.py      # daily loss limit + pause
tests/replay_parity.py   # acceptance test: live == backtest
```

## Disclaimer

Phase 2 เทรดเงินจริง — ผล backtest ในอดีตไม่การันตีอนาคต edge ของ ETH
เป็นสิ่งที่วัดได้ ไม่ใช่คำสัญญา
