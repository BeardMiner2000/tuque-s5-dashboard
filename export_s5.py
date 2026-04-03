#!/usr/bin/env python3
import json
import os
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

CAPITAL_PER_BOT_USD = Decimal(os.getenv("S5_CAPITAL_PER_BOT_USD", "1500"))
SEASON_ID = os.getenv("S5_SEASON_ID", "season-005")
COINBASE_PRODUCTS_URL = os.getenv("COINBASE_PRODUCTS_URL", "https://api.exchange.coinbase.com/products")
MAKER_FEE_BPS = Decimal(os.getenv("MAKER_FEE_BPS", "1.875"))
TAKER_FEE_BPS = Decimal(os.getenv("TAKER_FEE_BPS", "4.875"))

BOTS = [
    {"id": "loser_reversal_hunter", "name": "Loser Reversal Hunter", "emoji": "🔄", "color": "#10b981"},
    {"id": "chaos_prophet", "name": "Chaos Prophet", "emoji": "🔮", "color": "#eab308"},
    {"id": "pump_surfer", "name": "Pump Surfer", "emoji": "🏄", "color": "#3b82f6"},
    {"id": "obsidian_flux", "name": "Obsidian Flux", "emoji": "⚫", "color": "#ec4899"},
]

BOT_IDS = [bot["id"] for bot in BOTS]
MARKET_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"]


def normalize_json(value):
    if isinstance(value, dict):
        return {str(k): normalize_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_json(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    return value


def get_connection():
    dsn = os.getenv("DB_DSN")
    if dsn:
        return psycopg2.connect(dsn, cursor_factory=RealDictCursor)
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "paperbot"),
        user=os.getenv("DB_USER", "paperbot"),
        password=os.getenv("DB_PASSWORD", "paperbot"),
        sslmode=os.getenv("DB_SSLMODE", "prefer"),
        cursor_factory=RealDictCursor,
    )


