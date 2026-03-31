# TUQUE SEASON 5 — DASHBOARD 🚀

**Live Paper Trading Dashboard**

- **Status:** PAPER TRADING LIVE (48-hour run)
- **Launch:** Tue 2026-03-31 11:28 AM PDT
- **End:** Thu 2026-04-02 11:28 AM PDT
- **Capital:** $1500 USD per bot ($6000 total)

---

## The Bots 🤖

### 1. **Loser Reversal Hunter** 🔄
- **Strategy:** Mean reversion on big losers
- **Entry:** 24h drops > -3%, 4h drops > -1%, 15m dips > -0.8%
- **Exit:** +16% take profit, -18% hard stop, 4h time stop
- **Max Position:** 75% of capital
- **Risk Profile:** Conservative mean reversion

### 2. **Chaos Prophet** 🔮
- **Strategy:** Contrarian pump fading + volatility arbitrage
- **Entry:** High volatility spikes (1.5x baseline), 2% dislocations
- **Exit:** +15% take profit, -45% hard stop, 6h time stop
- **Max Position:** 75% of capital
- **Risk Profile:** High volatility, reversal-focused

### 3. **Pump Surfer** 🏄
- **Strategy:** DexScreener real-time pump hunting
- **Entry:** 3x volume spike, 10%+ price surge
- **Exit:** +50% take profit, -50% hard stop, 3h time stop
- **Max Position:** 75% of capital
- **Risk Profile:** Aggressive momentum chasing

### 4. **Obsidian Flux** ⚫
- **Strategy:** Statistical mean reversion (Z-score based)
- **Entry:** Z-score > 2.0 from moving average
- **Exit:** +12% take profit, -35% hard stop, 12h time stop
- **Max Position:** 75% of capital
- **Risk Profile:** Moderate, systematic

---

## Trading Infrastructure

- **Execution:** Paper trading with live Coinbase market data
- **Symbols:** 9 Coinbase-verified pairs (BTC, ETH, SOL, AVAX, AKT, PRL, IOTX, AXS, AUDIO)
- **Fees:** 0.5% maker, 0.6% taker (realistic Coinbase fees)
- **Slippage:** 0.1% (market impact simulation)
- **Time Frame:** Continuous 48-hour trading

---

## Live Monitoring

**Real-time Dashboard:**
- Dashboard: http://localhost:3000 (Grafana)
- Live fills: `docker logs -f ptl-paper-trading-executor | grep PAPER_FILL`

**Status Checks:**
```bash
# Orders count
docker exec ptl-timescaledb psql -U paperbot -d paperbot -c \
  "SELECT bot_id, COUNT(*) as orders FROM bot_orders \
   WHERE season_id='season-005-paper-trading' GROUP BY bot_id;"

# P&L (every 12 hours)
docker exec ptl-timescaledb psql -U paperbot -d paperbot -c "
SELECT bot_id, 
  ROUND(100.0 * (SUM(executed_quantity * executed_price) - SUM(simulated_fee)) / 1500, 2) as roi_pct,
  ROUND((SUM(executed_quantity * executed_price) - SUM(simulated_fee)), 2) as net_pnl
FROM bot_orders
WHERE season_id='season-005-paper-trading'
GROUP BY bot_id ORDER BY net_pnl DESC;"
```

---

## Results Timeline

- **Hour 0-1:** Bots load, first orders expected
- **Hour 24:** 24-hour checkpoint (P&L snapshot)
- **Hour 48:** Final results + decision on live deployment

---

## Next Phase: Live Deployment (Phase 5)

Once paper trading completes and Coinbase approves API access:

1. **Select bots** based on P&L results
2. **Deploy to live** with chosen capital allocation
3. **Trade real money** using the winning strategies

---

## Technology Stack

- **Backend:** Python (asyncio, psycopg2)
- **Database:** TimescaleDB (hypertables for time-series)
- **Execution:** Paper Trading Executor (simulated fills)
- **Monitoring:** Grafana + TimescaleDB
- **Dashboard:** HTML/TailwindCSS/Chart.js (this repo)

---

**Season 5 Paper Trading: LIVE & RUNNING** ✅
