import discord
from discord.ext import commands
from discord import app_commands
import yfinance as yf
import asyncio
from datetime import datetime
from ..services.chart_generator import generate_price_chart
from ..ui import EmbedColor, make_embed, set_embed_author

def fetch_stock_data(symbol: str):
    """Sync function to fetch stock info and 1-month historical data from yfinance."""
    ticker = yf.Ticker(symbol)
    info = ticker.info
    hist = ticker.history(period="1mo")
    return info, hist

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
            info, hist = await asyncio.to_thread(fetch_stock_data, symbol)

            # Check if stock data was successfully retrieved
            current_price = info.get("currentPrice") or info.get("regularMarketPrice")
            if current_price is None and not hist.empty:
                current_price = hist['Close'].iloc[-1]

            if not info or current_price is None:
                embed = make_embed(
                    self.bot,
                    "Stocks",
                    title="🔎 ยังไม่เจอหุ้นตัวนี้",
                    description=f"ผมหาข้อมูลหุ้น **{symbol}** ไม่เจอ ลองเช็กชื่อย่ออีกทีนะ\n"
                                f"*ตัวอย่าง: AAPL (หุ้นนอก), PTT.BK (หุ้นไทยต้องลงท้ายด้วย .BK)*",
                    color=EmbedColor.WARNING,
                )
                await interaction.followup.send(embed=embed)
                return

            # Extract metrics
            company_name = info.get("longName") or info.get("shortName") or symbol
            currency = info.get("currency", "USD")
            currency_symbol = "$" if currency == "USD" else (currency + " ")
            
            prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
            if prev_close is None and len(hist) > 1:
                prev_close = hist['Close'].iloc[-2]

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

            # Build simplified Discord Embed
            embed = discord.Embed(
                title=f"📈 {symbol} ({company_name})",
                description=(
                    f"💵 **ราคาล่าสุด:** `{currency_symbol}{current_price:,.2f}`\n"
                    f"📊 **การเปลี่ยนแปลงวันนี้:** `{change_str}`\n"
                    f"💼 **มูลค่าตลาด:** `{format_large_number(market_cap)}`\n\n"
                    f"*📉 กราฟราคาย้อนหลัง 30 วัน*"
                ),
                color=color,
                timestamp=datetime.utcnow()
            )
            set_embed_author(embed, self.bot, "Stocks • อัปเดตล่าสุด")
            embed.add_field(
                name="📡 ข้อมูลจาก",
                value=f"Yahoo Finance • `{exchange}`",
                inline=False,
            )

            chart_file = None
            if not hist.empty and len(hist) > 1:
                color_theme = "green" if change >= 0 else "red"
                chart_buf = generate_price_chart(
                    dates=hist.index,
                    prices=hist['Close'],
                    label=symbol,
                    color_theme=color_theme,
                    currency_symbol=currency_symbol
                )
                chart_file = discord.File(chart_buf, filename="stock_chart.png")
                embed.set_image(url="attachment://stock_chart.png")

            if chart_file:
                await interaction.followup.send(embed=embed, file=chart_file)
            else:
                await interaction.followup.send(embed=embed)

        except Exception:
            embed = make_embed(
                self.bot,
                "Stocks",
                title="😅 ราคาหุ้นยังมาไม่ถึง",
                description="แหล่งข้อมูลเงียบไปนิดนึง รอสักครู่แล้วลองให้ผมเช็กใหม่อีกทีนะ",
                color=EmbedColor.ERROR,
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
        embed = make_embed(
            self.bot,
            "Stocks",
            title="📊 หุ้นยอดนิยม",
            description="เจอตัวที่สนใจแล้วใช้ `/stock` เดี๋ยวผมเช็กราคาให้เลย",
            color=EmbedColor.INFO,
        )
        
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
        
        
        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(StockCog(bot))
