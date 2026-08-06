# Project architecture

โปรเจกต์แบ่งโค้ดตามหน้าที่เพื่อให้เพิ่มฟีเจอร์และทดสอบได้ง่ายขึ้น:

```text
main.py
  └── src.bot
        ├── src.config
        ├── src.services
        └── src.cogs
              └── data/javis.db
```

## ขอบเขตแต่ละส่วน

- `main.py` ตรวจ environment variables ที่จำเป็นและเริ่ม process เท่านั้น
- `src/bot.py` ประกอบ Discord bot, ลงทะเบียน extension และเก็บเฉพาะคำสั่งหลัก
- `src/cogs/` เก็บ Discord UI และ slash commands แยกหนึ่งไฟล์ต่อฟีเจอร์
- `src/services/` ติดต่อ SDK หรือ API ภายนอก และไม่ควรผูกกับ Discord UI
- `src/config.py` เป็นจุดเดียวสำหรับอ่าน environment variables
- `src/services/database.py` เป็น persistence boundary สำหรับ SQLite โดยใช้
  parameterized queries และเก็บ runtime state ใน `data/javis.db`

Dependency ควรไหลจาก `bot` ไป `cogs`/`services` และจาก `cogs` ไป `services`
หรือ `config` เท่านั้น หลีกเลี่ยงการ import `bot` กลับจากโมดูลย่อยเพื่อไม่ให้เกิด
circular import

Cog เข้าถึงฐานข้อมูลผ่าน `bot.database` และควรเรียก synchronous repository methods
ด้วย `asyncio.to_thread` เพื่อไม่ block Discord Gateway ห้ามประกอบ SQL จาก input
ของผู้ใช้ และต้องเพิ่มชื่อ column ลง allowlist ก่อนรองรับการตั้งค่าใหม่

## บริการเสริมและฟีเจอร์สำคัญ (Core Services)

### 1. บริการสร้างกราฟราคา (Chart Generator)
- โมดูล `src/services/chart_generator.py` ทำหน้าที่วาดกราฟแนวโน้มราคาสินทรัพย์ (เช่น หุ้น คริปโต ทองคำ) แบบภาพนิ่ง (.png) โดยใช้ Matplotlib
- ถูกกำหนดให้เรนเดอร์ในโหมด non-GUI (`matplotlib.use('Agg')`) เพื่อความเสถียรบนเซิร์ฟเวอร์
- ปรับแต่งการแสดงผลขั้นสูง: ใช้สีพื้นหลังโทนเดียวกับดิสคอร์ดแบบมืด (`#2b2d31`), เพิ่มเลเยอร์เส้นเรืองแสงสไตล์นีออน (Neon Line Glow), ใส่เอฟเฟกต์ไล่เฉดสีแนวดิ่ง (Vertical Gradient Fill), และใส่จุดเน้นราคาล่าสุดพร้อมวงแหวนเรืองแสง

### 2. บริการปัญญาประดิษฐ์ (AI Service)
- โมดูล `src/services/gemini.py` ได้เปลี่ยนระบบการทำงานภายในไปเรียกใช้งาน **Typhoon AI** ผ่าน API รูปแบบ OpenAI-compatible (โมเดล `typhoon-v2.5-30b-a3b-instruct`)
- รักษาชื่อโครงสร้างเดิมไว้เพื่อไม่ให้กระทบกับคำสั่ง `/ask` หรือระบบสรุปยามเช้า แต่ปรับปรุงให้ประมวลผลผ่าน OpenTyphoon Endpoint พร้อมระบบจัดเก็บประวัติการสนทนาส่วนตัวของแต่ละช่องแชท (`TyphoonChat`)

### 3. ระบบเพลงและคลังเพลงโปรด (Music & Saved Playlists)
- ระบบเพลงเพิ่มการจัดเก็บสถานะคิวเพลงส่วนตัวใน `Database` ผ่านคำสั่ง `/playlist-save`, `/playlist-load`
- สร้างตาราง `playlists` (เชื่อมกับ Discord User ID) และ `playlist_tracks` (เก็บรายละเอียดเพลง ลำดับ และลิงก์อ้างอิง) โดยทำงานร่วมกับ SQLite Foreign Key แบบ `ON DELETE CASCADE` เพื่อความสะอาดในการล้างข้อมูลคิว

### 4. บริการวาดรูปภาพ AI (Flux Image Generation)
- โมดูล `src/cogs/draw.py` เปลี่ยนไปใช้บริการของ **Together AI** โดยทำงานร่วมกับโมเดล `black-forest-labs/FLUX.1-schnell-Free`
- เพื่อแก้ไขปัญหาลิงก์รูปภาพหมดอายุ (Temporary Link) บอทจะทำการดาวน์โหลดไบต์รูปภาพจาก API แล้วแปลงเป็น `discord.File` เพื่อแนบส่งตรงไปยังห้องแชทของดิสคอร์ดเป็นรูปภาพถาวร

## เพิ่ม slash command ใหม่

1. สร้างโมดูลใน `src/cogs/` และประกาศคลาสที่สืบทอดจาก `commands.Cog`
2. เพิ่มฟังก์ชัน `async def setup(bot)` ซึ่งเรียก `bot.add_cog(...)`
3. เพิ่มชื่อโมดูลลงใน `COG_EXTENSIONS` ที่ `src/bot.py`
4. หากมี client/API logic ให้แยกไว้ใน `src/services/`
5. รัน compile check ก่อนเปิดบอต:

   ```bash
   python -m compileall -q main.py src
   ```
