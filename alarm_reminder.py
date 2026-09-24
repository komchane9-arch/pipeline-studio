"""Windows desktop reminder. Run with pythonw alarm_reminder.py."""
from pathlib import Path
import math
import struct
import time
import tkinter as tk
from tkinter import ttk, messagebox
import wave
import winsound


def make_sound(path):
    rate = 22050
    samples = bytearray()
    for i in range(rate * 2):
        t = i / rate
        phase = t % 0.5
        envelope = min(1, phase / 0.02, max(0, (0.35 - phase) / 0.04))
        frequency = 880 if int(t * 2) % 2 == 0 else 660
        samples.extend(struct.pack('<h', int(12000 * envelope * math.sin(2 * math.pi * frequency * t))))
    with wave.open(str(path), 'wb') as sound:
        sound.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        sound.writeframes(samples)


class Reminder:
    def __init__(self, root):
        self.root = root
        self.active = False
        self.deadline = None
        self.popup = None
        self.silence_job = None
        self.sound = Path(__file__).with_name('alarm_reminder.wav')
        make_sound(self.sound)
        root.title('Alarm — เตือนทุก 10 นาที')
        root.geometry('440x310')
        root.resizable(False, False)
        root.protocol('WM_DELETE_WINDOW', self.close)
        frame = ttk.Frame(root, padding=24)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='นาฬิกาแจ้งเตือน', font=('Tahoma', 20)).pack(pady=(0, 12))
        row = ttk.Frame(frame)
        row.pack()
        ttk.Label(row, text='เตือนทุก').pack(side='left', padx=6)
        self.minutes = tk.StringVar(value='10')
        ttk.Entry(row, textvariable=self.minutes, width=8).pack(side='left')
        ttk.Label(row, text='นาที').pack(side='left', padx=6)
        self.status = tk.StringVar()
        ttk.Label(frame, textvariable=self.status, font=('Tahoma', 16)).pack(pady=20)
        buttons = ttk.Frame(frame)
        buttons.pack()
        ttk.Button(buttons, text='เริ่มแจ้งเตือนใหม่', command=self.start).pack(side='left', padx=3)
        ttk.Button(buttons, text='หยุดการเตือน', command=self.stop).pack(side='left', padx=3)
        ttk.Button(buttons, text='ทดสอบเสียง', command=self.ring).pack(side='left', padx=3)
        ttk.Label(frame, text='ย่อหน้าต่างได้ • ปิดหน้าต่างเพื่อออกจากโปรแกรม\nเสียงดังไม่เกิน 30 วินาที หรือกดรับทราบเพื่อปิดเสียง',
                  justify='center').pack(pady=18)
        self.start()
        self.tick()

    def start(self):
        try:
            minutes = float(self.minutes.get())
            if not math.isfinite(minutes) or not 0.05 <= minutes <= 1440:
                raise ValueError
        except ValueError:
            messagebox.showerror('เวลาไม่ถูกต้อง', 'กรุณาใส่เวลา 0.05–1440 นาที', parent=self.root)
            return
        self.dismiss()
        self.interval = minutes * 60
        self.deadline = time.monotonic() + self.interval
        self.active = True

    def stop(self):
        self.active = False
        self.dismiss()
        self.status.set('หยุดการแจ้งเตือนแล้ว')

    def silence(self):
        winsound.PlaySound(None, 0)
        if self.silence_job is not None:
            self.root.after_cancel(self.silence_job)
            self.silence_job = None

    def dismiss(self):
        self.silence()
        if self.popup is not None:
            self.popup.destroy()
            self.popup = None

    def ring(self):
        if self.popup is None:
            self.popup = tk.Toplevel(self.root)
            self.popup.title('ถึงเวลาแจ้งเตือนแล้ว')
            self.popup.geometry('380x180')
            self.popup.attributes('-topmost', True)
            self.popup.protocol('WM_DELETE_WINDOW', self.dismiss)
            ttk.Label(self.popup, text='ถึงเวลาแจ้งเตือนแล้วครับ!', font=('Tahoma', 18)).pack(pady=30)
            ttk.Button(self.popup, text='รับทราบ / ปิดเสียง', command=self.dismiss).pack()
        self.popup.deiconify()
        self.popup.lift()
        self.silence()
        try:
            winsound.PlaySound(str(self.sound), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
        except RuntimeError:
            self.status.set('เล่นเสียงไม่ได้ — ตรวจสอบอุปกรณ์เสียง')
        self.silence_job = self.root.after(30000, self.silence)

    def tick(self):
        if self.active:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                self.deadline = time.monotonic() + self.interval
                self.ring()
                remaining = self.interval
            seconds = math.ceil(remaining)
            self.status.set(f'แจ้งเตือนใน {seconds // 60:02d}:{seconds % 60:02d}')
        self.root.after(200, self.tick)

    def close(self):
        self.stop()
        self.root.destroy()


if __name__ == '__main__':
    window = tk.Tk()
    Reminder(window)
    window.mainloop()
