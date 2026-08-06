# สถาปัตยกรรมโปรเจกต์

เอกสารนี้อธิบายโครงสร้าง runtime, ขอบเขตของโมดูล และแนวทางเพิ่มฟีเจอร์ให้
Javis Discord Bot โดยอ้างอิงจากโค้ดปัจจุบัน

## ภาพรวมการทำงาน

```text
main.py
  └── src.bot.GeminiBot
        ├── src.config
        ├── src.cogs.*
        │     └── src.services.*
        └── src.services.database.Database
              └── data/javis.db
```

1. `main.py` ตรวจ environment variables ที่จำเป็น แล้วเริ่ม Discord client
2. `src/bot.py` สร้าง bot, database และ AI service ก่อนโหลด extensions ใน
   `COG_EXTENSIONS`
3. แต่ละ Cog ลงทะเบียน Slash Commands หรือ background task ของตัวเอง
4. Cog เรียก service สำหรับ API ภายนอก, การแปลงข้อมูล และ persistence
5. Discord sync application commands เมื่อ event `on_ready` ทำงาน

ระบบใช้ Discord Gateway โดยตรงและไม่มี HTTP server หรือ health-check endpoint

## ขอบเขตแต่ละส่วน

| ส่วน | หน้าที่ |
| --- | --- |
| `main.py` | Entry point และ startup validation |
| `src/config.py` | อ่าน environment variables ผ่าน `python-dotenv` |
| `src/bot.py` | ประกอบ bot, โหลด extensions, `/ask`, `/reset-chat` และ error handler กลาง |
| `src/cogs/` | Discord UI, Slash Commands และ background workers แยกตามฟีเจอร์ |
| `src/services/` | API clients, market data, chart, translation และ SQLite repository |
| `tests/` | Unit tests สำหรับ persistence, validation, permission และ rate limit |
| `data/` | Runtime state ที่ไม่ควร commit เช่น SQLite และ dashboard state |

Dependency ควรไหลจาก `bot` ไป `cogs`/`services` และจาก `cogs` ไป `services`
หรือ `config` เท่านั้น หลีกเลี่ยงการ import `bot` กลับจากโมดูลย่อยเพื่อป้องกัน
circular import

## โมดูลฟีเจอร์

| กลุ่ม | Cog/Service หลัก | รายละเอียด |
| --- | --- | --- |
| AI chat/tools | `bot.py`, `cogs/ai_tools.py`, `services/gemini.py` | Typhoon AI, ประวัติแชทแยกตาม channel และ Context Menu 3 รายการ |
| Music | `cogs/music.py` | yt-dlp, FFmpeg/Opus, Spotify track/playlist resolution, queue และ Saved Playlists |
| Market | `cogs/stock.py`, `crypto.py`, `gold.py`, `price_alerts.py` | Yahoo Finance, Binance, กราฟ 30 วัน และ Price Alerts |
| Content | `news.py`, `lyrics.py`, `translator.py`, `draw.py` | Google News RSS, LRCLIB, Google Translate และ Together AI FLUX.1 |
| Utility | `weather.py`, `valorant.py`, `horoscope.py` | wttr.in, HenrikDev, Prokerala และ Wikimedia |
| Automation | `reminder.py`, `dashboard.py`, `morning_digest.py`, `x_notifier.py`, `deals_notifier.py` | งานตามเวลาและการแจ้งเตือนอัตโนมัติ |
| Administration | `admin.py`, `health.py` | การตั้งค่าระดับ Server และข้อมูลสุขภาพของ bot |

`services/gemini.py` คงชื่อเดิมไว้เพื่อ compatibility แต่ implementation ปัจจุบัน
เรียก OpenTyphoon endpoint ด้วยโมเดล `typhoon-v2.5-30b-a3b-instruct`

## Persistence และ runtime state

`src/services/database.py` เป็น persistence boundary สำหรับ SQLite ใช้
parameterized queries, เปิด foreign keys และ WAL mode และป้องกันการเข้าถึงพร้อมกัน
ด้วย `threading.RLock`

ข้อมูลใน `data/javis.db` ได้แก่:

- การตั้งค่า Morning Digest และห้อง Price Alert ต่อ Server
- Reminder แบบครั้งเดียวและแบบทำซ้ำ
- Price Alert ของผู้ใช้
- Saved Playlists และลำดับเพลง (ลบ tracks อัตโนมัติด้วย `ON DELETE CASCADE`)

