# Group Poster

ระบบโพสต์ลงกลุ่ม Facebook ผ่านมือถือ แยกออกมาจาก Pipeline Studio เพื่อขายให้คนอื่นใช้
มี serial key ที่ตรวจกับเครื่องหลักของเจ้าของ (แบบร่างเต็มอยู่ที่ `../SPEC-ขายระบบโพสต์กลุ่ม-serial-key.md`)

```
 คอมลูกค้า                                   เครื่องหลักของเรา (เปิดตลอด)
 agent/main.py  ── HTTPS ขาออก ──────────►  server/license_server.py
  หน้าเว็บ 127.0.0.1:8890                    ตรวจรหัส / ต่ออายุ / ระงับ
  โพสต์ผ่าน ADB ── USB ── มือถือลูกค้า         server/admin.py (ออกรหัส)
```

| โฟลเดอร์ | คืออะไร | อยู่ที่ไหน |
|---|---|---|
| `server/` | license server + คำสั่งออกรหัส | เครื่องเรา **ห้ามส่งให้ลูกค้า** |
| `agent/` | โปรแกรมลูกค้า + หน้าเว็บ | ส่งให้ลูกค้า |
| `agent/poster/` | โค้ดโพสต์ที่ copy มาจาก Studio | อัปเดตด้วย `python sync_poster.py` |
| `common/` | รูปแบบรหัสและ token | ใช้ทั้งสองฝั่ง |

## ลองใช้บนเครื่องเดียว (ใช้เวลาประมาณ 5 นาที)

ต้องมี Python 3.10 ขึ้นไป เปิด terminal ในโฟลเดอร์ `group-poster` แล้วรันทีละขั้น:

```bash
# 1. ติดตั้ง
pip install -r requirements.txt

# 2. เปิด license server (ปล่อยหน้าต่างนี้ค้างไว้) — หรือดับเบิลคลิก start_server.bat
python server/license_server.py

# 3. เปิด terminal ใหม่: สร้าง config ของโปรแกรมลูกค้า แล้วออกรหัสทดลอง
python server/admin.py agent-config --server http://127.0.0.1:8870
python server/admin.py new --plan trial --note "ทดสอบเอง"
#    → ได้รหัสแบบ GP-XXXX-XXXX-XXXX-XXXX

# 4. เปิดโปรแกรมลูกค้า — หรือดับเบิลคลิก start_agent.bat
python agent/main.py
#    → เปิด http://127.0.0.1:8890 แล้วใส่รหัสจากขั้นที่ 3
```

