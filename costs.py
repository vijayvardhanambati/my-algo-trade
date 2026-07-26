"""Approximate Zerodha intraday equity (MIS) charges.

Rates below match Zerodha's published intraday equity tariff as of early 2026.
Zerodha revises this schedule occasionally — cross-check against
console.zerodha.com/charges before trusting these numbers for real money.
"""

BROKERAGE_RATE = 0.0003        # 0.03% per executed order
BROKERAGE_CAP = 20.0           # ...or ₹20, whichever is lower
STT_RATE = 0.00025             # 0.025% on sell-side turnover, intraday equity
EXCHANGE_TXN_RATE = 0.0000297  # NSE transaction charges, both legs
SEBI_RATE = 0.0000001          # ₹10 per crore, both legs
STAMP_DUTY_RATE = 0.00003      # 0.003% on buy-side value only
GST_RATE = 0.18                # on brokerage + exchange txn charges + SEBI charges


def calculate_charges(buy_value: float, sell_value: float) -> dict:
    """Round-trip charges for one intraday buy+sell of equal quantity."""
    brokerage = min(BROKERAGE_CAP, buy_value * BROKERAGE_RATE) + min(BROKERAGE_CAP, sell_value * BROKERAGE_RATE)
    stt = sell_value * STT_RATE
    exchange_txn = (buy_value + sell_value) * EXCHANGE_TXN_RATE
    sebi = (buy_value + sell_value) * SEBI_RATE
    stamp_duty = buy_value * STAMP_DUTY_RATE
    gst = GST_RATE * (brokerage + exchange_txn + sebi)

    total = brokerage + stt + exchange_txn + sebi + stamp_duty + gst

    return {
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 2),
        "exchange_txn": round(exchange_txn, 2),
        "sebi": round(sebi, 2),
        "stamp_duty": round(stamp_duty, 2),
        "gst": round(gst, 2),
        "total": round(total, 2),
    }
