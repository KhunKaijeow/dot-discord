# Javis Discord Bot

บอท Discord แบบอเนกประสงค์ที่ใช้ Slash Commands รองรับการสนทนาด้วย Gemini AI,
เล่นเพลงใน Voice Channel, ดูข้อมูลหุ้น/คริปโต/สภาพอากาศ, สรุปข่าว และเครื่องมือทั่วไป
โดยพัฒนาด้วย Python และ `discord.py`

## ฟีเจอร์

- สนทนาต่อเนื่องกับ Gemini AI แยกตามช่อง
- เล่นเพลงจากชื่อเพลง, YouTube และลิงก์ Spotify พร้อมระบบคิว
- ตรวจสอบราคาหุ้นและคริปโต
- ดูสภาพอากาศและสถานะเซิร์ฟเวอร์ Valorant
- ค้นหาเนื้อเพลง สรุปข่าว แปลภาษา และสร้างภาพ
- ตั้งเวลาแจ้งเตือนสูงสุด 24 ชั่วโมง

## Slash Commands

| คำสั่ง | รายละเอียด |
| --- | --- |
| `/ask` | สนทนาหรือถามคำถามกับ Gemini AI |
| `/reset-chat` | ล้างประวัติการสนทนาของช่องปัจจุบัน |
| `/play` | เล่นเพลงจากชื่อ, YouTube หรือ Spotify |
| `/pause` | หยุดเพลงชั่วคราว |
| `/resume` | เล่นเพลงต่อ |
| `/skip` | ข้ามเพลงปัจจุบัน |
| `/queue` | แสดงคิวเพลง |
| `/stop` | หยุดเพลง ล้างคิว และออกจาก Voice Channel |
| `/lyrics` | ค้นหาเนื้อเพลงหรือใช้เพลงที่กำลังเล่น |
| `/stock` | ดูข้อมูลหุ้นจากสัญลักษณ์ เช่น `AAPL` หรือ `PTT.BK` |
| `/stock-popular` | แสดงตัวอย่างหุ้นยอดนิยม |
| `/crypto` | ดูราคาคริปโต เช่น `BTC`, `ETH` หรือ `SOL` |
| `/weather` | ดูสภาพอากาศตามชื่อเมือง |
| `/valorant-status` | ตรวจสอบสถานะเซิร์ฟเวอร์ Valorant |
| `/news` | ดึงข่าวล่าสุดและให้ Gemini ช่วยสรุป |
| `/translate` | แปลข้อความเป็นภาษาที่เลือก |
| `/draw` | สร้างภาพจากข้อความ |
| `/remind` | ตั้งเวลาแจ้งเตือน เช่น `30s`, `10m` หรือ `2h` |

## สิ่งที่ต้องมี

- Python 3.12 หรือใหม่กว่า
- FFmpeg และ Opus สำหรับระบบ Voice
- Discord Bot Token
- Gemini API Key
- Valorant API Key (ไม่บังคับ)

## ติดตั้ง

โคลน repository และสร้าง virtual environment:

```bash
git clone https://github.com/KhunKaijeow/dot-discord.git
cd dot-discord
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

สำหรับ Windows ให้เปิด virtual environment ด้วย:

```powershell
.venv\Scripts\Activate.ps1
```

ติดตั้ง FFmpeg และ Opus บน macOS:

```bash
brew install ffmpeg opus
```

บน Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg libopus0
```

## ตั้งค่าตัวแปรแวดล้อม

คัดลอกไฟล์ตัวอย่าง:

```bash
cp .env.example .env
```

จากนั้นใส่ค่าจริงใน `.env`:

```dotenv
DISCORD_TOKEN=your_discord_bot_token
GEMINI_API_KEY=your_gemini_api_key
VALORANT_API_KEY=your_valorant_api_key
```

| ตัวแปร | จำเป็น | แหล่งที่มา |
| --- | --- | --- |
| `DISCORD_TOKEN` | ใช่ | [Discord Developer Portal](https://discord.com/developers/applications) |
| `GEMINI_API_KEY` | ใช่ | [Google AI Studio](https://aistudio.google.com/) |
| `VALORANT_API_KEY` | ไม่ | [HenrikDev Dashboard](https://api.henrikdev.xyz/dashboard/) |

ไฟล์ `.env` ถูก ignore ไว้แล้ว ห้าม commit token หรือ API key ขึ้น repository

## ตั้งค่า Discord Application

1. สร้าง Application และ Bot ที่ Discord Developer Portal
2. ไปที่ **OAuth2 → URL Generator**
3. เลือก scopes `bot` และ `applications.commands`
4. เลือก permissions ที่จำเป็น เช่น Send Messages, Embed Links, Connect และ Speak
5. เปิด URL ที่สร้างขึ้นเพื่อเชิญบอทเข้าเซิร์ฟเวอร์

โปรเจกต์ใช้ Slash Commands เป็นหลัก จึงไม่จำเป็นต้องเปิด Message Content Intent

## เริ่มใช้งาน

```bash
python main.py
```

เมื่อเชื่อมต่อสำเร็จจะเห็นข้อความลักษณะนี้:

```text
Synced 18 command(s)
Logged in as ...
```

## Deploy บน Railway

1. สร้างโปรเจกต์ใหม่ใน Railway และเลือก **Deploy from GitHub repo**
2. เลือก repository นี้
3. เพิ่ม `DISCORD_TOKEN`, `GEMINI_API_KEY` และ `VALORANT_API_KEY` ในหน้า
   **Variables**
4. กำหนด Start Command เป็น:

   ```text
   python main.py
   ```

5. Deploy โดยไม่ต้องสร้าง Public Domain หรือกำหนด `PORT`
6. ใช้เพียง 1 replica เพื่อไม่ให้บอทหลาย process ใช้ token เดียวกันพร้อมกัน

บอทเป็น worker ที่เชื่อมต่อ Discord Gateway โดยตรง จึงไม่ต้องมี HTTP health check

## โครงสร้างโปรเจกต์

```text
.
├── main.py              # Entry point
├── requirements.txt     # Python dependencies
├── .env.example         # ตัวอย่างตัวแปรแวดล้อม
└── src/
    ├── bot.py           # Bot และคำสั่ง Gemini
    ├── config.py        # Environment configuration
    ├── gemini.py        # Gemini service
    ├── music.py         # Music player
    ├── stock.py         # Stock information
    ├── crypto.py        # Cryptocurrency information
    ├── weather.py       # Weather information
    └── ...              # Feature cogs อื่น ๆ
```

## แก้ไขปัญหาเบื้องต้น

- `Missing required environment variables` — ตรวจค่า `DISCORD_TOKEN` และ
  `GEMINI_API_KEY`
- `LoginFailure: Improper token` — สร้างหรือคัดลอก Discord Bot Token ใหม่
- Slash Commands ไม่แสดง — ตรวจ scope `applications.commands` และรอให้ Discord sync
- เล่นเพลงไม่ได้ — ตรวจว่า FFmpeg/Opus ติดตั้งแล้วและบอทมีสิทธิ์ Connect/Speak
- คำสั่ง Valorant ใช้ไม่ได้ — ตรวจ `VALORANT_API_KEY`; ฟีเจอร์อื่นยังใช้งานได้ตามปกติ

## ความปลอดภัย

- อย่าเผยแพร่ไฟล์ `.env`, token หรือ API key
- หาก secret เคยถูก commit หรือแชร์ ให้ rotate ค่านั้นทันที
- จำกัดสิทธิ์ของ Discord bot เท่าที่จำเป็น
