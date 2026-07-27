"""Stock market slash commands."""

import discord
from discord.ext import commands
from discord import app_commands
import yfinance as yf
import asyncio

def fetch_stock_info(symbol: str):
    """Sync function to fetch stock data from yfinance (runs in threadpool)."""
    ticker = yf.Ticker(symbol)
    return ticker.info

def format_large_number(val):
    """Format market cap or large numbers beautifully (e.g., Billions, Trillions)."""
    if val is None:
        return "N/A"
    try:
        val = float(val)
        if val >= 1_000_000_000_000:
            return f"{val / 1_000_000_000_000:.2f}T"
        elif val >= 1_000_000_000:
            return f"{val / 1_000_000_000:.2f}B"
        elif val >= 1_000_000:
            return f"{val / 1_000_000:.2f}M"
        return f"{val:,.2f}"
    except (ValueError, TypeError):
        return "N/A"

class StockCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="stock", description="ค้นหารายละเอียดราคาหุ้นรายวัน")
    @app_commands.describe(symbol="ชื่อย่อหุ้น เช่น AAPL (Apple), TSLA (Tesla), PTT.BK (ปตท.)")
    async def stock(self, interaction: discord.Interaction, symbol: str):
        # Format the symbol to uppercase for consistency
        symbol = symbol.strip().upper()
        
        await interaction.response.defer(thinking=True)

        try:
            # Fetch data asynchronously using a threadpool to prevent blocking the event loop
            info = await asyncio.to_thread(fetch_stock_info, symbol)

            # Check if stock data was successfully retrieved
            current_price = info.get("currentPrice") or info.get("regularMarketPrice")
            if not info or current_price is None:
                embed = discord.Embed(
                    title="❌ ไม่พบข้อมูลหุ้น",
                    description=f"ไม่พบข้อมูลของหุ้นสัญลักษณ์ **{symbol}** กรุณาตรวจสอบความถูกต้องของสัญลักษณ์หุ้นอีกครั้งครับ\n"
                                f"*ตัวอย่าง: AAPL (หุ้นนอก), PTT.BK (หุ้นไทยต้องลงท้ายด้วย .BK)*",
                    color=0xe74c3c
                )
                await interaction.followup.send(embed=embed)
                return

            # Extract metrics
            company_name = info.get("longName") or info.get("shortName") or symbol
            currency = info.get("currency", "USD")
            currency_symbol = "$" if currency == "USD" else (currency + " ")
            
            prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
            day_open = info.get("open") or info.get("regularMarketOpen")
            day_high = info.get("dayHigh") or info.get("regularMarketDayHigh")
            day_low = info.get("dayLow") or info.get("regularMarketDayLow")
            market_cap = info.get("marketCap")
            exchange = info.get("exchange", "Unknown")

            # Calculate daily change
            change = 0.0
            pct_change = 0.0
            change_str = "0.00 (0.00%)"
            color = 0x95a5a6  # Default Gray (no change)

            if prev_close is not None:
                change = current_price - prev_close
                pct_change = (change / prev_close) * 100
                sign = "+" if change > 0 else ""
                change_str = f"{sign}{change:,.2f} ({sign}{pct_change:,.2f}%)"
                if change > 0:
                    color = 0x2ecc71  # Vibrant Green (Up)
                elif change < 0:
                    color = 0xe74c3c  # Vibrant Red (Down)

            # Build beautiful Discord Embed
            embed = discord.Embed(
                description=f"🏛️ **ตลาดหลักทรัพย์:** `{exchange}` | 💸 **สกุลเงิน:** `{currency}`",
                color=color
            )
            avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
            embed.set_author(name=f"ข้อมูลดัชนีหุ้น • {symbol} ({company_name})", icon_url=avatar_url)
            
            # Format price showing sign changes
            price_display = f"`{currency_symbol}{current_price:,.2f}`"
            embed.add_field(name="💵 ราคาปัจจุบัน", value=price_display, inline=True)
            embed.add_field(name="📊 การเปลี่ยนแปลงวันนี้", value=f"`{change_str}`", inline=True)
            embed.add_field(name="🔙 ราคาปิดวันก่อนหน้า", value=f"`{currency_symbol}{prev_close:,.2f}`" if prev_close else "`N/A`", inline=True)
            
            embed.add_field(name="📈 ราคาสูงสุดวันนี้", value=f"`{currency_symbol}{day_high:,.2f}`" if day_high else "`N/A`", inline=True)
            embed.add_field(name="📉 ราคาต่ำสุดวันนี้", value=f"`{currency_symbol}{day_low:,.2f}`" if day_low else "`N/A`", inline=True)
            embed.add_field(name="⏱️ ราคาเปิดวันนี้", value=f"`{currency_symbol}{day_open:,.2f}`" if day_open else "`N/A`", inline=True)

            embed.add_field(name="💼 มูลค่าตลาดทั้งหมด (Market Cap)", value=f"`{format_large_number(market_cap)}`", inline=False)
            
            embed.set_footer(text="Data retrieved from Yahoo Finance", icon_url=avatar_url)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            embed = discord.Embed(
                title="❌ เกิดข้อผิดพลาด",
                description=f"ไม่สามารถตรวจสอบข้อมูลหุ้นได้ในขณะนี้: {e}",
                color=0xe74c3c
            )
            await interaction.followup.send(embed=embed)

    @stock.autocomplete('symbol')
    async def stock_autocomplete(self, interaction: discord.Interaction, current: str):
        popular_stocks = [
            ("Apple (AAPL)", "AAPL"),
            ("Tesla (TSLA)", "TSLA"),
            ("NVIDIA (NVDA)", "NVDA"),
            ("Microsoft (MSFT)", "MSFT"),
            ("Amazon (AMZN)", "AMZN"),
            ("Alphabet (GOOGL)", "GOOGL"),
            ("Meta Platforms (META)", "META"),
            ("Netflix (NFLX)", "NFLX"),
            ("AMD (AMD)", "AMD"),
            ("Intel (INTC)", "INTC"),
            ("S&P 500 ETF (SPY)", "SPY"),
            ("Nasdaq 100 ETF (QQQ)", "QQQ"),
            ("PTT (PTT.BK)", "PTT.BK"),
            ("CP ALL (CPALL.BK)", "CPALL.BK"),
            ("Airports of Thailand (AOT.BK)", "AOT.BK"),
            ("Kasikornbank (KBANK.BK)", "KBANK.BK"),
            ("SCB X (SCB.BK)", "SCB.BK"),
            ("Bangkok Dusit Medical (BDMS.BK)", "BDMS.BK"),
            ("GULF Energy (GULF.BK)", "GULF.BK"),
            ("Advanced Info Service (ADVANC.BK)", "ADVANC.BK")
        ]
        return [
            app_commands.Choice(name=name, value=value)
            for name, value in popular_stocks
            if current.lower() in name.lower() or current.lower() in value.lower()
        ][:25]

    @app_commands.command(name="stock-popular", description="แสดงรายชื่อหุ้นยอดฮิตแนะนำสำหรับการค้นหา")
    async def stock_popular(self, interaction: discord.Interaction):
        embed = discord.Embed(
            description="💡 **คุณสามารถนำชื่อย่อหุ้นเหล่านี้ไปค้นหาข้อมูลด้วยคำสั่ง `/stock [สัญลักษณ์]` ได้ทันทีครับ**",
            color=0x3498db  # Material Blue
        )
        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
        embed.set_author(name="รายชื่อหุ้นยอดฮิตแนะนำ • Popular Tickers", icon_url=avatar_url)
        
        us_giants = (
            "• `AAPL` - Apple Inc.\n"
            "• `TSLA` - Tesla Inc.\n"
            "• `NVDA` - NVIDIA Corp.\n"
            "• `MSFT` - Microsoft Corp.\n"
            "• `AMZN` - Amazon.com Inc.\n"
            "• `GOOGL` - Alphabet Inc. (Google)\n"
            "• `META` - Meta Platforms (Facebook)\n"
            "• `NFLX` - Netflix Inc.\n"
            "• `AMD` - Advanced Micro Devices\n"
            "• `INTC` - Intel Corp."
        )
        
        etfs = (
            "• `SPY` - S&P 500 ETF Trust\n"
            "• `QQQ` - Invesco QQQ Trust (Nasdaq 100)"
        )
        
        thai_giants = (
            "• `PTT.BK` - ปตท. (พลังงาน)\n"
            "• `CPALL.BK` - ซีพี ออลล์ (ค้าปลีก)\n"
            "• `AOT.BK` - ท่าอากาศยานไทย (ขนส่ง)\n"
            "• `KBANK.BK` - ธนาคารกสิกรไทย\n"
            "• `SCB.BK` - เอสซีบี เอกซ์ (การเงิน)\n"
            "• `BDMS.BK` - กรุงเทพดุสิตเวชการ (การแพทย์)\n"
            "• `GULF.BK` - กัลฟ์ เอ็นเนอร์จี (พลังงาน)\n"
            "• `ADVANC.BK` - แอดวานซ์ อินโฟร์ เซอร์วิส (สื่อสาร)"
        )
        
        embed.add_field(name="🇺🇸 หุ้นยักษ์ใหญ่ระดับโลก (US Giants)", value=us_giants, inline=False)
        embed.add_field(name="📈 กองทุนดัชนีสหรัฐฯ (Index ETFs)", value=etfs, inline=False)
        embed.add_field(name="🇹🇭 หุ้นยักษ์ใหญ่ไทย (SET Giants)", value=thai_giants, inline=False)
        
        embed.set_footer(text="ค้นหาข้อมูลหุ้นอื่นๆ เพิ่มเติมได้โดยการระบุชื่อย่อหุ้นตามตลาดจริง", icon_url=avatar_url)
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(StockCog(bot))
