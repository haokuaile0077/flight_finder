"""轻量日期与城市选择控件，全部使用Tkinter标准库。"""
import calendar
from datetime import date
import tkinter as tk
from tkinter import ttk


class DateField(ttk.Frame):
    def __init__(self, master, variable: tk.StringVar):
        super().__init__(master, style="Card.TFrame")
        self.variable = variable
        self.entry = ttk.Entry(self, textvariable=variable, width=12)
        self.entry.pack(side="left", fill="x", expand=True)
        self.button = ttk.Button(self, text="日历", width=4, command=self.open_calendar)
        self.button.pack(side="right", padx=(4, 0))
        self.popup = None

    def set_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.entry.configure(state=state)
        self.button.configure(state=state)

    def open_calendar(self):
        if self.popup and self.popup.winfo_exists():
            self.popup.lift()
            return
        try:
            selected = date.fromisoformat(self.variable.get())
        except ValueError:
            selected = date(2026, 11, 10)
        win = tk.Toplevel(self)
        self.popup = win
        win.title("选择日期")
        win.transient(self.winfo_toplevel())
        win.resizable(False, False)
        win.geometry(f"+{max(0, self.winfo_rootx())}+{max(0, self.winfo_rooty()+34)}")
        month = [selected.year, selected.month]
        head = ttk.Frame(win, padding=10)
        head.pack(fill="x")
        title = ttk.Label(head, anchor="center", width=16)
        body = ttk.Frame(win, padding=(10, 0, 10, 10))
        body.pack()

        def choose(value):
            self.variable.set(value.isoformat())
            win.destroy()
            self.entry.focus_set()

        def render():
            title.configure(text=f"{month[0]}年 {month[1]}月")
            for child in body.winfo_children():
                child.destroy()
            for column, label in enumerate("一二三四五六日"):
                ttk.Label(body, text=label, anchor="center", width=4).grid(row=0, column=column, pady=4)
            for row, week in enumerate(calendar.monthcalendar(*month), 1):
                for column, day in enumerate(week):
                    if day:
                        value = date(month[0], month[1], day)
                        ttk.Button(body, text=str(day), width=4,
                                   style="Primary.TButton" if value == selected else "TButton",
                                   command=lambda v=value: choose(v)).grid(row=row, column=column, padx=1, pady=1)

        def move(delta):
            value = month[0]*12 + month[1]-1 + delta
            year, index = divmod(value, 12)
            if 1 <= year <= 9999:
                month[:] = year, index+1
                render()
        ttk.Button(head, text="‹", width=3, command=lambda: move(-1)).pack(side="left")
        title.pack(side="left", expand=True)
        ttk.Button(head, text="›", width=3, command=lambda: move(1)).pack(side="right")
        ttk.Label(win, text="也可直接输入 YYYY-MM-DD", padding=(10, 0, 10, 10)).pack()
        win.bind("<Escape>", lambda _e: win.destroy())
        render()
        win.grab_set()
        win.focus_set()


def choose_cities(parent, title: str, cities: tuple[str, ...], selected: tuple[str, ...], on_confirm):
    """复选框多选，不需要按住Ctrl，取消不会改变原选择。"""
    win = tk.Toplevel(parent)
    win.title(title)
    win.transient(parent)
    win.resizable(False, False)
    frame = ttk.Frame(win, padding=18)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=title, style="Heading.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))
    variables = {city: tk.BooleanVar(value=city in selected) for city in cities}
    for index, (city, variable) in enumerate(variables.items()):
        ttk.Checkbutton(frame, text=city, variable=variable).grid(row=1+index//3, column=index%3, padx=12, pady=8, sticky="w")
    row = 2+(len(cities)+2)//3
    def set_all(value):
        for variable in variables.values():
            variable.set(value)
    ttk.Button(frame, text="全选", command=lambda: set_all(True)).grid(row=row, column=0, pady=10)
    ttk.Button(frame, text="清空", command=lambda: set_all(False)).grid(row=row, column=1)
    def confirm():
        on_confirm(tuple(c for c in cities if variables[c].get()))
        win.destroy()
    ttk.Button(frame, text="确认选择", style="Primary.TButton", command=confirm).grid(row=row+1, column=2, pady=8)
    ttk.Button(frame, text="取消", command=win.destroy).grid(row=row+1, column=1)
    ttk.Label(frame, text="勾选所需城市，不需要按住Ctrl。", style="Muted.TLabel").grid(row=row+2, column=0, columnspan=3, pady=4)
    win.bind("<Escape>", lambda _e: win.destroy())
    win.grab_set()
    win.focus_set()
    return win
