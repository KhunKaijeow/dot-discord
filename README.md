# Javis Discord Bot

บอท Discord แบบอเนกประสงค์ที่ใช้ Slash Commands รองรับการสนทนาด้วย Typhoon AI,
เล่นเพลงใน Voice Channel, ดูข้อมูลหุ้น/คริปโต/ทองคำ/สภาพอากาศ, ติดตามข่าว
และตั้งระบบแจ้งเตือนอัตโนมัติ
โดยพัฒนาด้วย Python และ `discord.py`

## เอกสาร

- [สถาปัตยกรรมและแนวทางพัฒนา](docs/architecture.md)
- [รายการ Slash Commands](#slash-commands)
- [การติดตั้งและตั้งค่า](#ติดตั้ง)
- [การ Deploy บน Railway](#deploy-บน-railway)

## ฟีเจอร์

- สนทนาต่อเนื่องกับ Typhoon AI แยกตามช่อง
- เล่นเพลงจากชื่อเพลง, YouTube และลิงก์ Spotify (รองรับ YouTube/Spotify Playlist) พร้อมระบบคิวแยกต่อ Server สูงสุด 200 เพลง และระบบบันทึกเพลย์ลิสต์ส่วนตัว (Saved Playlists)
- ตรวจสอบราคาหุ้น คริปโต และทองคำ พร้อมภาพกราฟเทรนด์ราคา 30 วันและวิเคราะห์ทองคำทางเทคนิค
- ดูสภาพอากาศและสถานะเซิร์ฟเวอร์ Valorant
- ดึงหัวข้อข่าว แปลภาษา และสร้างภาพด้วย Together AI (FLUX.1)
- ตั้งเวลาแจ้งเตือนแบบถาวร รองรับวันเวลาจริงและรอบแจ้งเตือนซ้ำ
- ดูดวงรายวันครบ 12 ราศีจาก Prokerala พร้อมคำทำนายด้านความรัก งาน และสุขภาพ
- ดึงสีประจำวันตามธรรมเนียมไทยจาก Wikipedia พร้อมแสดงแหล่งที่มา
- แจ้งเตือนโพสต์ใหม่จาก sheapgamer และดีลเกมแจกฟรีอัตโนมัติ
- แสดง Daily Dashboard สำหรับข่าวและข้อมูลตลาด โดยอัปเดตทุกวันเวลา 08:00 น. เวลาไทย
- Price Alerts สำหรับหุ้น คริปโต และทองคำ พร้อมเงื่อนไขสูงกว่า/ต่ำกว่า
- Morning Digest แยกห้อง เวลา และ Timezone ได้ต่อ Server
- Reminder แบบถาวร รองรับวันเวลาจริงและการแจ้งเตือนซ้ำ
- AI Message Tools ผ่านเมนูคลิกขวา พร้อม rate limit และการป้องกัน prompt injection
- Admin Control Panel, Bot Health Status และระบบเพลงแบบ Volume/Loop/Shuffle

## Slash Commands

| คำสั่ง | รายละเอียด |
| --- | --- |
| `/ask` | สนทนาหรือถามคำถามกับ Typhoon AI |
| `/reset-chat` | ล้างประวัติการสนทนาของช่องปัจจุบัน |
| `/playlist-save` | บันทึกเพลงในคิวปัจจุบันเป็นเพลย์ลิสต์ส่วนตัว |
| `/playlist-load` | โหลดเพลงจากเพลย์ลิสต์ส่วนตัวเข้าสู่คิว |
| `/playlist-list` | แสดงรายชื่อเพลย์ลิสต์ส่วนตัวทั้งหมดของคุณ |
| `/playlist-delete` | ลบเพลย์ลิสต์ส่วนตัวของคุณ |
| `/play` | เล่นเพลงจากชื่อ, YouTube หรือ Spotify |
| `/pause` | หยุดเพลงชั่วคราว |
| `/resume` | เล่นเพลงต่อ |
| `/skip` | ข้ามเพลงปัจจุบัน |
| `/queue` | แสดงคิวเพลง |
| `/stop` | หยุดเพลง ล้างคิว และออกจาก Voice Channel |
| `/now-playing` | ดูเพลงปัจจุบัน ระดับเสียง และโหมด Loop |
| `/volume` | ปรับระดับเสียง 0–100% |
| `/loop` | เล่นซ้ำเพลงปัจจุบันหรือทั้งคิว |
| `/shuffle` | สุ่มเพลงที่รอในคิว |
| `/remove` | นำเพลงออกจากคิวตามลำดับ |
| `/clear-queue` | ล้างคิวโดยไม่หยุดเพลงปัจจุบัน |
| `/stock` | ดูข้อมูลหุ้นจากสัญลักษณ์ เช่น `AAPL` หรือ `PTT.BK` |
| `/stock-popular` | แสดงตัวอย่างหุ้นยอดนิยม |
| `/crypto` | ดูราคาคริปโต เช่น `BTC`, `ETH` หรือ `SOL` |
| `/gold` | ดูราคาทองคำตลาดโลกจาก Gold Futures (`GC=F`) |
| `/gold-analysis` | วิเคราะห์ทองคำด้วย Pivot Points, RSI และ EMA |
| `/weather` | ดูสภาพอากาศตามชื่อเมือง |
| `/valorant-status` | ตรวจสอบสถานะเซิร์ฟเวอร์ Valorant |
| `/news` | แสดงหัวข้อและลิงก์ข่าวล่าสุดจาก Google News RSS |
| `/translate` | แปลข้อความเป็นภาษาที่เลือก |
| `/draw` | สร้างภาพจากข้อความ |
| `/remind` | ตั้งเวลาแจ้งเตือน เช่น `30s`, `10m` หรือ `2h` |
| `/remind-at` | ตั้งเตือนด้วยวันเวลา `YYYY-MM-DD HH:MM` |
| `/remind-every` | ตั้งแจ้งเตือนซ้ำตั้งแต่ทุก 1 นาทีถึง 1 ปี |
| `/reminders` | ดู Reminder ที่ยังทำงานอยู่ |
| `/reminder-cancel` | ยกเลิก Reminder ด้วย ID |
| `/horoscope` | ดูดวงรายวันจาก Prokerala พร้อมสีประจำวันจากแหล่งอ้างอิง |
| `/lucky-shirt` | ดูสีประจำวันตามธรรมเนียมไทยจาก Wikipedia |
| `/x-setup` | ตั้งห้องรับแจ้งเตือนโพสต์ใหม่จาก sheapgamer |
| `/x-status` | ดูสถานะระบบแจ้งเตือน sheapgamer |
| `/x-disable` | ปิดระบบตามข่าว sheapgamer ของ Server |
| `/deals-setup` | ตั้งห้องรับแจ้งเตือนเกมแจกฟรี |
| `/deals-check` | แสดงดีลเกมแจกฟรีล่าสุดสูงสุด 3 รายการทันที |
| `/deals-disable` | ปิดแจ้งเตือนเกมแจกฟรีของ Server |
| `/dashboard-setup` | สร้าง Daily Dashboard ในห้องที่เลือก |
| `/dashboard-update` | สั่งอัปเดตข้อมูลบน Dashboard ทันที |
| `/dashboard-disable` | ปิด Daily Dashboard ของ Server โดยเก็บข้อความเดิมไว้ |
| `/my-data` | ดูจำนวนข้อมูลส่วนตัวที่บอทบันทึกไว้ |
| `/my-data-delete` | ลบ Reminder, Price Alert และ Saved Playlist ของผู้เรียก |
| `/price-alert add` | เพิ่มเงื่อนไขแจ้งเตือนราคาหุ้น คริปโต หรือทอง |
| `/price-alert list` | ดู Price Alert ของผู้ใช้ |
| `/price-alert remove` | ลบ Price Alert ด้วย ID |
| `/digest setup` | ตั้งห้อง เวลา Timezone และเมืองสำหรับ Morning Digest |
| `/digest preview` | ดูตัวอย่าง Morning Digest |
| `/digest status` | ดูสถานะ Morning Digest |
| `/digest disable` | ปิด Morning Digest |
| `/settings` | เปิด Admin Control Panel แบบ Interactive |
| `/setup-check` | ตรวจ permissions, config, database และ runtime ของบอท |
| `/bot-status` | ดู latency, uptime, runtime และจำนวนงานที่บันทึกไว้ |

เมนู **Apps** เมื่อคลิกขวาข้อความมี `AI: สรุปข้อความ`, `AI: แปลเป็นไทย`
และ `AI: อธิบายข้อความ` ผลลัพธ์จะแสดงแบบ Ephemeral เฉพาะผู้เรียกใช้งาน

คำสั่ง `/x-setup`, `/deals-setup` และ `/dashboard-setup` ต้องใช้สิทธิ์
**Manage Channels** ส่วน `/digest setup`, `/digest disable` และ `/settings` ต้องใช้สิทธิ์
**Manage Server** คำสั่งที่เหลือเปิดให้สมาชิกใช้งานตามสิทธิ์ของ Discord Server

## งานอัตโนมัติ

| ระบบ | รอบการทำงาน | แหล่งข้อมูล |
| --- | --- | --- |
| แจ้งเตือน sheapgamer | ตรวจโพสต์ใหม่ทุก 5 นาที | RSS feed จาก rss.app |
| แจ้งเตือนเกมแจกฟรี | ตรวจดีลใหม่ทุก 1 ชั่วโมง | GamerPower API |
| Daily Dashboard | อัปเดตทุกวันเวลา 08:00 น. (`Asia/Bangkok`) | Yahoo Finance และ Google News RSS |
| Persistent Reminder | ตรวจรายการที่ครบเวลาทุก 15 วินาที | SQLite |
| Price Alerts | ตรวจราคาใหม่ทุก 5 นาที | Yahoo Finance และ Binance |
| Morning Digest | ตรวจตารางเวลาของแต่ละ Server ทุก 1 นาที | SQLite, Yahoo Finance และ Google News |

หลังใช้ `/dashboard-setup` บอทจะสร้าง Dashboard ครั้งแรกทันที และแก้ไขข้อความเดิม
ตามตารางข้างต้น หากต้องการข้อมูลล่าสุดก่อนถึงรอบถัดไปให้ใช้ `/dashboard-update`
บอทต้องออนไลน์ในเวลาที่กำหนดจึงจะทำงานตามรอบได้

Reminder, Price Alert, Morning Digest, Saved Playlists, Dashboard และการตั้งค่าระบบ
แจ้งเตือนบันทึกใน `data/javis.db` แบบแยกตาม Server จึงไม่หายเมื่อบอทรีสตาร์ต
ส่วนประวัติแชทและคิวเพลงปกติยังเก็บในหน่วยความจำ

เมื่อเริ่มบอท ระบบจะอัปเกรด SQLite schema ตามลำดับเวอร์ชันให้อัตโนมัติและบันทึก
ประวัติไว้ใน `schema_migrations` โดย migration ที่ล้มเหลวจะถูก rollback ทั้งเวอร์ชัน
แนะนำให้สำรอง `data/javis.db` ก่อน deploy รุ่นที่มีการเปลี่ยน schema

การเพิ่ม YouTube/Spotify Playlist และ Saved Playlist เข้าคิวเป็นแบบ atomic: หาก
พื้นที่คิวไม่พอ ระบบจะไม่เพิ่มเพลงเพียงบางส่วนและจะแจ้งจำนวนช่องว่างที่เหลือ

## สิ่งที่ต้องมี

- Python 3.12 หรือใหม่กว่า
- FFmpeg และ Opus สำหรับระบบ Voice
- Deno 2.3+ หรือ Node.js 22+ สำหรับให้ yt-dlp เล่นเพลงจาก YouTube
- Discord Bot Token
- Typhoon API Key
- Together AI API Key (จำเป็นสำหรับคำสั่งวาดภาพ)
- Spotify Client ID และ Client Secret (ไม่บังคับ - จำเป็นเฉพาะโหลด Spotify Playlist)
- Valorant API Key (ไม่บังคับ)
- Prokerala API Client ID และ Client Secret (จำเป็นสำหรับคำสั่งดูดวง)

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
TYPHOON_API_KEY=your_typhoon_api_key
TOGETHER_API_KEY=your_together_api_key
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
VALORANT_API_KEY=your_valorant_api_key
PROKERALA_CLIENT_ID=your_prokerala_client_id
PROKERALA_CLIENT_SECRET=your_prokerala_client_secret
```

| ตัวแปร | จำเป็น | แหล่งที่มา |
| --- | --- | --- |
| `DISCORD_TOKEN` | ใช่ | [Discord Developer Portal](https://discord.com/developers/applications) |
| `TYPHOON_API_KEY` | ใช่ | [OpenTyphoon](https://opentyphoon.ai/) |
| `TOGETHER_API_KEY` | สำหรับ /draw | [Together AI](https://together.ai/) |
| `SPOTIFY_CLIENT_ID` | สำหรับ Spotify Playlist | [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) |
| `SPOTIFY_CLIENT_SECRET` | สำหรับ Spotify Playlist | [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) |
| `VALORANT_API_KEY` | ไม่ | [HenrikDev Dashboard](https://api.henrikdev.xyz/dashboard/) |
| `PROKERALA_CLIENT_ID` | เฉพาะดูดวง | [Prokerala Astrology API](https://api.prokerala.com/) |
| `PROKERALA_CLIENT_SECRET` | เฉพาะดูดวง | [Prokerala Astrology API](https://api.prokerala.com/) |

ไฟล์ `.env` ถูก ignore ไว้แล้ว ห้าม commit token หรือ API key ขึ้น repository

คำสั่ง `/horoscope` ใช้ Advanced Daily Prediction แบบครบ 4 หมวด ซึ่งใช้
1,000 Prokerala credits ต่อราศีต่อวัน บอทจะ cache ผลไว้จนเปลี่ยนวันเพื่อลด
การเรียก API ซ้ำ หากมีการรีสตาร์ทบอท cache ในหน่วยความจำจะเริ่มใหม่

สีในคำสั่ง `/horoscope` และ `/lucky-shirt` ดึงจากตาราง
[Colors of the day in Thailand](https://en.wikipedia.org/wiki/Colors_of_the_day_in_Thailand)
ผ่าน Wikimedia API และ cache ไว้ 24 ชั่วโมง เนื้อหาต้นทางเผยแพร่ภายใต้
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)

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
Synced 59 command(s)
Logged in as ...
```

## ตรวจสอบก่อนส่งขึ้นระบบ

รัน compile check และชุดทดสอบจาก root ของโปรเจกต์:

```bash
python -m compileall -q main.py src
python -m unittest discover -s tests -v
```

ชุดทดสอบครอบคลุม persistence/ownership ของ Reminder และ Price Alert,
allowlist สำหรับการตั้งค่าและสัญลักษณ์ตลาด, rate limit ของ AI Message Tools
และ CRUD ของ Saved Playlists

## Deploy บน Railway

1. สร้างโปรเจกต์ใหม่ใน Railway และเลือก **Deploy from GitHub repo**
2. เลือก repository นี้
3. เพิ่ม `DISCORD_TOKEN`, `TYPHOON_API_KEY`, `TOGETHER_API_KEY`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `VALORANT_API_KEY`,
   `PROKERALA_CLIENT_ID` และ `PROKERALA_CLIENT_SECRET` ในหน้า
   **Variables**
4. กำหนด Start Command เป็น:

   ```text
   python main.py
   ```

5. Deploy โดยไม่ต้องสร้าง Public Domain หรือกำหนด `PORT`
6. ใช้เพียง 1 replica เพื่อไม่ให้บอทหลาย process ใช้ token เดียวกันพร้อมกัน

หากต้องการเก็บฐานข้อมูล Reminder, Price Alert, Morning Digest, Dashboard และการตั้งค่าห้องข้ามการ redeploy
ให้ผูก Persistent Volume กับโฟลเดอร์ `data/` ตามการตั้งค่าของแพลตฟอร์มที่ใช้

บอทเป็น worker ที่เชื่อมต่อ Discord Gateway โดยตรง จึงไม่ต้องมี HTTP health check
Railway จะอ่าน `railpack.json` และติดตั้ง FFmpeg, Opus และ Node.js
สำหรับระบบเพลงให้อัตโนมัติ โดยไม่ต้องใช้ Docker

ลิงก์ Spotify รองรับทั้งเพลงเดี่ยว (`/track/...`) และเพลย์ลิสต์ (`/playlist/...`) โดยเพลงเดี่ยวจะอ่านข้อมูลและค้นหาบน YouTube ได้ทันที ส่วนเพลย์ลิสต์จะใช้ Spotify API Credentials ในการดึงข้อมูลเพลงทั้งหมดเข้ามาในคิว

## โครงสร้างโปรเจกต์

```text
.
├── railpack.json            # Runtime packages สำหรับ Railway
├── main.py                  # Entry point สำหรับ local และ Railway
├── requirements.txt         # Python dependencies
├── .env.example             # ตัวอย่างตัวแปรแวดล้อม
├── docs/
│   └── architecture.md      # ขอบเขตและแนวทางเพิ่มโมดูล
├── tests/
│   └── test_secure_features.py # Unit tests สำหรับ persistence และ validation
└── src/
    ├── bot.py               # ประกอบ Bot, โหลด cogs และคำสั่งหลัก
    ├── config.py            # Environment configuration
    ├── ui.py                # ชุดสีและรูปแบบ Embed กลาง
    ├── cogs/                # Slash commands แยกตามฟีเจอร์
    │   ├── music.py
    │   ├── stock.py
    │   ├── weather.py
    │   └── ...
    └── services/            # Persistence และ client/logic สำหรับบริการภายนอก
        ├── database.py      # SQLite repository
        ├── typhoon.py       # OpenTyphoon client และ conversation state
        ├── market_data.py   # ราคาหุ้น คริปโต และทองคำ
        ├── chart_generator.py # สร้างกราฟราคาแบบ PNG
        ├── translation.py   # Google Translate endpoint
        ├── prokerala.py     # Prokerala Astrology API
        └── gemini.py        # Compatibility imports สำหรับชื่อเดิม
```

รายละเอียด dependency direction และวิธีเพิ่มคำสั่งใหม่อยู่ใน
[`docs/architecture.md`](docs/architecture.md)

## แก้ไขปัญหาเบื้องต้น

- `Missing required environment variables` — ตรวจค่า `DISCORD_TOKEN` และ
  `TYPHOON_API_KEY`
- `LoginFailure: Improper token` — สร้างหรือคัดลอก Discord Bot Token ใหม่
- Slash Commands ไม่แสดง — ตรวจ scope `applications.commands` และรอให้ Discord sync
- เล่นเพลงไม่ได้ — ตรวจว่า FFmpeg/Opus และ Deno 2.3+ หรือ Node.js 22+
  ติดตั้งแล้ว รวมถึงตรวจสิทธิ์ Connect/Speak ของบอท
- คำสั่ง Valorant ใช้ไม่ได้ — ตรวจ `VALORANT_API_KEY`; ฟีเจอร์อื่นยังใช้งานได้ตามปกติ
- คำสั่งดูดวงใช้ไม่ได้ — ตรวจ Prokerala credentials และเครดิตคงเหลือของบัญชี
- Dashboard ไม่อัปเดต — ตรวจว่าบอทออนไลน์เวลา 08:00 น. ตามเวลาไทย,
  ข้อความเดิมยังอยู่ และบอทมีสิทธิ์ View Channel, Send Messages และ Embed Links
- ระบบแจ้งเตือนไม่ส่งข้อความ — ตรวจห้องที่ตั้งไว้ สิทธิ์ของบอท และลองตั้งค่าห้องใหม่
  ด้วย `/x-setup` หรือ `/deals-setup`

## ความปลอดภัย

- อย่าเผยแพร่ไฟล์ `.env`, token หรือ API key
- หาก secret เคยถูก commit หรือแชร์ ให้ rotate ค่านั้นทันที
- จำกัดสิทธิ์ของ Discord bot เท่าที่จำเป็น
- ไฟล์ฐานข้อมูลและ runtime state ใน `data/` ถูก ignore จาก Git และฐานข้อมูลใหม่ถูกตั้ง permission เป็น `0600`
- Query ของ SQLite ใช้ parameter binding และชื่อ field ที่แก้ไขได้ผ่าน allowlist
- คำสั่งผู้ดูแลตรวจ permission ตอน runtime และ Admin Panel ผูกกับผู้เปิดหน้าต่างเท่านั้น
- ข้อมูลจาก API ภายนอกไม่สามารถ Mention `@everyone` หรือ Role ได้โดยค่าเริ่มต้น
- `/ask`, `/draw` และ AI Message Tools มี rate limit เพื่อลดการ abuse และค่า API
- Symbol ตลาด, ราคา, เวลา, Timezone, ความยาวข้อความ และจำนวน Alert ถูก validate ก่อนบันทึก
- `/bot-status` ไม่แสดง token, API key หรือรายละเอียด exception ภายใน
