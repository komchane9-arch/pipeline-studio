"""หน้าต่างกรอกบัญชี Google Flow — เจ้าของกรอกเอง เก็บแบบเข้ารหัส

**เจ้าของสั่ง 9 ก.ย. 2569** — *"ข้อ 1 ที่เก็บอีเมล + รหัสผ่าน ทำเป็นหน้าต่าง
มาให้ผมกรอก"* และยืนยันว่า *"เปลี่ยนบัญชีเองทุกครั้ง"* คือต้องล็อกอินใหม่ทุกรอบ
จึงต้องมีรหัสผ่านเก็บไว้จริง ไม่ใช่พึ่งบัญชีที่ Chrome จำไว้

เปิดด้วย

    python flow_accounts_window.py


ทำไมเป็นหน้าต่างบนเครื่อง ไม่ใช่หน้าเว็บ
---------------------------------------

Chrome ของเจ้าของอยู่**คนละเครื่องกับเซิร์ฟเวอร์** (เข้าผ่าน `laptop-…:8866`)
ถ้าทำเป็นหน้าเว็บ รหัสผ่านจะเดินทางข้ามเน็ตเวิร์กในบ้านแบบ **http ธรรมดา
ไม่ได้เข้ารหัส** ใครดักดูสายได้ก็อ่านได้

หน้าต่างตัวนี้รันบนเครื่องเดียวกับที่เก็บไฟล์ **รหัสผ่านจึงไม่ออกจากเครื่องเลย
แม้แต่ก้าวเดียว** — เดินจากช่องพิมพ์เข้าตัวเข้ารหัสของ Windows แล้วลงไฟล์

ถ้าอยากได้บนหน้าเว็บด้วย ต้องคุยเรื่องทางเข้ารหัสก่อน (https หรือกรอกที่เครื่อง
เซิร์ฟเวอร์อย่างเดียว) — ยังไม่ทำจนกว่าเจ้าของจะสั่ง


สิ่งที่หน้าต่างนี้ **ไม่ทำ**
--------------------------

* ไม่โชว์รหัสผ่านที่เก็บไว้แล้วซ้ำอีก — บันทึกแล้วดูย้อนไม่ได้ ตั้งใหม่ได้อย่างเดียว
* ไม่เขียนรหัสผ่านลง log · ไฟล์สถานะ · ข้อความแจ้งเตือน
* ไม่ส่งอะไรออกนอกเครื่อง
"""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox, ttk

import flow_accounts

TITLE = "บัญชี Google Flow — กรอกไว้ให้ระบบสลับเอง"

# สีให้เข้ากับหน้าเว็บของโปรเจกต์ (โทนมืด) แต่ไม่พึ่งธีมของ Windows
BG = "#14161a"
CARD = "#1c2027"
FG = "#e8eaed"
DIM = "#9aa0a6"
OK = "#57d977"
WARN = "#ffb020"
BAD = "#ff6b6b"


class AccountWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(TITLE)
        root.configure(bg=BG)
        root.geometry("760x560")
        root.minsize(680, 480)

        self._build_header()
        self._build_table()
        self._build_form()
        self._build_status()
        self.refresh()

    # ------------------------------------------------------------- ส่วนประกอบ

    def _label(self, parent, text, *, fg=FG, size=10, bold=False, **kw):
        return tk.Label(parent, text=text, bg=kw.pop("bg", BG), fg=fg,
                        font=("Segoe UI", size, "bold" if bold else "normal"), **kw)

    def _build_header(self) -> None:
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=16, pady=(14, 6))
        self._label(head, "บัญชี Google Flow", size=15, bold=True).pack(anchor="w")
        self._label(
            head,
            f"ระบบจะสลับไปใบถัดไปเองเมื่อเครดิตเหลือน้อยกว่า "
            f"{flow_accounts.CREDIT_PER_CLIP} หน่วย (ใช้ต่อคลิป)",
            fg=DIM,
        ).pack(anchor="w")
        self._label(
            head,
            "รหัสผ่านเข้ารหัสด้วยบัญชี Windows เครื่องนี้ — "
            "ก๊อปไฟล์ไปเครื่องอื่นเปิดไม่ได้ และไม่ถูกส่งออกนอกเครื่อง",
            fg=DIM,
        ).pack(anchor="w", pady=(2, 0))

    def _build_table(self) -> None:
        wrap = tk.Frame(self.root, bg=CARD, highlightthickness=0)
        wrap.pack(fill="both", expand=True, padx=16, pady=8)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("A.Treeview", background=CARD, fieldbackground=CARD,
                        foreground=FG, rowheight=28, borderwidth=0)
        style.configure("A.Treeview.Heading", background="#252a33", foreground=DIM,
                        borderwidth=0, font=("Segoe UI", 9))
        style.map("A.Treeview", background=[("selected", "#2f6fd0")])

        columns = ("email", "credits", "state", "note")
        self.tree = ttk.Treeview(wrap, columns=columns, show="headings",
                                 style="A.Treeview", selectmode="browse")
        for key, text, width in (("email", "อีเมล", 250),
                                 ("credits", "เครดิตล่าสุด", 110),
                                 ("state", "สถานะ", 150),
                                 ("note", "หมายเหตุ", 200)):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width,
                             anchor="e" if key == "credits" else "w")
        self.tree.pack(fill="both", expand=True, side="left")
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        bar.pack(fill="y", side="right")
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.bind("<<TreeviewSelect>>", self._on_pick)

    def _entry(self, parent, *, width=34, secret=False):
        """ช่องกรอกที่ **เห็นขอบชัด** — ของเดิมไม่มีขอบบนพื้นมืด มองไม่ออกว่าช่องอยู่ไหน"""
        return tk.Entry(
            parent, width=width, bg=CARD, fg=FG, insertbackground=FG,
            relief="solid", borderwidth=1, highlightthickness=1,
            highlightbackground="#39404b", highlightcolor="#2f6fd0",
            show="●" if secret else "", font=("Segoe UI", 10),
        )

    def _build_form(self) -> None:
        form = tk.Frame(self.root, bg=BG)
        form.pack(fill="x", padx=16, pady=(0, 4))

        self._label(form, "อีเมล").grid(row=0, column=0, sticky="w", pady=4)
        self.email = self._entry(form)
        self.email.grid(row=0, column=1, sticky="we", padx=(8, 14), ipady=4)

        self._label(form, "หมายเหตุ").grid(row=0, column=2, sticky="w")
        self.note = self._entry(form, width=22)
        self.note.grid(row=0, column=3, sticky="we", padx=(8, 0), ipady=4)

        self._label(form, "รหัสผ่าน").grid(row=1, column=0, sticky="w", pady=4)
        self.password = self._entry(form, secret=True)
        self.password.grid(row=1, column=1, sticky="we", padx=(8, 14), ipady=4)

        self.show = tk.BooleanVar(value=False)
        tk.Checkbutton(form, text="ให้เห็นรหัส", variable=self.show,
                       command=self._toggle_show, bg=BG, fg=DIM,
                       selectcolor=CARD, activebackground=BG, activeforeground=FG,
                       font=("Segoe UI", 9), borderwidth=0,
                       highlightthickness=0).grid(row=1, column=2, sticky="w")

        # แถวโปรไฟล์ต้องอยู่คอลัมน์เดียวกับช่องอื่น ไม่งั้นมันลอยเยื้องไปคนละแนว
        self._label(form, "โปรไฟล์ Chrome").grid(row=2, column=0, sticky="w", pady=4)
        self.profile = self._entry(form)
        self.profile.grid(row=2, column=1, sticky="we", padx=(8, 14), ipady=4)
        self._label(form, "ไม่ใส่ก็ได้", fg=DIM, size=9).grid(
            row=2, column=2, sticky="w")
        form.grid_columnconfigure(1, weight=1)
        form.grid_columnconfigure(3, weight=1)

        buttons = tk.Frame(self.root, bg=BG)
        buttons.pack(fill="x", padx=16, pady=(6, 4))
        for text, command, color in (
            ("💾 บันทึก", self.save, "#2f6fd0"),
            ("🧹 ล้างช่อง", self.clear, "#3a3f48"),
            ("▶ ตั้งเป็นใบที่ใช้อยู่", self.make_current, "#3a3f48"),
            ("⏸ พัก / ใช้ต่อ", self.toggle_disabled, "#3a3f48"),
            ("🗑 ลบบัญชีนี้", self.delete, "#7a2b2b"),
        ):
            tk.Button(buttons, text=text, command=command, bg=color, fg=FG,
                      relief="flat", font=("Segoe UI", 10), padx=14, pady=6,
                      activebackground=color, activeforeground=FG,
                      cursor="hand2").pack(side="left", padx=(0, 8))

    def _build_status(self) -> None:
        self.status = self._label(self.root, "", fg=DIM)
        self.status.pack(anchor="w", padx=16, pady=(0, 12))

    # ----------------------------------------------------------------- ทำงาน

    def _toggle_show(self) -> None:
        self.password.configure(show="" if self.show.get() else "●")

    def _say(self, text: str, colour: str = DIM) -> None:
        self.status.configure(text=text, fg=colour)

    def refresh(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)
        data = flow_accounts.board()
        for row in data["accounts"]:
            if row["disabled"]:
                state = "พักไว้" + (f" — {row['disabled_why']}"
                                    if row["disabled_why"] else "")
            elif row["enough"] is False:
                state = "เครดิตไม่พอ"
            elif row["is_current"]:
                state = "ใช้อยู่ตอนนี้"
            else:
                state = "พร้อมใช้"
            credits = "ยังไม่รู้" if row["credits"] is None else f"{row['credits']:,}"
            self.tree.insert(
                "", "end", iid=row["email"],
                values=(row["email"], credits, state, row["note"]))
        if data["count"]:
            self._say(f"เก็บไว้ {data['count']} ใบ · ใช้ได้ {data['usable']} ใบ"
                      + (f" · ใช้อยู่: {flow_accounts.mask(data['current'])}"
                         if data["current"] else " · ยังไม่ได้ตั้งว่าใช้ใบไหน"))
        else:
            self._say("ยังไม่มีบัญชีเลย — กรอกอีเมลกับรหัสผ่านข้างล่างแล้วกดบันทึก")

    def _picked(self) -> str:
        rows = self.tree.selection()
        return rows[0] if rows else ""

    def _on_pick(self, _event=None) -> None:
        email = self._picked()
        if not email:
            return
        # **ไม่เติมรหัสผ่านกลับเข้าช่อง** — เก็บแล้วดูย้อนไม่ได้ ตั้งใหม่ได้อย่างเดียว
        self.email.delete(0, "end"); self.email.insert(0, email)
        row = next((r for r in flow_accounts.board()["accounts"]
                    if r["email"] == email), {})
        self.note.delete(0, "end"); self.note.insert(0, row.get("note", ""))
        self.profile.delete(0, "end"); self.profile.insert(0, row.get("profile", ""))
        self.password.delete(0, "end")
        self._say(f"เลือก {flow_accounts.mask(email)} — "
                  "เว้นช่องรหัสผ่านไว้ถ้าไม่ต้องการเปลี่ยน")

    def clear(self) -> None:
        for field in (self.email, self.password, self.note, self.profile):
            field.delete(0, "end")
        self.tree.selection_remove(self.tree.selection())
        self._say("ล้างช่องแล้ว")

    def save(self) -> None:
        email = self.email.get().strip()
        password = self.password.get()
        known = flow_accounts.emails()

        if not password and email in known:
            # แก้เฉพาะหมายเหตุ/โปรไฟล์ ไม่ต้องพิมพ์รหัสซ้ำ
            try:
                password = flow_accounts.password_for(email)
            except flow_accounts.FlowAccountError as error:
                messagebox.showerror(TITLE, str(error)); return
        try:
            message = flow_accounts.add(email, password,
                                        self.note.get().strip(),
                                        self.profile.get().strip())
        except flow_accounts.FlowAccountError as error:
            messagebox.showerror(TITLE, str(error))
            return

        # **อ่านกลับมายืนยันว่าเก็บได้จริง** ไม่ใช่เชื่อว่าเขียนสำเร็จ (กติกาข้อ 2.3.1)
        try:
            saved_ok = flow_accounts.password_for(email) == password
        except flow_accounts.FlowAccountError:
            saved_ok = False
        del password
        self.password.delete(0, "end")
        if not saved_ok:
            messagebox.showerror(
                TITLE, "บันทึกแล้วแต่อ่านกลับมาไม่ตรง — ยังใช้ไม่ได้\n"
                       "ลองใหม่อีกครั้ง ถ้ายังไม่หายให้แจ้ง")
            return
        self.refresh()
        self._say(f"{message} · อ่านกลับมาตรวจแล้วใช้ได้จริง", OK)

    def make_current(self) -> None:
        email = self._picked()
        if not email:
            self._say("เลือกบัญชีในตารางก่อน", WARN); return
        flow_accounts.set_current(email)
        self.refresh()
        self._say(f"ตั้งให้ใช้ {flow_accounts.mask(email)} แล้ว", OK)

    def toggle_disabled(self) -> None:
        email = self._picked()
        if not email:
            self._say("เลือกบัญชีในตารางก่อน", WARN); return
        row = next((r for r in flow_accounts.board()["accounts"]
                    if r["email"] == email), {})
        now_off = bool(row.get("disabled"))
        flow_accounts.set_disabled(email, not now_off,
                                   "" if now_off else "เจ้าของสั่งพักจากหน้าต่าง")
        self.refresh()
        self._say(("เอากลับมาใช้แล้ว: " if now_off else "พักไว้แล้ว: ")
                  + flow_accounts.mask(email), OK)

    def delete(self) -> None:
        email = self._picked()
        if not email:
            self._say("เลือกบัญชีในตารางก่อน", WARN); return
        if not messagebox.askyesno(
                TITLE, f"ลบบัญชี {email} ออกจากที่เก็บ?\n\n"
                       "รหัสผ่านที่เก็บไว้จะหายไปด้วย ต้องกรอกใหม่ถ้าจะใช้อีก"):
            return
        try:
            message = flow_accounts.remove(email)
        except flow_accounts.FlowAccountError as error:
            messagebox.showerror(TITLE, str(error)); return
        self.clear()
        self.refresh()
        self._say(message, OK)


def main() -> int:
    try:
        root = tk.Tk()
    except tk.TclError as error:
        print("เปิดหน้าต่างไม่ได้ (เครื่องนี้ไม่มีจอให้วาด):", error)
        print("ใช้แบบพิมพ์คำสั่งแทนได้: python flow_accounts.py add อีเมล")
        return 1
    AccountWindow(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
