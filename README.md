# srbounce — S/R bounce multi-market backtester

> Monorepo: โฟลเดอร์ `livesignal/` คือ live trading service ที่ import กลยุทธ์
> จากแพ็กเกจ `srbounce` นี้โดยตรง — ดู `livesignal/README.md`
> แก้อะไรใน `srbounce/` ต้องรัน `python livesignal/tests/replay_parity.py` ให้ผ่านก่อน commit

กลยุทธ์: เข้าเทรดเฉพาะเมื่อราคาแตะโซนแนวรับ/แนวต้าน + มีแท่งยืนยันการกลับตัว (pin bar / engulfing)
Zone detection เป็นแบบ walk-forward — swing ยืนยันหลังผ่านไป N แท่งเท่านั้น ไม่มี lookahead bias

## ติดตั้ง (Ubuntu VM)

```bash
python3 -m venv venv && source venv/bin/activate
pip install pandas numpy pyyaml pyarrow ccxt yfinance
```

## ใช้งาน

```bash
python run.py                 # รันทุกตลาดใน config.yaml (BTC, ETH, SPY, QQQ, NVDA)
python run.py --refresh       # บังคับดึงข้อมูลใหม่
python run.py --market SPY    # รันตลาดเดียว
```

ผลออกที่ `results/`:
- `summary.csv` — เทียบทุกตลาด (win rate, profit factor, drawdown, PF แยกฝั่ง long/short)
- `trades_<MARKET>.csv` — รายการเทรดทุกไม้ พร้อม pattern, R-multiple, เหตุผลออก
- `equity_<MARKET>.csv` — equity curve

## ปรับกลยุทธ์ที่ config.yaml

| Key | ความหมาย |
|---|---|
| `swing_lookback` | จำนวนแท่งซ้าย/ขวาที่ใช้ยืนยัน swing (ค่ามาก = โซนน้อยแต่แข็ง) |
| `zone_atr_mult` | ความกว้างครึ่งโซน = ค่านี้ × ATR(14) |
| `min_touches` | จำนวนครั้งที่ราคาต้องแตะโซนก่อนเทรดได้ |
| `confirm_patterns` | `pin`, `engulfing` |
| `sl_atr_mult` | SL เลยขอบโซน = ค่านี้ × ATR |
| `rr_target` | TP = ค่านี้ × ระยะ risk |
| `trend_filter` | `ema200` (เทรดตามเทรนด์เท่านั้น) หรือ `null` (ปิด) |
| `risk_pct` | % ของ equity ที่เสี่ยงต่อไม้ |

## เพิ่มตลาด

เพิ่ม entry ใน `markets:` — adapter `ccxt` (crypto ทุก exchange ที่ ccxt รองรับ)
หรือ `yfinance` (หุ้น/ETF/ดัชนี US, `^GSPC`, `GC=F` ฯลฯ)

## ลำดับถัดไป

1. รัน backtest เทียบตลาด → เลือกตลาดที่ PF ดีสุด
2. Parameter sweep (swing_lookback 3–8, zone_atr_mult 0.2–0.5, min_touches 2–3)
3. Walk-forward validation (in-sample / out-of-sample split)
4. ต่อเข้า live pipeline: DataAdapter เดิม + approval gate (Telegram/LINE) + ExecAdapter
