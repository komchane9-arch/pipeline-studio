# Link Harvester

แอป Android หาลิงก์สินค้าใน Shopee/Lazada ตาม keyword ที่ตั้งไว้ แล้วส่งเข้าแอป `th.pipeline.links`
รันในมือถือเอง (ใช้ AccessibilityService) เว้นจังหวะแบบสุ่มเพื่อเลียนแบบคนใช้จริง

## ⚠️ เวอร์ชันนี้คือ v0.1 — ตัวพิสูจน์ว่าอ่านหน้าจอ Shopee ได้ไหม

**ยังไม่ได้ทำส่วนก๊อปลิงก์และส่งเข้า pipeline links** ตั้งใจทำเป็นขั้นแรกก่อน เพราะจุดเสี่ยง
ที่สุดของทั้งโปรเจกต์คือ **"AccessibilityService อ่านหน้าจอ Shopee ได้ไหม"**
(ตอนทดสอบผ่าน adb พบว่า uiautomator อ่าน Shopee ไม่ได้ แต่ accessibility ใช้กลไกคนละแบบ
อาจอ่านได้) v0.1 จึงมีแค่:

- หน้าตั้งค่า: ใส่ keyword หลายคำ, เลือก Shopee/Lazada, ตั้งช่วงเวลาสุ่ม (เก็บไว้ใช้ต่อ)
- ปุ่ม **Dump หน้าจอ** ในแถบแจ้งเตือน — อ่านทุกข้อความบนหน้าจอปัจจุบัน นับ node
  และนับว่าเจอ "EXTRA COMM" กี่จุด

ถ้า v0.1 อ่าน EXTRA COMM บนหน้าค้นหา Shopee เจอ → ต่อส่วนก๊อปลิงก์ + ส่งเข้า pipeline links
ได้เลยในแอปตัวเดิม ถ้าอ่านไม่เจอ → ต้องเปลี่ยนไปใช้ OCR (ต้องมี Gradle + ML Kit)

## Build และติดตั้ง

ต้องมีบนคอม (ตัวเดียวกับที่ build `android-notes` ผ่าน):
- Android SDK build-tools + platform (ตั้ง `ANDROID_HOME` ให้ชี้ไป Android SDK)
- JDK (`javac`, `keytool` — ตั้ง `JAVA_HOME`)
- adb (หาจาก `ANDROID_HOME/platform-tools` หรือ PATH เอง)

```bash
cd link-harvester
python build.py --install --serial 93a21824
```

ไม่ใช้ Gradle — พึ่งแค่ API ของ Android เอง จึง build เร็วและไฟล์เล็ก

## วิธีทดสอบ v0.1

1. ลงแอปตามข้างบน แล้วเปิดแอป **Link Harvester**
2. ใส่ keyword (เช่น `ถุงคลุมรถ`) กด **บันทึกการตั้งค่า**
3. กด **เปิดสิทธิ์ Accessibility** → ในตั้งค่า หา "Link Harvester" แล้วเปิดสวิตช์
   (Android จะเตือนว่าแอปนี้ดูหน้าจอได้ — กดยอมรับ)
4. เปิดแอป **Shopee** ค้นหาสินค้าจนเห็นผลลัพธ์ (ที่มีป้าย EXTRA COMM)
5. ดึงแถบแจ้งเตือนลงมา กด **Dump หน้าจอ** — จะเด้ง toast บอกว่าอ่านได้กี่ node เจอ EXTRA COMM กี่จุด
6. กลับมาแอป Link Harvester กด **ดูผล Dump หน้าจอล่าสุด** — เห็นข้อความทั้งหมดที่อ่านได้

ผลไฟล์เต็มอยู่ที่ `/sdcard/Android/data/th.pipeline.harvester/files/dump.txt` (ดึงด้วย adb pull ได้)

## ผลลัพธ์ที่ต้องดู

- **เจอ EXTRA COMM > 0** → เยี่ยม accessibility อ่าน Shopee ได้ ทำต่อได้เลย
- **อ่านได้หลาย node แต่ EXTRA COMM = 0** → อ่านได้แต่ป้ายเป็นรูปไม่ใช่ข้อความ ต้องดู dump ว่ามีอะไรพอใช้แทน
- **root = null / อ่านได้ 0 node** → Shopee บล็อก accessibility ด้วย ต้องเปลี่ยนไป OCR

## แผนต่อ (v0.2 เมื่อ v0.1 ผ่าน)

1. เปิด Shopee เอง → หาช่องค้นหา → พิมพ์ keyword → กดค้นหา (ทั้งหมดผ่าน accessibility node)
2. เลื่อนผลลัพธ์ หา node EXTRA COMM → เปิดสินค้า → กดแชร์ → คัดลอกลิงก์
3. อ่านลิงก์จาก clipboard → ส่งเข้า `th.pipeline.links` ผ่าน Intent แชร์ (ACTION_SEND)
4. เว้นจังหวะสุ่มตามที่ตั้ง วนจนครบ keyword และครบแพลตฟอร์ม
5. Lazada: เหมือนกันแต่ไม่กรอง EXTRA COMM เก็บทุกลิงก์

## ข้อควรรู้

การให้แอปกดแทนคนขัดกับเงื่อนไข Shopee/Lazada บัญชี affiliate อาจโดนจำกัดหรือแบน
เว้นจังหวะสุ่มและจำกัดจำนวนต่อวันช่วยลดความเสี่ยง แต่ไม่ได้ทำให้เป็นศูนย์ — เริ่มทดสอบทีละ keyword
