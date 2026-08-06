import asyncio
from datetime import datetime
import logging

import discord
from discord import app_commands
from discord.ext import commands
import pandas as pd
import yfinance as yf

from ..services.chart_generator import generate_price_chart


logger = logging.getLogger("javis.gold")

def fetch_gold_data():
    """Sync function to fetch gold ticker information and historical data (1 month)."""
    ticker = yf.Ticker("GC=F")
    info = ticker.info
    hist = ticker.history(period="1mo")
    return info, hist

def calculate_rsi(series: pd.Series, period: int = 14) -> float:
    """Calculates Relative Strength Index (RSI) using Wilder's EMA technique."""
    if len(series) < period + 1:
        return 50.0  # Fallback neutral RSI
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    
    avg_gain = gain.ewm(alpha=1/period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period).mean()
    
    rs = avg_gain / (avg_loss + 1e-10)  # Avoid division by zero
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])

def calculate_ema(series: pd.Series, period: int) -> float:
    """Calculates Exponential Moving Average (EMA)."""
    if len(series) < period:
        return float(series.iloc[-1])
    ema = series.ewm(span=period, adjust=False).mean()
    return float(ema.iloc[-1])

class GoldCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="gold", description="เช็คราคาทองคำตลาดโลกแบบสด ๆ (Gold Futures: GC=F)")
    async def gold_price(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            info, hist = await asyncio.to_thread(fetch_gold_data)
            
            current_price = info.get("currentPrice") or info.get("regularMarketPrice")
            if current_price is None and not hist.empty:
                current_price = hist['Close'].iloc[-1]

            prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
            if prev_close is None and len(hist) > 1:
                prev_close = hist['Close'].iloc[-2]

            change_str = "0.00 (0.00%)"
            color = 0xf1c40f  # Default Gold/Yellow
            if current_price and prev_close:
                change = current_price - prev_close
                pct_change = (change / prev_close) * 100
                sign = "+" if change > 0 else ""
                change_str = f"{sign}{change:,.2f} ({sign}{pct_change:,.2f}%)"
                if change > 0:
                    color = 0xf1c40f  # Gold/Yellow (Up)
                elif change < 0:
                    color = 0xe74c3c  # Red (Down)

            embed = discord.Embed(
                title="🏆 ราคาทองคำตลาดโลก (Gold Futures)",
                description=(
                    f"💵 **ราคาปัจจุบัน:** `${current_price:,.2f} / ออนซ์`\n"
                    f"📊 **การเปลี่ยนแปลงวันนี้:** `{change_str}`\n\n"
                    f"*📉 กราฟราคาย้อนหลัง 30 วัน*"
                ),
                color=color,
                timestamp=datetime.utcnow()
            )
            embed.set_footer(text="ตลาด COMEX (GC=F) | แหล่งข้อมูล: Yahoo Finance")

            chart_file = None
            if not hist.empty and len(hist) > 1:
                chart_buf = generate_price_chart(
                    dates=hist.index,
                    prices=hist['Close'],
                    label="Gold Futures (GC=F)",
                    color_theme="gold",
                    currency_symbol="$"
                )
                chart_file = discord.File(chart_buf, filename="gold_chart.png")
                embed.set_image(url="attachment://gold_chart.png")

            if chart_file:
                await interaction.followup.send(embed=embed, file=chart_file)
            else:
                await interaction.followup.send(embed=embed)

        except Exception:
            logger.exception("Could not fetch gold price")
            await interaction.followup.send("😅 ขออภัย ไม่สามารถดึงราคาทองคำได้ในขณะนี้ ลองอีกครั้งในภายหลังครับ")

    @app_commands.command(name="gold-analysis", description="วิเคราะห์จุดซื้อขายทองทางเทคนิคอล (Pivot Points, RSI, EMA)")
    async def gold_analysis(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        try:
            info, hist = await asyncio.to_thread(fetch_gold_data)
            
            if hist.empty or len(hist) < 2:
                await interaction.followup.send("😅 ขออภัย ไม่พบข้อมูลสถิติราคาทองคำที่เพียงพอสำหรับการคำนวณ")
                return

            current_price = info.get("currentPrice") or info.get("regularMarketPrice") or hist['Close'].iloc[-1]

            # 1. Fetch Yesterday's values for Pivot Points calculation
            # If the market is open, the last row [-1] might be today's incomplete candle.
            # We use the previous complete candle [-2] for pivot levels to keep it stable.
            yest_idx = -2 if len(hist) > 2 else -1
            high_yest = float(hist['High'].iloc[yest_idx])
            low_yest = float(hist['Low'].iloc[yest_idx])
            close_yest = float(hist['Close'].iloc[yest_idx])

            # Standard Pivot Points calculation
            pp = (high_yest + low_yest + close_yest) / 3.0
            r1 = (2.0 * pp) - low_yest
            r2 = pp + (high_yest - low_yest)
            s1 = (2.0 * pp) - high_yest
            s2 = pp - (high_yest - low_yest)

            # 2. Indicators: RSI (14) & EMAs
            close_series = hist['Close']
            rsi = calculate_rsi(close_series, 14)
            ema10 = calculate_ema(close_series, 10)
            ema20 = calculate_ema(close_series, 20)

            # 3. Determine Short-term Trend
            if current_price > ema20 and ema10 > ema20:
                trend_status = "📈 **ขาขึ้นระยะสั้น (Bullish)**"
                trend_desc = "ราคาอยู่เหนือเส้นค่าเฉลี่ย EMA 10 และ 20 ทิศทางมีแรงซื้อหนุนอย่างชัดเจน"
                color = 0x2ecc71  # Green
            elif current_price < ema20 and ema10 < ema20:
                trend_status = "📉 **ขาลงระยะสั้น (Bearish)**"
                trend_desc = "ราคาอยู่ใต้เส้นค่าเฉลี่ย EMA 10 และ 20 มีแรงเทขายกดดันตลาดอย่างต่อเนื่อง"
                color = 0xe74c3c  # Red
            else:
                trend_status = "↔️ **แกว่งตัวออกข้าง (Sideways)**"
                trend_desc = "ราคาเคลื่อนไหวสลับขึ้นลงใกล้เคียงเส้น EMA ตลาดยังเลือกทิศทางไม่ชัดเจน"
                color = 0xf1c40f  # Gold/Yellow

            # 4. Determine Momentum from RSI
            if rsi >= 70:
                rsi_status = f"🔴 **Overbought ({rsi:.1f})**"
                rsi_desc = "มีการซื้อมากเกินไปชั่วคราว ระวังแรงเทขายทำกำไรระยะสั้นในโซนนี้"
            elif rsi <= 30:
                rsi_status = f"🟢 **Oversold ({rsi:.1f})**"
                rsi_desc = "มีการขายมากเกินไปชั่วคราว เป็นจุดที่ราคาค่อนข้างถูกและน่าสนใจทยอยสะสม"
            else:
                rsi_status = f"⚪ **Neutral ({rsi:.1f})**"
                rsi_desc = "โมเมนตัมตลาดอยู่ในเกณฑ์ปกติ ไม่มีกำลังซื้อหรือขายที่มากจนเกินไป"

            # 5. Volatility (High - Low of last complete day)
            day_range = high_yest - low_yest

            # Render Discord Embed
            embed = discord.Embed(
                title="📊 วิเคราะห์แนวรับ-แนวต้านทองคำทางเทคนิค",
                description=f"วิเคราะห์จากสถิติราคาทองคำตลาดโลก (COMEX: GC=F)\n**ราคาตลาดปัจจุบัน:** `${current_price:,.2f}`",
                color=color,
                timestamp=datetime.utcnow()
            )

            # Add fields
            embed.add_field(
                name="🧭 แนวโน้มและทิศทางตลาด (Trend)", 
                value=f"{trend_status}\n*{trend_desc}*", 
                inline=False
            )
            
            embed.add_field(
                name="⚡ พลังซื้อขายของตลาด (RSI-14)", 
                value=f"{rsi_status}\n*{rsi_desc}*", 
                inline=False
            )

            # Support & Resistance levels
            levels_text = (
                f"🔴 **แนวต้านที่ 2 (R2):** `${r2:,.2f}` *(แนวต้านสำคัญ/จุดขายทำกำไรใหญ่)*\n"
                f"🔴 **แนวต้านที่ 1 (R1):** `${r1:,.2f}` *(แนวต้านย่อย/จุดขายทำกำไรแรก)*\n"
                f"📍 **จุดสมดุลราคา (Pivot Point):** `${pp:,.2f}` *(แนวรับ-ต้านหลักประจำวัน)*\n"
                f"🟢 **แนวรับที่ 1 (S1):** `${s1:,.2f}` *(แนวรับย่อย/จุดเริ่มพิจารณาเข้าซื้อ)*\n"
                f"🟢 **แนวรับที่ 2 (S2):** `${s2:,.2f}` *(แนวรับสำคัญ/จุดทยอยสะสมหลัก)*"
            )
            embed.add_field(name="🎯 ระดับราคาสำคัญ (Pivot Levels)", value=levels_text, inline=False)

            # Volatility info
            extra_info = (
                f"• **Volatility (ระยะแกว่งเมื่อวาน):** `${day_range:,.2f}`\n"
                f"• **EMA 10:** `${ema10:,.2f}`\n"
                f"• **EMA 20:** `${ema20:,.2f}`"
            )
            embed.add_field(name="ℹ️ ข้อมูลเทคนิคอลเพิ่มเติม", value=extra_info, inline=False)

            await interaction.followup.send(embed=embed)

        except Exception:
            logger.exception("Could not calculate gold analysis")
            await interaction.followup.send("😅 เกิดข้อผิดพลาดในการคำนวณวิเคราะห์ราคาทองคำ ลองอีกครั้งภายหลังครับ")

async def setup(bot):
    await bot.add_cog(GoldCog(bot))
