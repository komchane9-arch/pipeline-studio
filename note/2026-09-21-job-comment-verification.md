# ตัวตรวจคอมเมนต์ใบงาน p970424321

## อาการและหลักฐาน

ใบงานมีคอมเมนต์ 2 ข้อความ แต่ผล 5 กลุ่มเก็บ comment_count=1 และ verified.comments_wanted=1; หน้าเว็บจึงรายงานขาดคอมเมนต์ แม้ภาพผู้ใช้แสดงครบ.

ตรวจมือถือ Khao Fang Nichapa จาก data/devices.json: serial DATCW8GQUOCUWK9P. ใช้ phone_lock และ open_post_link ตามเส้นทางบอทกับกลุ่ม 3572170672880410, ลิงก์ https://www.facebook.com/share/p/1EnhDXP6N9/.

## Why-Why

1. ทำไมหน้าเว็บยังรายงานขาด? _fb_result_missing เปรียบเทียบ verified.comments_seen=1 กับจำนวนในใบงาน 2.
2. ทำไมตัวตรวจต้องการเพียง 1? run รับ callback จาก app แต่ verify_liked ส่ง callback เข้า _as_texts โดยไม่ resolve; เดิมจึงแปลง function เป็นข้อความหนึ่งรายการ.
3. ทำไมหน้าจอจริงมีแต่ตัวตรวจอาจได้ศูนย์? เดิม screen_has อ่าน XML จอแรกหลังเปิดลิงก์เท่านั้น ไม่เลื่อน. หลักฐาน diagnostics/job-comments-20260921-184414: step 0 ไม่มีคอมเมนต์, step 2 เห็นซิมทรูครบ, step 3–4 เห็น Pocket WiFi ครบ. ทั้งสองเป็นผู้เขียน Khao Fang Nichapa.

## การแก้และผล

- _as_texts resolve callback ก่อนแปลงเป็นรายการ.
- verify_existing_comments เลื่อนด้วยสัดส่วนหน้าจอ เก็บ matched index ข้าม viewport เทียบเนื้อหาเต็มในเขตคอมเมนต์ของบัญชีจริง; ไม่นับ preview โดเมนเดียวกันเป็นหลักฐาน URL-only.
- พบครบจึงคืน comments_seen เป็นจำนวนจริง; พบไม่ครบคืน None พร้อม comments_observed/note โดยรักษาผลเดิม. หน้าเว็บแสดงยังตรวจไม่ครบแทนบอกว่าคอมเมนต์ไม่มี.
- ทดสอบจริงโค้ดใหม่โดยเปิดลิงก์ซ้ำ: diagnostics/job-comments-20260921-184639/result.json คืน comments_seen=2/comments_wanted=2/comments_complete=true. ไม่มีการส่งคอมเมนต์หรือกดไลก์ระหว่างตรวจ.
- regression 19 unittest ผ่าน และ test_fb_group_controls ผ่านทุก checks. เพิ่ม replay XML จริง, callback สองข้อความ, wrong account และ unknown แทนศูนย์.
- ตรวจมือถือจริงหนึ่งกลุ่มเท่านั้น; ยังไม่ยืนยันอีกสี่กลุ่มและไม่ได้แก้ทะเบียนให้ครบด้วยการคาดเดา.
