"""Validated market price lookups shared by alerts and user commands."""

from __future__ import annotations

import asyncio
import re

import aiohttp
import yfinance as yf


SYMBOL_PATTERN = re.compile(r"^[A-Z0-9^][A-Z0-9.^=-]{0,19}$")


def normalize_symbol(asset_type: str, symbol: str) -> str:
    asset_type = asset_type.lower().strip()
    if asset_type not in {"stock", "crypto", "gold"}:
        raise ValueError("Unsupported asset type")
    if asset_type == "gold":
        return "GC=F"
    value = symbol.upper().strip()
    if not SYMBOL_PATTERN.fullmatch(value):
        raise ValueError("Invalid symbol")
    return value


def _yahoo_price(symbol: str) -> float:
    ticker = yf.Ticker(symbol)
    history = ticker.history(period="5d")
    if history.empty:
        raise ValueError("Price unavailable")
    return float(history["Close"].iloc[-1])


async def get_market_price(asset_type: str, symbol: str) -> tuple[str, float]:
    normalized = normalize_symbol(asset_type, symbol)
    if asset_type == "crypto":
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": f"{normalized}USDT"},
            ) as response:
                if response.status != 200:
                    raise ValueError("Crypto price unavailable")
                payload = await response.json(content_type=None)
        return normalized, float(payload["price"])
    return normalized, await asyncio.to_thread(_yahoo_price, normalized)
