import logging
import requests
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

_POSITIVE = [
    "rally", "surge", "gain", "rise", "bullish", "positive", "strong",
    "recovery", "bounce", "support", "growth", "profit", "buy", "optimism",
    "high", "outperform", "upgrade", "record", "boom", "jump", "soar",
]
_NEGATIVE = [
    "fall", "crash", "decline", "drop", "bearish", "negative", "weak",
    "sell", "resistance", "loss", "risk", "fear", "worry", "low",
    "underperform", "downgrade", "recession", "inflation", "debt", "crisis",
    "slump", "plunge", "tumble",
]

_RSS_FEEDS = [
    "https://www.moneycontrol.com/rss/marketreports.xml",
    "https://www.moneycontrol.com/rss/latestnews.xml",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
    "https://www.business-standard.com/rss/markets-106.rss",
]

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; AlgoBot/1.0)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Encoding": "identity",
}


def _fetch_headlines(url: str) -> list:
    try:
        resp = requests.get(url, timeout=8, headers=_HEADERS)
        resp.raise_for_status()
        text = resp.content.decode("utf-8", errors="replace").lstrip("﻿").strip()
        if not text.startswith("<"):
            logger.warning(f"[NEWS] {url} returned non-XML content")
            return []
        root = ET.fromstring(text)
        headlines = []
        for item in root.iter("item"):
            title = item.find("title")
            if title is not None and title.text:
                headlines.append(title.text.lower())
        return headlines
    except Exception as e:
        logger.warning(f"[NEWS] Feed {url} failed: {e}")
        return []


def get_sentiment() -> str:
    """Return 'bullish', 'bearish', or 'neutral' from latest market news headlines."""
    headlines = []
    for url in _RSS_FEEDS:
        fetched = _fetch_headlines(url)
        headlines.extend(fetched)
        if len(headlines) >= 10:
            break

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
