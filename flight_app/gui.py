"""Tkinter桌面界面。无网络、浏览器及HTTP服务依赖。"""
import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .errors import FlightAppError
from .exporting import export_quotes
from .models import Quote, SearchCriteria, SortOrder
from .presentation import detail_text, leg_label, money
from .provider import JsonFlightProvider
from .service import SearchService
from .validation import parse_budget, parse_date

BG = "#F3F6FA"
INK = "#162B45"
MUTED = "#5C7088"
BLUE = "#2563EB"


class FlightApp:
    def __init__(self, root: tk.Tk, provider: JsonFlightProvider):
        self.root, self.provider = root, provider
        self.service = SearchService(provider)
        self.results: tuple[Quote, ...] = ()
        self.last_criteria: SearchCriteria | None = None
        self._pending: str | None = None
        self._layout_job: str | None = None
        self._busy = False
        root.title("航迹 · 本地机票查询  |  INT6181")
        width = min(1220, max(1030, root.winfo_screenwidth()-80))
        height = min(820, max(650, root.winfo_screenheight()-100))
        root.geometry(f"{width}x{height}")
        root.minsize(1030, 650)
        root.configure(background=BG)
        self._style()
        self.trip = tk.StringVar(value="单程")
        self.origin = tk.StringVar(value="深圳" if "深圳" in provider.cities else (provider.cities[0] if provider.cities else ""))
        self.destination = tk.StringVar(value="北京" if "北京" in provider.cities else (provider.cities[-1] if provider.cities else ""))
        initial = provider.dates[min(9, len(provider.dates)-1)] if provider.dates else None
        return_initial = provider.dates[min(14, len(provider.dates)-1)] if provider.dates else None
        self.dep_date = tk.StringVar(value=initial.isoformat() if initial else "2026-11-10")
        self.ret_date = tk.StringVar(value=return_initial.isoformat() if return_initial else "2026-11-15")
        self.budget = tk.StringVar()
        self.airline = tk.StringVar(value="不限")
        self.direct = tk.BooleanVar(value=False)
        self.sort_order = tk.StringVar(value=SortOrder.PRICE.value)
        self.status = tk.StringVar(value="选择条件后点击查询。默认示例：深圳 → 北京，2026-11-10。")
        self.summary = tk.StringVar(value="查询结果")
        self.count = tk.StringVar(value="尚未查询")
        self.selected_price = tk.StringVar(value="—")
        self.selected_route = tk.StringVar(value="选中一条结果查看行程")
        self._build()
        self.trip.trace_add("write", lambda *_: self._trip_changed())
        self._trip_changed()
        root.bind("<Return>", self._enter_search)
        root.protocol("WM_DELETE_WINDOW", self.close)

    def _style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        import tkinter.font as tkfont
        available = set(tkfont.families())
        family = next((f for f in ("Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC", "PingFang SC", "Arial") if f in available), "TkDefaultFont")
        self.family = family
        for named in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            tkfont.nametofont(named).configure(family=family, size=10)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background="white")
        style.configure("TLabel", background=BG, foreground=INK, font=(family, 10))
        style.configure("Card.TLabel", background="white", foreground=INK)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(family, 9))
        style.configure("CardMuted.TLabel", background="white", foreground=MUTED, font=(family, 9))
        style.configure("Title.TLabel", font=(family, 24, "bold"), foreground=INK)
        style.configure("Heading.TLabel", font=(family, 12, "bold"), foreground=INK)
        style.configure("Price.TLabel", background="white", foreground=BLUE, font=(family, 22, "bold"))
        style.configure("TButton", padding=(12, 8), font=(family, 10), background="#E7EDF5", foreground=INK, borderwidth=0)
        style.configure("Primary.TButton", background=BLUE, foreground="white", padding=(22, 9), font=(family, 11, "bold"))
        style.map("Primary.TButton", background=[("disabled", "#A6B9D6"), ("active", "#1D4ED8")], foreground=[("disabled", "white")])
        style.configure("TRadiobutton", background="white", foreground=INK)
        style.configure("TCheckbutton", background="white", foreground=INK)
        style.configure("TEntry", padding=7, fieldbackground="#F7F9FC")
        style.configure("TCombobox", padding=6, fieldbackground="#F7F9FC", arrowsize=14)
        style.map("TCombobox", fieldbackground=[("readonly", "#F7F9FC")], selectbackground=[("readonly", "#F7F9FC")], selectforeground=[("readonly", INK)])
        style.configure("Treeview", rowheight=46, background="white", fieldbackground="white", foreground=INK, font=(family, 9), borderwidth=0)
        style.configure("Treeview.Heading", background="#EAF0F7", foreground=MUTED, font=(family, 9, "bold"), padding=(5, 11), relief="flat")
        style.map("Treeview", background=[("selected", "#DCE9FF")], foreground=[("selected", "#15376B")])

    def _build(self):
        page = ttk.Frame(self.root, padding=(24, 18, 24, 12))
        page.pack(fill="both", expand=True)
        header = ttk.Frame(page)
        header.pack(fill="x", pady=(0, 12))
        ttk.Label(header, text="航迹", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="  FLIGHT FINDER / 本地教学版", style="Muted.TLabel").pack(side="left", padx=10, pady=(9, 0))
        ttk.Label(header, text="1名成人  ·  经济舱  ·  北京时间", style="Muted.TLabel").pack(side="right", pady=(9, 0))
        notice = tk.Label(page, text="模拟数据，仅供教学演示。所有航司、航班和票价均为虚构，不提供购买服务。", bg="#FFF2D8", fg="#855C17", anchor="w", padx=12, pady=9, font=(self.family, 9))
        notice.pack(fill="x", pady=(0, 12))
        card = ttk.Frame(page, style="Card.TFrame", padding=16)
        card.pack(fill="x")
        top = ttk.Frame(card, style="Card.TFrame")
        top.pack(fill="x", pady=(0, 12))
        for trip in ("单程", "往返"):
            ttk.Radiobutton(top, text=trip, value=trip, variable=self.trip).pack(side="left", padx=(0, 18))
        ttk.Label(top, text="数据覆盖  2026-11-01 至 2026-11-30", style="CardMuted.TLabel").pack(side="right")
        fields = ttk.Frame(card, style="Card.TFrame")
        fields.pack(fill="x")
        for col, weight in ((0, 2), (1, 0), (2, 2), (3, 2), (4, 2)):
            fields.columnconfigure(col, weight=weight)
        for col, label in ((0, "出发城市"), (2, "到达城市"), (3, "出发日期 YYYY-MM-DD"), (4, "返程日期 YYYY-MM-DD")):
            ttk.Label(fields, text=label, style="CardMuted.TLabel").grid(row=0, column=col, sticky="w", padx=(0, 12), pady=(0, 5))
        self.origin_box = ttk.Combobox(fields, textvariable=self.origin, values=self.provider.cities, state="readonly", width=14)
        self.origin_box.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(fields, text="⇄", command=self.swap, width=3).grid(row=1, column=1, padx=(0, 8))
        self.destination_box = ttk.Combobox(fields, textvariable=self.destination, values=self.provider.cities, state="readonly", width=14)
        self.destination_box.grid(row=1, column=2, sticky="ew", padx=(0, 12))
        ttk.Entry(fields, textvariable=self.dep_date, width=16).grid(row=1, column=3, sticky="ew", padx=(0, 12))
        self.return_entry = ttk.Entry(fields, textvariable=self.ret_date, width=16)
        self.return_entry.grid(row=1, column=4, sticky="ew")
        options = ttk.Frame(card, style="Card.TFrame")
        options.pack(fill="x", pady=(14, 0))
        ttk.Label(options, text="预算上限 ¥", style="Card.TLabel").pack(side="left")
        ttk.Entry(options, textvariable=self.budget, width=11).pack(side="left", padx=(6, 14))
        ttk.Label(options, text="全程航司", style="Card.TLabel").pack(side="left")
        ttk.Combobox(options, textvariable=self.airline, values=("不限",)+self.provider.airlines, state="readonly", width=17).pack(side="left", padx=(6, 14))
        ttk.Checkbutton(options, text="仅看直飞", variable=self.direct).pack(side="left", padx=(0, 14))
        self.search_button = ttk.Button(options, text="查询航班", style="Primary.TButton", command=self.search)
        self.search_button.pack(side="right")
        ttk.Button(options, text="恢复示例", command=self.reset).pack(side="right", padx=(0, 10))
        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(15, 10))
        ttk.Label(bar, textvariable=self.summary, style="Heading.TLabel").pack(side="left")
        ttk.Label(bar, textvariable=self.count, style="Muted.TLabel").pack(side="left", padx=12)
        self.export_button = ttk.Button(bar, text="导出 CSV", command=self.export, state="disabled")
        self.export_button.pack(side="right")
        self.sort_box = ttk.Combobox(bar, textvariable=self.sort_order, values=tuple(s.value for s in SortOrder), state="readonly", width=20)
        self.sort_box.pack(side="right", padx=10)
        self.sort_box.bind("<<ComboboxSelected>>", self.resort)
        self.body = ttk.Panedwindow(page, orient="horizontal")
        self.body.pack(fill="both", expand=True)
        left = ttk.Frame(self.body, style="Card.TFrame")
        right = ttk.Frame(self.body, style="Card.TFrame", padding=14)
        self.body.add(left, weight=3)
        self.body.add(right, weight=1)
        columns = ("out", "back", "airline", "type", "price")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        for col, label, width in (("out", "去程 / 起降", 185), ("back", "返程 / 起降", 185), ("airline", "航司", 135), ("type", "行程", 70), ("price", "合计 ¥", 95)):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, minwidth=65, anchor="e" if col=="price" else "w")
        ys = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        left.rowconfigure(0, weight=1); left.columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns"); xs.grid(row=1, column=0, sticky="ew")
        self.tree.tag_configure("alternate", background="#F7F9FC")
        self.tree.bind("<<TreeviewSelect>>", self.show_selected)
        ttk.Label(right, text="行程详情", style="Card.TLabel", font=(self.family, 12, "bold")).pack(anchor="w")
        ttk.Label(right, textvariable=self.selected_route, style="CardMuted.TLabel", wraplength=260).pack(anchor="w", pady=(8, 4))
        ttk.Label(right, textvariable=self.selected_price, style="Price.TLabel").pack(anchor="w", pady=(0, 8))
        detail_frame = ttk.Frame(right, style="Card.TFrame")
        detail_frame.pack(fill="both", expand=True)
        self.details = tk.Text(detail_frame, width=31, wrap="word", relief="flat", borderwidth=0,
                               background="white", foreground=INK, font=(self.family, 9), padx=0, pady=4,
                               spacing1=2, spacing3=4, state="disabled")
        scrollbar = ttk.Scrollbar(detail_frame, orient="vertical", command=self.details.yview)
        self.details.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y");self.details.pack(side="left", fill="both", expand=True)
        self._set_details("输入查询条件后点击「查询航班」。\n\n试一试：\n深圳 → 北京\n出发 2026-11-10\n返程 2026-11-15\n\n预算留空表示不限。\n航司筛选适用于行程的每一个航段。\n跨日到达会标记 +1天。")
        bottom = ttk.Frame(page)
        # 优先给状态栏预留空间，避免小窗口中被可扩张的结果区挤掉。
        bottom.pack(side="bottom", fill="x", pady=(10, 0), before=self.body)
        self.status_label = ttk.Label(bottom, textvariable=self.status, style="Muted.TLabel", wraplength=950)
        self.status_label.pack(anchor="w")
        self._layout_job = self.root.after(80, self._initial_split)

    def _initial_split(self):
        self._layout_job = None
        width = self.body.winfo_width()
        if width < 900:
            self._layout_job = self.root.after(25, self._initial_split)
            return
        self.body.sashpos(0, width-310)

    def _trip_changed(self):
        self.return_entry.configure(state="normal" if self.trip.get()=="往返" else "disabled")

    def _enter_search(self, event):
        if event.widget is self.details:
            return
        self.search()

    def swap(self):
        a, b = self.origin.get(), self.destination.get()
        self.origin.set(b);self.destination.set(a)

    def reset(self):
        if self._busy:
            return
        self.trip.set("单程");self.origin.set("深圳");self.destination.set("北京")
        self.dep_date.set("2026-11-10");self.ret_date.set("2026-11-15")
        self.budget.set("");self.direct.set(False);self.airline.set("不限");self.sort_order.set(SortOrder.PRICE.value)
        self._clear_results()
        self.status.set("已恢复默认示例，点击查询。")

    def _criteria(self):
        return SearchCriteria(self.origin.get(), self.destination.get(), parse_date(self.dep_date.get(), "出发日期"),
                              parse_date(self.ret_date.get(), "返程日期") if self.trip.get()=="往返" else None,
                              parse_budget(self.budget.get()), self.direct.get(),
                              None if self.airline.get()=="不限" else self.airline.get(), SortOrder(self.sort_order.get()))

    def _clear_results(self):
        self.results = ();self.last_criteria = None
        self.tree.delete(*self.tree.get_children())
        self.export_button.configure(state="disabled")
        self.count.set("尚无结果");self.summary.set("查询结果")
        self.selected_route.set("选中一条结果查看行程");self.selected_price.set("—")
        self._set_details("尚无可显示的行程。")

    def search(self):
        if self._busy:
            return
        self._clear_results()
        try:
            criteria = self._criteria()
        except FlightAppError as exc:
            self.status.set(str(exc));messagebox.showwarning("请检查查询条件", str(exc), parent=self.root)
            return
        self._busy = True
        self.search_button.configure(state="disabled")
        self.export_button.configure(state="disabled")
        self.status.set("正在查询本地模拟航班…")
        # 单日期本地查询规模受控；延后一次事件，让状态先显示。
        self._pending = self.root.after(30, lambda: self._run_search(criteria))

    def _run_search(self, criteria):
        self._pending = None
        try:
            results = self.service.search(criteria)
            self.results, self.last_criteria = results, criteria
            self._render_results()
        except FlightAppError as exc:
            self.status.set(str(exc));messagebox.showwarning("查询未完成", str(exc), parent=self.root)
        except Exception:
            logging.exception("Unexpected search error")
            self.status.set("查询发生未预期错误，请检查终端记录。")
            messagebox.showerror("查询异常", "查询未完成，详细错误已输出到终端。", parent=self.root)
        finally:
            self._busy = False
            self.search_button.configure(state="normal")

    def _render_results(self):
        self.tree.delete(*self.tree.get_children())
        for index, q in enumerate(self.results):
            a, b = q.itinerary.outbound, q.itinerary.inbound
            airlines = " / ".join(dict.fromkeys(s.airline.replace("（模拟）", "") for leg in q.itinerary.legs for s in leg.segments))
            kind = "全程直飞" if all(f.direct for f in q.itinerary.legs) else "含中转"
            self.tree.insert("", "end", iid=str(index), values=(leg_label(a), leg_label(b), airlines, kind, money(q.final_price_cents)), tags=("alternate",) if index%2 else ())
        c = self.last_criteria
        self.summary.set(f"{c.origin} → {c.destination}  {'往返组合' if c.return_date else '单程'}")
        self.count.set(f"{len(self.results)} 条结果")
        self.export_button.configure(state="normal" if self.results else "disabled")
        if self.results:
            self.tree.selection_set("0");self.tree.focus("0");self.show_selected()
            self.status.set(f"已显示查询快照：{c.departure_date}，{'返程 '+str(c.return_date)+'，' if c.return_date else ''}共{len(self.results)}条。修改条件后需重新查询。")
        else:
            self.selected_route.set("没有符合条件的行程");self.selected_price.set("—")
            self._set_details("未找到匹配航班。\n\n请检查数据覆盖日期、航线或放宽预算、航司及直飞条件。\n\n模拟数据仅覆盖2026年11月。")
            self.status.set("没有符合条件的行程；未超售的航班才会出现在结果中。")

    def resort(self, event=None):
        if not self.last_criteria or self._busy:
            return
        from dataclasses import replace
        from .filters import sort_quotes
        self.last_criteria = replace(self.last_criteria, sort_order=SortOrder(self.sort_order.get()))
        self.results = sort_quotes(list(self.results), self.last_criteria.sort_order)
        self._render_results()

    def _set_details(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end");self.details.insert("1.0", text)
        self.details.configure(state="disabled");self.details.yview_moveto(0)

    def show_selected(self, event=None):
        selection = self.tree.selection()
        if not selection:
            return
        q = self.results[int(selection[0])]
        self.selected_route.set(f"{q.itinerary.outbound.origin.city} → {q.itinerary.outbound.destination.city}" + (" → "+q.itinerary.inbound.destination.city if q.itinerary.inbound else ""))
        self.selected_price.set(f"¥ {money(q.final_price_cents)}")
        self._set_details(detail_text(q))

    def export(self):
        if not self.results or self.last_criteria is None:
            return
        path = filedialog.asksaveasfilename(parent=self.root, title="导出当前查询结果", defaultextension=".csv", filetypes=[("CSV文件", "*.csv")], initialfile="模拟机票查询结果.csv")
        if not path:
            return
        try:
            count = export_quotes(Path(path), self.results, self.last_criteria)
            self.status.set(f"已导出{count}条查询快照：{path}")
        except (OSError, UnicodeError, ValueError) as exc:
            messagebox.showerror("导出失败", f"请检查路径和写入权限，或关闭占用文件的程序。\n{exc}", parent=self.root)

    def close(self):
        if self._pending:
            self.root.after_cancel(self._pending)
        if self._layout_job:
            self.root.after_cancel(self._layout_job)
        self.root.destroy()
