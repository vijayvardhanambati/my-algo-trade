import logging
import requests
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

_POSITIVE = [
    "rally", "surge", "gain", "rise", "bullish", "positive", "strong",
    "recovery", "bounce", "support", "growth", "profit", "buy", "optimism",
    "high", "outperform", "upgrade", "record", "boom",
]
_NEGATIVE = [
    "fall", "crash", "decline", "drop", "bearish", "negative", "weak",
    "sell", "resistance", "loss", "risk", "fear", "worry", "low",
    "underperform", "downgrade", "recession", "inflation", "debt", "crisis",
]

_RSS_FEEDS = [
    "https://economictimes.indiatimes.com/markets/stocks/rss.cms",
    "https://www.moneycontrol.com/rss/marketreports.xml",
]


def get_sentiment() -> str:
    """Return 'bullish', 'bearish', or 'neutral' from latest market news headlines."""
    headlines = []
    for url in _RSS_FEEDS:
        try:
            resp = requests.get(url, timeout=5)
            root = ET.fromstring(resp.content)
            for item in root.iter("item"):
                title = item.find("title")
                if title is not None and title.text:
                    headlines.append(title.text.lower())
            if headlines:
                break
        except Exception as e:
            logger.warning(f"[NEWS] Feed {url} failed: {e}")

    if not headlines:
        logger.warning("[NEWS] No headlines fetched — returning neutral")
        return "neutral"

    positive = sum(1 for h in headlines for w in _POSITIVE if w in h)
    negative = sum(1 for h in headlines for w in _NEGATIVE if w in h)

    logger.info(f"[NEWS] Headlines: {len(headlines)} | Positive signals: {positive} | Negative signals: {negative}")

    if positive > negative * 1.5:
        return "bullish"
    if negative > positive * 1.5:
        return "bearish"
    return "neutral"
