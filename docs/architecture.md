# Project architecture

โปรเจกต์แบ่งโค้ดตามหน้าที่เพื่อให้เพิ่มฟีเจอร์และทดสอบได้ง่ายขึ้น:

```text
main.py
  └── src.bot
        ├── src.config
        ├── src.services
        └── src.cogs
```

## ขอบเขตแต่ละส่วน

- `main.py` ตรวจ environment variables ที่จำเป็นและเริ่ม process เท่านั้น
- `src/bot.py` ประกอบ Discord bot, ลงทะเบียน extension และเก็บเฉพาะคำสั่งหลัก
- `src/cogs/` เก็บ Discord UI และ slash commands แยกหนึ่งไฟล์ต่อฟีเจอร์
- `src/services/` ติดต่อ SDK หรือ API ภายนอก และไม่ควรผูกกับ Discord UI
- `src/config.py` เป็นจุดเดียวสำหรับอ่าน environment variables

Dependency ควรไหลจาก `bot` ไป `cogs`/`services` และจาก `cogs` ไป `services`
หรือ `config` เท่านั้น หลีกเลี่ยงการ import `bot` กลับจากโมดูลย่อยเพื่อไม่ให้เกิด
circular import

## เพิ่ม slash command ใหม่

1. สร้างโมดูลใน `src/cogs/` และประกาศคลาสที่สืบทอดจาก `commands.Cog`
2. เพิ่มฟังก์ชัน `async def setup(bot)` ซึ่งเรียก `bot.add_cog(...)`
3. เพิ่มชื่อโมดูลลงใน `COG_EXTENSIONS` ที่ `src/bot.py`
4. หากมี client/API logic ให้แยกไว้ใน `src/services/`
5. รัน compile check ก่อนเปิดบอต:

   ```bash
   python -m compileall -q main.py src
   ```