def fetch_coinbase_products():
    req = urllib.request.Request(
        COINBASE_PRODUCTS_URL,
        headers={"User-Agent": "tuque-s5-dashboard/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        products = json.loads(response.read().decode("utf-8"))

    symbols = []
    for product in products:
        quote = str(product.get("quote_currency", "")).upper()
        status = str(product.get("status", "")).lower()
        trading_disabled = bool(product.get("trading_disabled", False))
        product_id = product.get("id")
        if quote != "USD" or status != "online" or trading_disabled or not product_id:
            continue
        symbols.append(product_id)

    return sorted(symbols)


def fetch_dashboard_rows(conn):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            WITH latest_metrics AS (
                SELECT DISTINCT ON (bot_id)
                    bot_id,
                    equity_btc,
                    realized_pnl_btc,
                    trade_count,
                    ts
                FROM bot_metrics
                WHERE season_id = %s AND bot_id = ANY(%s)
                ORDER BY bot_id, ts DESC
            ),
            equity_context AS (
                SELECT
                    m.bot_id,
                    m.equity_btc,
                    m.realized_pnl_btc,
                    m.trade_count,
                    m.ts,
                    s.starting_equity_btc,
                    latest_btc.mark_price AS btc_usd
                FROM latest_metrics m
                JOIN seasons s ON s.season_id = %s
                LEFT JOIN LATERAL (
                    SELECT mark_price
                    FROM market_marks
                    WHERE season_id = %s AND symbol = 'BTCUSDT'
                    ORDER BY ts DESC
                    LIMIT 1
                ) latest_btc ON true
            ),
            order_stats AS (
                SELECT
                    bot_id,
                    COUNT(*) AS orders_count,
                    COUNT(*) FILTER (WHERE status = 'filled') AS fills_count,
                    COUNT(*) FILTER (WHERE status NOT IN ('filled', 'canceled', 'rejected', 'expired')) AS open_orders
                FROM bot_orders
                WHERE season_id = %s AND bot_id = ANY(%s)
                GROUP BY bot_id
            ),
            top_symbols AS (
                SELECT DISTINCT ON (bot_id)
                    bot_id,
                    symbol,
                    COUNT(*) OVER (PARTITION BY bot_id, symbol) AS symbol_count
                FROM bot_orders
                WHERE season_id = %s AND bot_id = ANY(%s)
                ORDER BY bot_id, symbol_count DESC, symbol ASC
            )
            SELECT
                e.bot_id,
                COALESCE(o.orders_count, 0) AS orders_count,
                COALESCE(o.fills_count, 0) AS fills_count,
                COALESCE(o.open_orders, 0) AS open_orders,
                e.trade_count,
                e.equity_btc,
                e.realized_pnl_btc,
                e.starting_equity_btc,
                e.btc_usd,
                e.ts,
                t.symbol AS top_symbol
            FROM equity_context e
            LEFT JOIN order_stats o ON o.bot_id = e.bot_id
            LEFT JOIN top_symbols t ON t.bot_id = e.bot_id
            ORDER BY e.bot_id ASC
            """,
            (SEASON_ID, BOT_IDS, SEASON_ID, SEASON_ID, SEASON_ID, BOT_IDS, SEASON_ID, BOT_IDS),
        )
        return cursor.fetchall()


def fetch_recent_orders(conn):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                ts,
                bot_id,
                symbol,
                side,
                status,
                COALESCE(executed_price, request_price) AS price,
                COALESCE(executed_quantity, requested_quantity) AS quantity,
                simulated_fee,
                rationale,
                metadata
            FROM bot_orders
            WHERE season_id = %s AND bot_id = ANY(%s)
            ORDER BY ts DESC, id DESC
            LIMIT 20
            """,
            (SEASON_ID, BOT_IDS),
        )
        return cursor.fetchall()


def fetch_order_history(conn):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                ts,
                bot_id,
                symbol,
                side,
                status,
                COALESCE(executed_price, request_price) AS price,
                COALESCE(executed_quantity, requested_quantity) AS quantity,
                simulated_fee,
                rationale,
                metadata
            FROM bot_orders
            WHERE season_id = %s AND bot_id = ANY(%s)
              AND ts >= NOW() - INTERVAL '7 days'
            ORDER BY ts DESC, id DESC
            LIMIT 1000
            """,
            (SEASON_ID, BOT_IDS),
        )
        return cursor.fetchall()


def fetch_equity_history(conn):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            WITH sampled AS (
                SELECT
                    bot_id,
                    date_trunc('minute', ts) AS bucket_ts,
                    AVG(equity_btc) AS equity_btc
                FROM bot_metrics
                WHERE season_id = %s
                  AND bot_id = ANY(%s)
                  AND ts >= NOW() - INTERVAL '7 days'
                GROUP BY bot_id, date_trunc('minute', ts)
            ),
            latest_btc AS (
                SELECT mark_price
                FROM market_marks
                WHERE season_id = %s AND symbol = 'BTCUSDT'
                ORDER BY ts DESC
                LIMIT 1
            )
            SELECT
                s.bot_id,
                s.bucket_ts,
                s.equity_btc,
                b.mark_price AS btc_usd
            FROM sampled s
            CROSS JOIN latest_btc b
            ORDER BY s.bucket_ts ASC, s.bot_id ASC
            """,
            (SEASON_ID, BOT_IDS, SEASON_ID),
        )
        return cursor.fetchall()


