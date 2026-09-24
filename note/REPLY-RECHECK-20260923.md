# Recheck คำตอบ 3 รายการ — 23 กันยายน 2026

## ขอบเขต

ตรวจเฉพาะบัญชี Khao Fang Nichapa สามรายการที่หน้าเว็บนับว่าไม่สำเร็จ โดยไม่ล้าง submitted marker และไม่ส่ง comment แรกซ้ำ:

- Bunriam Phiwwandee — `share/p/19MWioU8ab/`
- Napat Pattarapornkul — `share/p/14qyvBpsDzo/`
- Pirom Lobru — `share/p/1Hi5j6cDo1/`

## อาการและ Why-Why

1. Bunriam แสดง `AccountUnreadable` ทั้งที่ Bot8 รอบหลังพบคำตอบของ Khao Fang ใต้ Bunriam แล้ว
   - DB read-only พบ child ของ Khao Fang ที่ `reply_to=Bunriam Phiwwandee`; ข้อความและ URL ตรง draft เต็ม และเห็นต่อเนื่องถึงรอบเก็บ `2026-09-23T12:48:45`.
   - ตัว retry เดิมเห็น `answered=1` แต่ `reply_sent_at` ว่าง จึงปฏิเสธเพื่อกันส่งซ้ำ โดยไม่มีทางใช้หลักฐานบวกจาก collector มาปิดสถานะ.
   - แก้ให้ retry ยืนยันจาก collector ได้เฉพาะกรณี parent ชื่อเดียวกันมีหนึ่งแถว, child เป็นบัญชีเดียวกัน, `reply_to` ตรง, ข้อความเต็มตรง, และ child ถูกพบหลังเวลาเข้าคิว; ถ้าชื่อชนมากกว่าหนึ่ง parent ต้องปฏิเสธเหมือนเดิม.
2. Napat ส่ง comment แรกสำเร็จ แต่ comment 2 เคยหยุดที่ `หาแถว...ไม่เจอ`.
   - ตรวจมือถือแบบไม่ส่งที่ `data/reply-audit/20260923-143057-Napat/` พบ parent และยืนยัน composer `กำลังตอบกลับ Napat Pattarapornkul`; เป็นสภาพหน้าจอชั่วคราวในรอบเดิม ไม่ใช่คอมเมนต์ถูกลบ.
3. Pirom ส่ง comment แรกสำเร็จ แต่ comment 2 หา parent ไม่เจอซ้ำได้.
   - ก่อนแก้ หลักฐาน `data/reply-audit/20260923-143320-Pirom/016.json` ถึง `027.json` ยังเห็นชื่อ+ข้อความ Pirom และปุ่ม Reply จริง.
   - หลัง verifier กางคำตอบแรก parent avatar เลื่อนไปที่ y=162 เหนือขอบอ่าน y=260 แต่ปุ่ม Reply ยังอยู่ในเขตปลอดภัยที่ y=268; finder ตัดทั้งแถวออก แล้วเลื่อนลงทางเดียวจนหลุด.
   - สาเหตุรากคือ reacquire ใช้ขอบอ่านเป็นขอบเดียวกับขอบกด ทั้งที่แถวค้างขอบบนยังระบุตัวตนได้และ control อยู่ในพื้นที่ปลอดภัย.
   - แก้ให้ reacquire กลางโซนคอมเมนต์ขยายเฉพาะพื้นที่อ่านขึ้นไปหนึ่งช่วงข้อความ แต่คืนพิกัด control เฉพาะเมื่ออยู่ใต้ขอบปลอดภัยและชื่อ+ข้อความ parent ตรงเต็มเท่านั้น.

## ผลทดสอบ

- Regression 66 รายการผ่าน ครอบคลุมแถวค้างขอบบนที่ปุ่มกดปลอดภัย, ปุ่มอยู่เหนือขอบต้องปฏิเสธ, followup retry ปกติ, submitted followup ต้องตรวจอย่างเดียว, collector proof ที่ตรงหนึ่งเดียว และชื่อ parent ชนต้องปฏิเสธ.
- `py_compile` ผ่านสำหรับไฟล์ที่แก้.
- ตรวจ Pirom สดหลังแก้แบบไม่ส่งที่ `data/reply-audit/20260923-145014-Pirom/` ผ่านและยืนยัน composer `กำลังตอบกลับ Pirom Lobru`.

## สถานะเปิดใช้

- safe restart สำเร็จโดยไม่ใช้ `--force`: PID `23852` → `28508`; `clip_app.py` และ `fb_mass_bot.py` ไม่ถูกหยุด.
- Bunriam: `/api/fb/engage/retry` ใช้ collector proof ที่ตรงหนึ่งเดียว ปิด `reply_error` และบันทึก `reply_sent_at=2026-09-21T14:27:24`; ไม่ส่งใหม่.
- Napat/Pirom: คืนคิวเฉพาะ synthetic key `::followup-2` สำเร็จ; `followup_error` ว่าง, comment แรกและ receipt เดิมไม่เปลี่ยน.
- เวลา 14:56 Facebook แจ้งจำกัดการแสดงความคิดเห็นชั่วคราวจากงานอื่นของบัญชี Khao Fang. account guard พักถึงประมาณ `2026-09-24 02:56`; comment 2 ทั้งสองรายการจึงรออยู่ในคิวและยังไม่ถูกส่ง ห้ามข้าม safety hold.
