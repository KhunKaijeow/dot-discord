"""Cryptocurrency slash commands."""

import discord
from discord.ext import commands
from discord import app_commands

def format_large_number(val):
    """Format volume or large numbers beautifully (e.g., Millions, Billions)."""
    if val is None:
        return "N/A"
    try:
        val = float(val)
        if val >= 1_000_000_000:
            return f"${val / 1_000_000_000:.2f}B"
        elif val >= 1_000_000:
            return f"${val / 1_000_000:.2f}M"
        return f"${val:,.2f}"
    except (ValueError, TypeError):
        return "N/A"

from datetime import datetime
from ..services.chart_generator import generate_price_chart
from ..ui import EmbedColor, make_embed, set_embed_author

class CryptoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="crypto", description="ค้นหารายละเอียดราคาเหรียญคริปโตตามเวลาจริง")
    @app_commands.describe(symbol="ชื่อย่อเหรียญคริปโต เช่น BTC, ETH, SOL, DOGE")
    async def crypto(self, interaction: discord.Interaction, symbol: str = "BTC"):
        # Format the symbol
        symbol = symbol.strip().upper()

        await interaction.response.defer(thinking=True)

        # Binance ticker and historical klines (30 days) endpoints
        ticker_url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}USDT"
        klines_url = f"https://api.binance.com/api/v3/klines?symbol={symbol}USDT&interval=1d&limit=30"

        try:
            async with self.bot.external_http.get(ticker_url) as response:
                if response.status == 200:
                    data = await response.json()

                    # Fetch historical klines for chart
                    klines_data = []
                    async with self.bot.external_http.get(klines_url) as kline_resp:
                        if kline_resp.status == 200:
                            klines_data = await kline_resp.json()

                    # Extract metrics
                    last_price = float(data.get("lastPrice", 0))
                    price_change = float(data.get("priceChange", 0))
                    pct_change = float(data.get("priceChangePercent", 0))
                    high_price = float(data.get("highPrice", 0))
                    low_price = float(data.get("lowPrice", 0))
                    quote_volume = float(data.get("quoteVolume", 0)) # USDT Volume

                    # Determine embed properties based on 24h change
                    if pct_change > 0:
                        color = 0x2ecc71  # Green (Up)
                        change_emoji = "📈"
                        sign = "+"
                    elif pct_change < 0:
                        color = 0xe74c3c  # Red (Down)
                        change_emoji = "📉"
                        sign = ""
                    else:
                        color = 0x95a5a6  # Gray (No change)
                        change_emoji = "➖"
                        sign = ""

                    change_str = f"{sign}{price_change:,.4f} ({sign}{pct_change:,.2f}%)"

                    # Format prices nicely (handle cheap tokens like SHIB differently)
                    def format_price(p):
                        if p >= 1.0:
                            return f"${p:,.2f}"
                        elif p > 0:
                            return f"${p:,.6f}"
                        return "$0.00"

                    # Build simplified Discord Embed
                    embed = discord.Embed(
                        title=f"🪙 {symbol}/USDT",
                        description=(
                            f"💵 **ราคาล่าสุด:** `{format_price(last_price)}`\n"
                            f"{change_emoji} **การเปลี่ยนแปลง 24 ชม.:** `{change_str}`\n"
                            f"💸 **ปริมาณซื้อขาย 24 ชม.:** `{format_large_number(quote_volume)}`\n\n"
                            f"*📉 กราฟราคาย้อนหลัง 30 วัน*"
                        ),
                        color=color,
                        timestamp=datetime.utcnow()
                    )
                    set_embed_author(embed, self.bot, "Crypto • อัปเดตล่าสุด")
                    embed.add_field(
                        name="📡 ข้อมูลจาก",
                        value="Binance API • คู่เทรด `USDT`",
                        inline=False,
                    )

                    # Parse historical data for chart
                    dates = []
                    prices = []
                    if klines_data:
                        for k in klines_data:
                            # k[0] is open time in milliseconds
                            dt = datetime.fromtimestamp(k[0] / 1000)
                            close_p = float(k[4])
                            dates.append(dt)
                            prices.append(close_p)

                    chart_file = None
                    if dates and prices and len(prices) > 1:
                        color_theme = "green" if pct_change >= 0 else "red"
                        chart_buf = generate_price_chart(
                            dates=dates,
                            prices=prices,
                            label=f"{symbol}/USDT",
                            color_theme=color_theme,
                            currency_symbol="$"
                        )
                        chart_file = discord.File(chart_buf, filename="crypto_chart.png")
                        embed.set_image(url="attachment://crypto_chart.png")

                    if chart_file:
                        await interaction.followup.send(embed=embed, file=chart_file)
                    else:
                        await interaction.followup.send(embed=embed)
                elif response.status == 400:
                    embed = make_embed(
                        self.bot,
                        "Crypto",
                        title="🔎 ยังไม่เจอเหรียญนี้",
                        description=f"ผมหาเหรียญ **{symbol}** หรือคู่เทรด USDT บน Binance ไม่เจอ\n"
                                    f"*ลองเช็กตัวย่ออีกครั้ง เช่น BTC, ETH, SOL หรือ DOGE*",
                        color=EmbedColor.WARNING,
                    )
                    await interaction.followup.send(embed=embed)
                else:
                    embed = make_embed(
                        self.bot,
                        "Crypto",
                        title="😅 ราคายังมาไม่ถึง",
                        description=f"Binance ตอบกลับด้วยรหัส `{response.status}` รอสักครู่แล้วลองใหม่อีกทีนะ",
                        color=EmbedColor.ERROR,
                    )
                    await interaction.followup.send(embed=embed)

        except Exception:
            embed = make_embed(
                self.bot,
                "Crypto",
                title="😅 ราคายังมาไม่ถึง",
                description="แหล่งข้อมูลเงียบไปนิดนึง รอสักครู่แล้วลองให้ผมเช็กใหม่อีกทีนะ",
                color=EmbedColor.ERROR,
            )
            await interaction.followup.send(embed=embed)

    @crypto.autocomplete('symbol')
    async def crypto_autocomplete(self, interaction: discord.Interaction, current: str):
        popular_cryptos = [
            ("Bitcoin (BTC)", "BTC"),
            ("Ethereum (ETH)", "ETH"),
            ("Solana (SOL)", "SOL"),
            ("Binance Coin (BNB)", "BNB"),
            ("Ripple (XRP)", "XRP"),
            ("Cardano (ADA)", "ADA"),
            ("Dogecoin (DOGE)", "DOGE"),
            ("Shiba Inu (SHIB)", "SHIB"),
            ("Avalanche (AVAX)", "AVAX"),
            ("Chainlink (LINK)", "LINK"),
            ("Polkadot (DOT)", "DOT"),
            ("Polygon (MATIC)", "MATIC")
        ]
        return [
            app_commands.Choice(name=name, value=value)
            for name, value in popular_cryptos
            if current.lower() in name.lower() or current.lower() in value.lower()
        ][:25]

async def setup(bot):
    await bot.add_cog(CryptoCog(bot))