def fetch_market_history(conn):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            WITH sampled AS (
                SELECT
                    symbol,
                    date_trunc('minute', ts) AS bucket_ts,
                    AVG(mark_price) AS mark_price
                FROM market_marks
                WHERE season_id = %s
                  AND symbol = ANY(%s)
                  AND ts >= NOW() - INTERVAL '7 days'
                GROUP BY symbol, date_trunc('minute', ts)
            )
            SELECT symbol, bucket_ts, mark_price
            FROM sampled
            ORDER BY bucket_ts ASC, symbol ASC
            """,
            (SEASON_ID, MARKET_SYMBOLS),
        )
        return cursor.fetchall()


def build_payload(rows, recent_orders, order_history, equity_history_rows, market_history_rows, coinbase_products):
    rows_by_bot = {row["bot_id"]: row for row in rows}
    bots_payload = []
    total_orders = 0
    total_fills = 0
    traded_symbols = set()
    for bot in BOTS:
        row = rows_by_bot.get(bot["id"])
        equity_usd = CAPITAL_PER_BOT_USD
        pnl_usd = Decimal("0")
        roi_pct = Decimal("0")
        orders_count = 0
        fills_count = 0
        open_orders = 0
        top_symbol = None
        last_metric_at = None
        if row:
            btc_usd = Decimal(str(row["btc_usd"] or 0))
            equity_btc = Decimal(str(row["equity_btc"] or 0))
            starting_btc = Decimal(str(row["starting_equity_btc"] or 0))
            if btc_usd > 0:
                equity_usd = equity_btc * btc_usd
                pnl_usd = equity_usd - CAPITAL_PER_BOT_USD
            if starting_btc > 0:
                roi_pct = ((equity_btc / starting_btc) - Decimal("1")) * Decimal("100")
            orders_count = int(row["orders_count"] or 0)
            fills_count = int(row["fills_count"] or 0)
            open_orders = int(row["open_orders"] or 0)
            top_symbol = row["top_symbol"]
            last_metric_at = row["ts"].astimezone(timezone.utc).isoformat() if row["ts"] else None

        total_orders += orders_count
        total_fills += fills_count
        bots_payload.append(
            {
                "id": bot["id"],
                "name": bot["name"],
                "emoji": bot["emoji"],
                "color": bot["color"],
                "current_equity_usd": round(float(equity_usd), 2),
                "current_pnl_usd": round(float(pnl_usd), 2),
                "roi_pct": round(float(roi_pct), 2),
                "orders_count": orders_count,
                "fills_count": fills_count,
                "active_positions": open_orders,
                "top_symbol": top_symbol,
                "last_metric_at": last_metric_at,
            }
        )

    def serialize_order(row):
        rationale = normalize_json(row.get("rationale") or {})
        metadata = normalize_json(row.get("metadata") or {})
        strategy = rationale.get("strategy") or metadata.get("strategy")
        note = rationale.get("note") or rationale.get("exit_reason")
        category = "strategy_trade"
        if strategy == "btc_reserve_refill_v1" or note == "refill_usdt_liquidity":
            category = "reserve_refill"
        return {
            "ts": row["ts"].astimezone(timezone.utc).isoformat() if row["ts"] else None,
            "bot_id": row["bot_id"],
            "symbol": row["symbol"],
            "side": row["side"],
            "status": row["status"],
            "price": round(float(row["price"] or 0), 8),
            "quantity": round(float(row["quantity"] or 0), 8),
            "fee": round(float(row.get("simulated_fee") or 0), 8),
            "strategy": strategy,
            "note": note,
            "category": category,
            "rationale": rationale,
            "metadata": metadata,
        }

    recent_orders_payload = [serialize_order(row) for row in recent_orders]

    order_history_payload = []
    orders_by_bot = {bot_id: [] for bot_id in BOT_IDS}
    for row in order_history:
        symbol = row["symbol"]
        if symbol:
            traded_symbols.add(symbol)
        order_row = serialize_order(row)
        order_history_payload.append(order_row)
        if row["bot_id"] in orders_by_bot:
            orders_by_bot[row["bot_id"]].append(order_row)

    equity_points = []
    for row in equity_history_rows:
        btc_usd = Decimal(str(row["btc_usd"] or 0))
        equity_btc = Decimal(str(row["equity_btc"] or 0))
        equity_usd = float(equity_btc * btc_usd) if btc_usd > 0 else 0.0
        equity_points.append(
            {
                "ts": row["bucket_ts"].astimezone(timezone.utc).isoformat() if row["bucket_ts"] else None,
                "bot_id": row["bot_id"],
                "equity_usd": round(equity_usd, 2),
            }
        )

    market_points = [
        {
            "ts": row["bucket_ts"].astimezone(timezone.utc).isoformat() if row["bucket_ts"] else None,
            "symbol": row["symbol"],
            "price": round(float(row["mark_price"] or 0), 8),
        }
        for row in market_history_rows
    ]

    return {
        "summary": {
            "season_id": SEASON_ID,
            "capital_per_bot_usd": float(CAPITAL_PER_BOT_USD),
            "total_orders": total_orders,
            "total_fills": total_fills,
            "active_bots": len(BOTS),
            "verified_pairs": len(traded_symbols),
        },
        "bots": bots_payload,
        "recent_orders": recent_orders_payload,
        "order_history": order_history_payload,
        "orders_by_bot": orders_by_bot,
        "equity_history": equity_points,
        "market_history": market_points,
        "trading_config": {
            "execution_mode": "paper_trading_coinbase_data",
            "maker_fee_bps": float(MAKER_FEE_BPS),
            "taker_fee_bps": float(TAKER_FEE_BPS),
            "coinbase_product_count": len(coinbase_products),
            "coinbase_products_sample": coinbase_products[:16],
            "quote_currency_source": "Coinbase USD products mapped into internal USDT symbols",
        },
        "meta": {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "data_source": "timescaledb + coinbase public products",
        },
    }


def main():
    coinbase_products = fetch_coinbase_products()
    with get_connection() as conn:
        rows = fetch_dashboard_rows(conn)
        recent_orders = fetch_recent_orders(conn)
        order_history = fetch_order_history(conn)
        equity_history_rows = fetch_equity_history(conn)
        market_history_rows = fetch_market_history(conn)

    payload = build_payload(rows, recent_orders, order_history, equity_history_rows, market_history_rows, coinbase_products)
    output_path = Path(__file__).with_name("data.json")
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
