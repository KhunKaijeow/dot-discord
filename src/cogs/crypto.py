"""Cryptocurrency slash commands."""

import discord
from discord.ext import commands
from discord import app_commands
import aiohttp

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

class CryptoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="crypto", description="ค้นหารายละเอียดราคาเหรียญคริปโตตามเวลาจริง")
    @app_commands.describe(symbol="ชื่อย่อเหรียญคริปโต เช่น BTC, ETH, SOL, DOGE")
    async def crypto(self, interaction: discord.Interaction, symbol: str = "BTC"):
        # Format the symbol
        symbol = symbol.strip().upper()
        
        await interaction.response.defer(thinking=True)

        # Binance ticker endpoint
        url = f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}USDT"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        
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

                        # Build beautiful Discord Embed
                        embed = discord.Embed(
                            description=f"🏛️ **กระดานเทรด:** `Binance` | 🪙 **คู่เหรียญ:** `{symbol}/USDT`",
                            color=color
                        )
                        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
                        embed.set_author(name=f"เช็กราคาคริปโตให้แล้ว • {symbol}/USDT", icon_url=avatar_url)
                        
                        embed.add_field(name="💵 ราคาปัจจุบัน", value=f"`{format_price(last_price)}`", inline=True)
                        embed.add_field(name=f"{change_emoji} การเปลี่ยนแปลง 24 ชม.", value=f"`{change_str}`", inline=True)
                        embed.add_field(name="💸 ปริมาณซื้อขาย 24 ชม.", value=f"`{format_large_number(quote_volume)}`", inline=True)
                        
                        embed.add_field(name="📈 ราคาสูงสุด 24 ชม.", value=f"`{format_price(high_price)}`", inline=True)
                        embed.add_field(name="📉 ราคาต่ำสุด 24 ชม.", value=f"`{format_price(low_price)}`", inline=True)
                        embed.add_field(name="🔄 อัปเดตราคาแบบ", value="`เรียลไทม์`", inline=True)
                        
                        embed.set_footer(text="ข้อมูลล่าสุดจาก Binance", icon_url=avatar_url)

                        await interaction.followup.send(embed=embed)
                    elif response.status == 400:
                        embed = discord.Embed(
                            title="🔎 ยังไม่เจอเหรียญนี้",
                            description=f"ผมหาเหรียญ **{symbol}** หรือคู่เทรด USDT บน Binance ไม่เจอครับ\n"
                                        f"*ลองเช็กตัวย่ออีกครั้ง เช่น BTC, ETH, SOL หรือ DOGE*",
                            color=0xe74c3c
                        )
                        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
                        embed.set_footer(text="Javis Crypto • ลองค้นหาเหรียญอื่นได้นะ", icon_url=avatar_url)
                        await interaction.followup.send(embed=embed)
                    else:
                        embed = discord.Embed(
                            title="😅 เช็กราคาให้ไม่ได้ในตอนนี้",
                            description=f"Binance ตอบกลับไม่สำเร็จ (รหัส {response.status}) ลองใหม่อีกครั้งในอีกสักครู่นะครับ",
                            color=0xe74c3c
                        )
                        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
                        embed.set_footer(text="Javis Crypto • เดี๋ยวลองใหม่กันนะ", icon_url=avatar_url)
                        await interaction.followup.send(embed=embed)

        except Exception as e:
            embed = discord.Embed(
                title="😅 เช็กราคาให้ไม่ได้ในตอนนี้",
                description="ขอโทษนะ ตอนนี้ผมติดต่อแหล่งข้อมูลราคาไม่ได้ ลองใหม่อีกครั้งในอีกสักครู่ครับ",
                color=0xe74c3c
            )
            avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
            embed.set_footer(text="Javis Crypto • เดี๋ยวลองใหม่กันนะ", icon_url=avatar_url)
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
