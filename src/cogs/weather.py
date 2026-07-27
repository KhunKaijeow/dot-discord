"""Weather slash commands."""

import discord
from discord.ext import commands
from discord import app_commands
import aiohttp

def get_weather_emoji(code: str) -> str:
    """Map weather code from WorldWeatherOnline (used by wttr.in) to standard emojis."""
    code_map = {
        "113": "☀️",  # Sunny/Clear
        "116": "⛅",  # Partly Cloudy
        "119": "☁️",  # Cloudy
        "122": "☁️",  # Overcast
        "143": "🌫️", # Mist
        "176": "🌦️", # Patchy rain nearby
        "182": "🌨️", # Patchy snow nearby
        "185": "🌨️", # Patchy freezing drizzle nearby
        "200": "⛈️", # Thundery outbreaks nearby
        "227": "🌨️", # Blowing snow
        "230": "❄️",  # Blizzard
        "248": "🌫️", # Fog
        "260": "🌫️", # Freezing fog
        "263": "🌧️", # Patchy light drizzle
        "266": "🌧️", # Light drizzle
        "281": "🌧️", # Freezing drizzle
        "284": "🌧️", # Heavy freezing drizzle
        "293": "🌦️", # Patchy light rain
        "296": "🌧️", # Light rain
        "299": "🌧️", # Moderate rain at times
        "302": "🌧️", # Moderate rain
        "305": "🌧️", # Heavy rain at times
        "308": "🌧️", # Heavy rain
        "311": "🌧️", # Light freezing rain
        "314": "🌧️", # Moderate or heavy freezing rain
        "317": "🌧️", # Light sleet
        "320": "🌨️", # Moderate or heavy sleet
        "323": "🌨️", # Patchy light snow
        "326": "🌨️", # Light snow
        "329": "🌨️", # Patchy moderate snow
        "332": "🌨️", # Moderate snow
        "335": "🌨️", # Patchy heavy snow
        "338": "🌨️", # Heavy snow
        "350": "🌨️", # Ice pellets
        "353": "🌦️", # Light rain shower
        "356": "🌧️", # Moderate or heavy rain shower
        "359": "🌧️", # Torrential rain shower
        "362": "🌨️", # Light sleet showers
        "365": "🌨️", # Moderate or heavy sleet showers
        "368": "🌨️", # Light snow showers
        "371": "🌨️", # Moderate or heavy snow showers
        "374": "🌨️", # Light showery of ice pellets
        "377": "🌨️", # Moderate or heavy showers of ice pellets
        "386": "⛈️", # Patchy light rain with thunder
        "389": "⛈️", # Moderate or heavy rain with thunder
        "392": "⛈️", # Patchy light snow with thunder
        "395": "⛈️", # Moderate or heavy snow with thunder
    }
    return code_map.get(code, "🌡️")

class WeatherCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="weather", description="ตรวจสอบสภาพอากาศและพยากรณ์ประจำวัน")
    @app_commands.describe(location="ชื่อเมือง/พื้นที่ เช่น Bangkok, Chiang Mai, Tokyo, London")
    async def weather(self, interaction: discord.Interaction, location: str):
        await interaction.response.defer(thinking=True)
        
        # Clean query URL
        url = f"https://wttr.in/{location}?format=j1&lang=th"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json(content_type=None)
                        
                        # Extract current conditions
                        current = data.get("current_condition", [{}])[0]
                        temp_c = current.get("temp_C", "N/A")
                        feels_like_c = current.get("FeelsLikeC", "N/A")
                        humidity = current.get("humidity", "N/A")
                        wind_speed = current.get("windspeedKmph", "N/A")
                        wind_dir = current.get("winddir16Point", "N/A")
                        uv_index = current.get("uvIndex", "N/A")
                        weather_code = current.get("weatherCode", "113")
                        
                        # Get weather description in Thai (or fallback to English)
                        weather_desc = "ไม่ทราบข้อมูลสภาพอากาศ"
                        if current.get("lang_th"):
                            weather_desc = current["lang_th"][0].get("value")
                        elif current.get("weatherDesc"):
                            weather_desc = current["weatherDesc"][0].get("value")

                        # Extract area information
                        nearest_area = data.get("nearest_area", [{}])[0]
                        area_name = nearest_area.get("areaName", [{}])[0].get("value", location)
                        country = nearest_area.get("country", [{}])[0].get("value", "")
                        region_name = nearest_area.get("region", [{}])[0].get("value", "")
                        
                        location_display = f"{area_name}"
                        if region_name and region_name != area_name:
                            location_display += f", {region_name}"
                        if country:
                            location_display += f" ({country})"

                        # Extract daily forecast
                        forecast = data.get("weather", [{}])[0]
                        max_temp = forecast.get("maxtempC", "N/A")
                        min_temp = forecast.get("mintempC", "N/A")
                        
                        astronomy = forecast.get("astronomy", [{}])[0]
                        sunrise = astronomy.get("sunrise", "N/A")
                        sunset = astronomy.get("sunset", "N/A")

                        # Determine embed color based on temperature
                        embed_color = 0x2ecc71  # Default Green (Mild)
                        try:
                            t = float(temp_c)
                            if t >= 32:
                                embed_color = 0xe74c3c  # Red (Hot)
                            elif t >= 27:
                                embed_color = 0xe67e22  # Orange (Warm)
                            elif t < 20:
                                embed_color = 0x3498db  # Blue (Cool/Cold)
                        except (ValueError, TypeError):
                            pass

                        # Get emoji representation
                        weather_emoji = get_weather_emoji(weather_code)

                        # Build Discord Embed
                        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
                        embed = discord.Embed(
                            description=f"📍 **สถานที่:** `{location_display}`\n☁️ **ลักษณะสภาพอากาศ:** {weather_emoji} **{weather_desc.strip()}**",
                            color=embed_color
                        )
                        embed.set_author(name="เช็กอากาศให้แล้ว • Weather", icon_url=avatar_url)
                        
                        embed.add_field(name="🌡️ อุณหภูมิปัจจุบัน", value=f"`{temp_c}°C`\n*(รู้สึกเหมือน `{feels_like_c}°C`)*", inline=True)
                        embed.add_field(name="💧 ความชื้นอากาศ", value=f"`{humidity}%`", inline=True)
                        embed.add_field(name="💨 ความเร็วลม", value=f"`{wind_speed} km/h`\n*(ทิศทาง `{wind_dir}`)*", inline=True)

                        embed.add_field(name="📈 อุณหภูมิวันนี้", value=f"สูงสุด `{max_temp}°C`\nต่ำสุด `{min_temp}°C`", inline=True)
                        embed.add_field(name="☀️ ดัชนี UV", value=f"ระดับ `{uv_index}`", inline=True)
                        embed.add_field(name="🌅 พระอาทิตย์", value=f"ขึ้น `{sunrise}`\nตก `{sunset}`", inline=True)


                        await interaction.followup.send(embed=embed)
                    else:
                        embed = discord.Embed(
                            title="😅 เช็กอากาศให้ไม่ได้ในตอนนี้",
                            description=f"บริการพยากรณ์อากาศตอบกลับไม่สำเร็จ (รหัส {response.status}) ลองใหม่อีกครั้งในอีกสักครู่นะครับ",
                            color=0xe74c3c
                        )
                        avatar_url = self.bot.user.display_avatar.url if self.bot.user else None
                        await interaction.followup.send(embed=embed)

        except Exception as e:
            embed = discord.Embed(
                title="😅 เช็กอากาศให้ไม่ได้ในตอนนี้",
                description="ขอโทษนะ ตอนนี้ผมติดต่อบริการพยากรณ์อากาศไม่ได้ ลองใหม่อีกครั้งในอีกสักครู่ครับ",
                color=0xe74c3c
            )
            await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(WeatherCog(bot))
