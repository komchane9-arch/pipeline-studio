# ADB MCP server

ให้ Claude บน cloud (claude.ai/code) เห็นและกดมือถือ Android ที่ต่อ USB กับคอมเครื่องนี้ได้
ผ่าน MCP connector — เพื่อ **build แอป ลงมือถือ แคปหน้าจอจริง กดทดสอบ และอ่าน error**
โดยที่ตัว server ไม่กินโควตา Claude

```
Claude บน cloud ──► custom connector (MCP) ──► Cloudflare Tunnel (HTTPS)
                                                   │
                              คอมนี้: adb_mcp_server.py ── USB ── มือถือ Android
```

## ⚠️ อ่านก่อนใช้ — ความปลอดภัย

server นี้ **แตะ กด พิมพ์ และลงแอปบนมือถือได้ทั้งเครื่อง** ใครก็ตามที่รู้ URL เต็ม
(ซึ่งมีรหัสลับอยู่ในเส้นทาง) สั่งมือถือได้ทันที ฉะนั้น:

- **อย่าส่ง URL connector ให้ใคร** และอย่าวางในที่สาธารณะ
- **ปิด tunnel ทุกครั้งที่ไม่ได้ใช้** (ปิดหน้าต่าง `cloudflared`)
- **ต่อมือถือทดสอบเครื่องเดียว** และตั้ง `ADB_MCP_DEVICES` ให้ล็อกไว้เฉพาะเครื่องนั้น
  แยกจากมือถือที่ Pipeline Studio ใช้โพสต์จริง (ที่ล็อกอิน Facebook/Shopee ไว้)
- server ฟังแค่ `127.0.0.1` ทางเข้าจากข้างนอกทางเดียวคือ tunnel
- คำสั่ง `shell` ดิบปิดไว้ เปิดเมื่อจำเป็นด้วย `ADB_MCP_ALLOW_SHELL=1`
- ทุกคำสั่งถูกบันทึกที่ `data/audit.log`

## ติดตั้ง

ต้องมี Python 3.10+, [adb (platform-tools)](https://developer.android.com/tools/releases/platform-tools)
และ [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)

```bash
pip install -r requirements.txt
```

บนมือถือ: เปิด USB debugging, กดอนุญาตคอมเครื่องนี้, และติดตั้ง ADBKeyboard ถ้าจะพิมพ์ภาษาไทย

## เปิดใช้งาน

1. หาว่ามือถือทดสอบ serial อะไร: `adb devices`
2. ตั้งให้ใช้ได้เฉพาะเครื่องนั้น แล้วเปิด server + tunnel:
   ```bash
   # Windows: ดับเบิลคลิก start_adb_mcp.bat (ตั้ง ADB_MCP_DEVICES ไว้ก่อนถ้าต้องการ)
   set ADB_MCP_DEVICES=TEST01
   start_adb_mcp.bat
   ```
   ```bash
   # macOS/Linux
   ADB_MCP_DEVICES=TEST01 ./start_adb_mcp.sh
   ```
3. หน้าต่าง server จะพิมพ์ **รหัสลับ** และเส้นทาง `/​<รหัส>/mcp`
   หน้าต่าง tunnel จะพิมพ์ URL แบบ `https://xxxx.trycloudflare.com`
4. **URL สำหรับ connector** = เอาสองอันต่อกัน:
   ```
   https://xxxx.trycloudflare.com/<รหัส>/mcp
   ```

> ใช้ `trycloudflare.com` ได้ทันทีโดยไม่ต้องมีโดเมน แต่ URL เปลี่ยนทุกครั้งที่เปิดใหม่
> ถ้าอยากได้ URL คงที่ ให้ตั้ง named tunnel ผูกกับโดเมนของคุณ (ดูเอกสาร cloudflared)

## เพิ่มเป็น connector ใน Claude

1. ไปที่ https://claude.ai/customize/connectors → **Add custom connector**
2. วาง URL เต็มจากข้อ 4 (ชนิด MCP / streamable HTTP)
3. **เปิด session ใหม่** ใน claude.ai/code — connector ถูกอ่านตอนเริ่ม session เท่านั้น
   session เดิมจะยังไม่เห็นเครื่องมือใหม่
4. สั่ง Claude เช่น "ลง app.apk ลงมือถือ เปิดแอป แล้วแคปหน้าจอมาดู"

## เครื่องมือที่ Claude เรียกได้

| เครื่องมือ | ทำอะไร |
|---|---|
| `devices` | ดูมือถือที่ต่ออยู่ (serial, รุ่น, อนุญาตไหม) |
| `screenshot` | แคปหน้าจอ (ย่อได้) — บอกขนาดจอจริงมาด้วย |
| `ui_tree` | ผังปุ่ม/ข้อความบนจอ พร้อมพิกัดกึ่งกลางที่เอาไปแตะได้เลย |
| `tap` `long_press` `swipe` `key` | แตะ กดค้าง ปัด กดปุ่ม |
| `type_text` | พิมพ์ข้อความ (ไทย/อีโมจิ ต้องมี ADBKeyboard) |
| `set_adb_keyboard` | สลับเป็น ADBKeyboard แล้วคืนตัวเดิม |
| `upload_chunk` + `install_apk` | อัปโหลด .apk มาที่คอมแล้วลงมือถือ (หรือลงจาก URL) |
| `launch_app` `stop_app` `list_packages` | เปิด/ปิด/ดูแอป |
| `logcat` | อ่าน log หาสาเหตุแอปเด้ง |
| `shell` | คำสั่ง shell ดิบ (ปิดไว้เป็นค่าเริ่มต้น) |

## รอบการทำงานที่ Claude ทำได้เอง

ลงแอป → เปิดแอป → `screenshot`/`ui_tree` ดูหน้าจอจริง → `tap`/`type_text` ทดสอบ →
`logcat` ดู error → แก้โค้ด → build .apk ใหม่ → ลงทับ → วนจนหน้าจอถูกต้อง

## ตัวแปรตั้งค่า

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `ADB_MCP_DEVICES` | (ว่าง = ทุกเครื่อง) | จำกัด serial ที่ใช้ได้ คั่นด้วย comma — **ควรตั้งเสมอ** |
| `ADB_MCP_PORT` | 8765 | พอร์ตในเครื่อง |
| `ADB_MCP_SECRET` | สุ่มเก็บใน `data/secret.txt` | รหัสลับในเส้นทาง (ลบไฟล์เพื่อสุ่มใหม่) |
| `ADB_MCP_ALLOW_SHELL` | ปิด | ตั้ง `1` เพื่อเปิดคำสั่ง shell ดิบ |
| `ADB_PATH` | หาจาก PATH | พาธ adb.exe ถ้าไม่อยู่ใน PATH |

## เทส

```bash
python -m pytest adb-mcp -q      # ไม่ต้องมีมือถือ ใช้ adb จำลอง
```

## ข้อจำกัด

- **โควตา Claude ไม่ได้เพิ่ม** session บน cloud ใช้โควตาเดียวกับบัญชีของคุณ
  ที่ช่วยได้คือไม่ต้องเปิด Claude อีกตัวบนคอม
- **คอมต้องเปิดและต่อมือถือไว้** ตลอดที่ทดสอบ
- `trycloudflare.com` เป็น URL ชั่วคราว เปิดใหม่ก็เปลี่ยน ต้องแก้ connector ทุกครั้ง
  (หรือใช้ named tunnel + โดเมนของตัวเองเพื่อให้คงที่)