**ก่อนโพสต์จริง** ติดตั้ง adb ([platform-tools](https://developer.android.com/tools/releases/platform-tools))
หรือวาง `adb.exe` ไว้ที่ `agent/tools/adb.exe` จากนั้นทำตามนี้ให้เหมือนตอนใช้ Studio:
- เปิด USB debugging บนมือถือ แล้วกดอนุญาตคอมเครื่องนี้
- ติดตั้ง ADBKeyboard
- ล็อกอินแอป Facebook ไว้ และปิดรหัสล็อกหน้าจอ (ถ้ามีรหัส ปลุกจอแล้วปลดล็อกไม่ได้)

แล้วลองโพสต์ **แบบทดลอง** กับ 1 กลุ่มก่อน (ติ๊ก "ทดลองก่อน" ไว้ ทำทุกขั้นแต่ไม่กดโพสต์จริง)

## คำสั่งจัดการรหัส

```bash
python server/admin.py new --plan basic --note "ร้านเอ LINE @aaa"   # ออกรหัส
python server/admin.py new --plan pro --days 90 --count 5            # ออกทีละ 5 รหัส
python server/admin.py list                                          # ดูทั้งหมด
python server/admin.py show GP-XXXX-XXXX-XXXX-XXXX                   # ดูว่าใช้เครื่องไหนอยู่
python server/admin.py revoke GP-...      /  unrevoke GP-...         # ระงับ / ยกเลิกระงับ
python server/admin.py extend GP-... --days 30                       # ต่ออายุ
python server/admin.py release GP-...                                # ปลดทุกเครื่องให้ลูกค้า
```

| แพ็กเกจ | เครื่อง | กลุ่มต่อรอบ | อายุ |
|---|---|---|---|
| `trial` | 1 | 5 | 7 วัน |
| `basic` | 1 | 30 | 30 วัน |
| `pro` | 2 | 100 | 30 วัน |

ปรับได้ตอนออกรหัส (`--days`, `--devices`, `--groups`) หรือแก้ `PLANS` ใน `common/license_format.py`
ใส่ `--days 0` = ไม่มีวันหมดอายุ

## กติกาที่ระบบบังคับไว้

- รหัสใช้ได้ตามจำนวนเครื่องของแพ็กเกจ ลูกค้าปลดเครื่องเองได้ไม่เกิน 3 ครั้งต่อ 30 วัน (แอดมินปลดได้ไม่จำกัด)
- โปรแกรมลูกค้าต่ออายุกับ server ทุก 30 นาที ถ้า server ติดต่อไม่ได้ ใช้ต่อได้อีก **72 ชั่วโมง**
- ระงับรหัสแล้ว โปรแกรมลูกค้าจะหยุดรับงานใหม่ภายใน 30 นาที (หรือทันทีเมื่อลูกค้ากด "ตรวจกับ server อีกครั้ง")
- ระยะห่างระหว่างกลุ่มต่ำสุด 15 วินาที ลูกค้าตั้งให้ถี่กว่านี้ไม่ได้
- เพดานคอมเมนต์ต่อชั่วโมงและต่อวันใช้ค่าเดียวกับ Studio (`fb_limits.py`)
- license token เซ็นด้วย Ed25519 ถ้าแก้ไฟล์เพื่อเพิ่มจำนวนกลุ่มหรือยืดวันหมดอายุ ลายเซ็นจะไม่ตรงและใช้ไม่ได้

## เปิดให้ลูกค้าเชื่อมต่อ (Cloudflare Tunnel)

server ฟังแค่ `127.0.0.1` ทางเข้าจากภายนอกทางเดียวคือ tunnel ไม่ต้องเปิด port ที่เราเตอร์

1. ซื้อโดเมนแล้วเพิ่มเข้า Cloudflare (แพ็กเกจฟรีก็พอ)
2. ติดตั้ง `cloudflared` บนเครื่องหลัก แล้วรัน:
   ```bash
   cloudflared tunnel login
   cloudflared tunnel create group-poster
   cloudflared tunnel route dns group-poster license.<โดเมนของคุณ>
   cloudflared tunnel run --url http://127.0.0.1:8870 group-poster
   ```
3. สร้าง config ใหม่ด้วย URL จริง แล้วส่ง `agent/config.json` ไปกับโปรแกรมลูกค้า:
   ```bash
   python server/admin.py agent-config --server https://license.<โดเมนของคุณ>
   ```
4. ให้ server และ tunnel เปิดเองตอนบูตเครื่อง: ใช้ `cloudflared service install`
   และ [NSSM](https://nssm.cc) สำหรับ `python server/license_server.py`

## สำรองข้อมูล — สำคัญ

ทุกอย่างอยู่ใน `server/data/` (ไม่ขึ้น git):
- `signing_key.pem` = **กุญแจเซ็นรหัส** ถ้าหาย รหัสทุกใบที่ขายไปแล้วจะต่ออายุไม่ได้ ถ้าหลุด คนอื่นจะปลอม license ได้
- `licenses.sqlite3` = รายการรหัสและเครื่องของลูกค้า

copy ทั้งโฟลเดอร์ไปเก็บที่ปลอดภัยทุกวัน และห้ามส่งโฟลเดอร์นี้ให้ใคร

## เมื่อแอป Facebook อัปเดตแล้วโพสต์พัง

แก้ที่ Studio ก่อนตามปกติ แล้วรัน:
```bash
python sync_poster.py        # copy โค้ดโพสต์ชุดใหม่มาไว้ใน agent/poster/
python -m pytest -q          # ต้องผ่านทั้งหมดก่อนส่งให้ลูกค้า
```
**ห้ามแก้ไฟล์ใน `agent/poster/` ตรงๆ** (ยกเว้น `studio_shared.py` และ `fb_auto_post.py`
ซึ่งเป็นตัวแทนที่เขียนแยกไว้) ไม่งั้นรอบ sync ถัดไปจะทับของที่แก้ไว้หาย

## ยังไม่ได้ทำ (ตามแผนใน SPEC)

- ส่งอัปเดตข้อความปุ่มจาก server (ตอนนี้ลูกค้าต้องได้โปรแกรมเวอร์ชันใหม่)
- build เป็นไฟล์ `.exe` ด้วย Nuitka และทำตัวช่วยติดตั้ง adb/ADBKeyboard
- เข้ารหัสไฟล์ license ด้วย DPAPI ของ Windows
- ระบบรับเงินแล้วออกรหัสอัตโนมัติ
- ดึงลิงก์โพสต์หลังโพสต์เสร็จ (Studio ใช้ clipboard ของตัวเอง ยังไม่ได้ต่อเข้ามา)

## ข้อควรรู้ก่อนขาย

การโพสต์อัตโนมัติขัดกับเงื่อนไขการใช้งานของ Facebook บัญชีลูกค้าอาจโดนจำกัดหรือแบน
ต้องแจ้งไว้ในเงื่อนไขการขาย และห้ามโฆษณาว่าไม่โดนแบน