Cog ควรเรียก synchronous repository methods ด้วย `asyncio.to_thread` เพื่อไม่ block
Discord Gateway ห้ามประกอบ SQL จาก input ของผู้ใช้ และต้องเพิ่มชื่อ column ลง
allowlist ใน `Database.update_settings` ก่อนรองรับการตั้งค่าใหม่

ข้อมูลต่อไปนี้ไม่ได้อยู่ใน SQLite:

- ประวัติแชท Typhoon และคิวเพลง เก็บในหน่วยความจำและหายเมื่อ restart
- Dashboard เก็บ channel/message ID ใน `data/dashboard.json`
- สถานะ notifier บางส่วนเก็บในไฟล์ JSON ใต้ `data/`

การ deploy ต้อง mount persistent volume ที่ `data/` หากต้องการเก็บข้อมูลข้าม
redeploy และควรใช้เพียง 1 process/replica เพราะ runtime state บางส่วนไม่ได้แชร์กัน

## Background workers

| Worker | รอบทำงาน | Persistence/แหล่งข้อมูล |
| --- | --- | --- |
| Reminder delivery | ทุก 15 วินาที | SQLite |
| Price Alerts | ทุก 5 นาที | SQLite, Yahoo Finance/Binance |
| Morning Digest | ทุก 1 นาที | SQLite และ timezone ของแต่ละ Server |
| sheapgamer notifier | ทุก 5 นาที | rss.app feed |
| Game deals | ทุก 1 ชั่วโมง | GamerPower API |
| Daily Dashboard | 08:00 น. `Asia/Bangkok` | Yahoo Finance และ Google News RSS |

workers เริ่มเมื่อ Cog ถูกโหลดและรอ `bot.wait_until_ready()` ก่อนทำงานกับ Discord

## ความปลอดภัยและสิทธิ์

- Bot ปิด mentions โดยค่าเริ่มต้นด้วย `AllowedMentions.none()` และเปิด user mention
  เฉพาะข้อความแจ้งเตือนที่จำเป็น
- `/ask` และ `/draw` มี per-user cooldown; AI Context Menu จำกัด 3 ครั้งต่อนาที
- `/x-setup`, `/deals-setup`, `/dashboard-setup` ต้องมี `Manage Channels`
- `/digest setup`, `/digest disable`, `/settings` ต้องมี `Manage Server`
- Reminder, Price Alert และ Playlist ตรวจ ownership ตอนอ่านหรือลบข้อมูล
- `.env`, SQLite และ runtime JSON ถูก ignore และต้องไม่ commit ขึ้น repository

## เพิ่ม Slash Command ใหม่

1. สร้างโมดูลใน `src/cogs/` และประกาศคลาสที่สืบทอดจาก `commands.Cog`
2. เพิ่ม `async def setup(bot)` ซึ่งเรียก `bot.add_cog(...)`
3. เพิ่มชื่อโมดูลลงใน `COG_EXTENSIONS` ที่ `src/bot.py`
4. แยก API/client หรือ business logic ที่นำกลับมาใช้ได้ไว้ใน `src/services/`
5. ใช้ `asyncio.to_thread` กับ SDK หรือ repository แบบ synchronous
6. validate ความยาว รูปแบบ ช่วงค่า และ permission ของ input ทุกจุด
7. เพิ่ม test ใน `tests/` แล้วรัน:

   ```bash
   python -m compileall -q main.py src
   python -m unittest discover -s tests -v
   ```

หาก command เรียกเครือข่าย ให้กำหนด timeout, จัดการ response ที่ไม่สำเร็จ และส่ง
ข้อความผิดพลาดแบบไม่เปิดเผย token, payload ภายใน หรือ stack trace ต่อผู้ใช้

## หมายเหตุเรื่อง environment variables

AI runtime ใช้ `TYPHOON_API_KEY` แต่ `main.py` ปัจจุบันยังตรวจ
`GEMINI_API_KEY` จาก startup guard เดิมด้วย ดังนั้น environment ต้องกำหนดทั้งสองค่า
จนกว่าจะเปลี่ยน validation ใน entry point ดูรายการทั้งหมดและแหล่งที่มาของคีย์ได้ที่
[README](../README.md#ตั้งค่าตัวแปรแวดล้อม)
