"""桌面界面：常规查询与灵活低价，后台计算，主线程更新控件。"""
import logging
from dataclasses import replace
from pathlib import Path
from queue import Empty, Queue
from threading import Event, Thread
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .errors import FlightAppError, SearchCancelled
from .exporting import export_quotes, export_range_quotes
from .filters import sort_quotes
from .models import Quote, RangeCriteria, SearchCriteria, SortOrder
from .presentation import detail_text, leg_label, money
from .provider import JsonFlightProvider
from .range_search import RangeSearchService
from .service import SearchService
from .validation import parse_budget, parse_date, validate_criteria
from .widgets import DateField, choose_cities

BG = "#F3F6FA"
INK = "#162B45"
MUTED = "#5C7088"
BLUE = "#2563EB"
PAGE_SIZE = 100


class FlightApp:
    def __init__(self, root: tk.Tk, provider: JsonFlightProvider, *,
                 range_service: RangeSearchService | None = None, discount_summary: str = "模拟优惠未配置"):
        self.root, self.provider = root, provider
        self.service = SearchService(provider)
        self.range_service = range_service
        bounds = (provider.dates[0], provider.dates[-1]) if provider.dates else None
        self.range_no_discount = RangeSearchService(self.service, provider.cities, date_bounds=bounds)
        self.discount_summary = discount_summary
        self.results: tuple[Quote, ...] = ()
        self.last_criteria: SearchCriteria | RangeCriteria | None = None
        self.last_discount_summary = ""
        self._pending = self._layout_job = None
        self._busy = self._closed = False
        self._serial = 0
        self._cancel = Event()
        self._queue = Queue()
        self._page = 0
        self._resetting = False
        root.title("航迹 · 机票查询与灵活低价  |  本地模拟版")
        root.geometry(f"{min(1320, max(1030, root.winfo_screenwidth()-80))}x{min(870, max(650, root.winfo_screenheight()-100))}")
        root.minsize(1030, 650)
        root.configure(background=BG)
        self._style()
        self.trip = tk.StringVar(value="单程")
        self.origin = tk.StringVar(value=self._default_city("深圳", 0))
        self.destination = tk.StringVar(value=self._default_city("北京", -1))
        self.dep_date = tk.StringVar(value=self._default_date(9, "2026-11-10"))
        self.ret_date = tk.StringVar(value=self._default_date(14, "2026-11-15"))
        self.range_start = tk.StringVar(value=self.dep_date.get())
        self.range_end = tk.StringVar(value=self.ret_date.get())
        self.range_origins = tuple(c for c in ("深圳", "广州", "珠海") if c in provider.cities) or (self.origin.get(),)
        self.range_destinations = (self.destination.get(),)
        self.origin_caption = tk.StringVar()
        self.destination_caption = tk.StringVar()
        self.use_discount = tk.BooleanVar(value=True)
        self.budget = tk.StringVar()
        self.airline = tk.StringVar(value="不限")
        self.direct = tk.BooleanVar(value=False)
        self.sort_order = tk.StringVar(value=SortOrder.PRICE.value)
        self.status = tk.StringVar(value="从左到右选择城市和日期，点击查询；也可按Enter。")
        self.summary = tk.StringVar(value="查询结果")
        self.count = tk.StringVar(value="尚未查询")
        self.cheapest = tk.StringVar(value="最低价 —")
        self.selected_price = tk.StringVar(value="—")
        self.selected_breakdown = tk.StringVar(value="原价与优惠将在查询后显示")
        self.selected_route = tk.StringVar(value="选中一条结果查看行程")
        self.page_label = tk.StringVar(value="第 0 / 0 页")
        self._build()
        self.trip.trace_add("write", lambda *_: self._trip_changed())
        self._trip_changed()
        self._city_captions()
        for variable in (self.origin, self.destination, self.dep_date, self.ret_date, self.trip,
                         self.range_start, self.range_end, self.budget, self.airline, self.direct, self.use_discount):
            variable.trace_add("write", lambda *_: self._mark_dirty())
        root.bind("<Return>", self._enter_search)
        root.bind("<Control-e>", lambda _e: self.export())
        root.bind("<Escape>", lambda _e: self.cancel_query())
        root.protocol("WM_DELETE_WINDOW", self.close)

    def _default_city(self, preferred, index):
        return preferred if preferred in self.provider.cities else self.provider.cities[index]

    def _default_date(self, index, fallback):
        dates = self.provider.dates
        return dates[min(index, len(dates)-1)].isoformat() if dates else fallback
    def _style(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        import tkinter.font as tkfont
        available = {f.casefold(): f for f in tkfont.families()}
        family = next((available[f.casefold()] for f in ("Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC", "PingFang SC", "Arial")
                       if f.casefold() in available), tkfont.nametofont("TkDefaultFont").actual("family"))
        self.family = family
        for named in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            tkfont.nametofont(named).configure(family=family, size=10)
        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background="white")
        style.configure("TLabel", background=BG, foreground=INK, font=(family, 10))
        style.configure("Card.TLabel", background="white", foreground=INK)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(family, 9))
        style.configure("CardMuted.TLabel", background="white", foreground=MUTED, font=(family, 9))
        style.configure("Title.TLabel", font=(family, 20, "bold"), foreground=INK)
        style.configure("Heading.TLabel", font=(family, 12, "bold"), foreground=INK)
        style.configure("Price.TLabel", background="white", foreground=BLUE, font=(family, 18, "bold"))
        style.configure("TButton", padding=(9, 4), font=(family, 10), background="#E7EDF5", foreground=INK, borderwidth=0)
        style.configure("Primary.TButton", background=BLUE, foreground="white", padding=(18, 5), font=(family, 11, "bold"))
        style.map("Primary.TButton", background=[("disabled", "#A6B9D6"), ("active", "#1D4ED8")], foreground=[("disabled", "white")])
        style.configure("Horizontal.TProgressbar", thickness=5)
        style.configure("TRadiobutton", background="white", foreground=INK)
        style.configure("TCheckbutton", background="white", foreground=INK)
        style.configure("TEntry", padding=4, fieldbackground="#F7F9FC")
        style.configure("TCombobox", padding=4, fieldbackground="#F7F9FC", arrowsize=14)
        style.map("TCombobox", fieldbackground=[("readonly", "#F7F9FC")], selectbackground=[("readonly", "#F7F9FC")], selectforeground=[("readonly", INK)])
        style.configure("Treeview", rowheight=34, background="white", fieldbackground="white", foreground=INK, font=(family, 9), borderwidth=0)
        style.configure("Treeview.Heading", background="#EAF0F7", foreground=MUTED, font=(family, 9, "bold"), padding=(5, 6), relief="flat")
        style.map("Treeview", background=[("selected", "#DCE9FF")], foreground=[("selected", "#15376B")])

    def _build(self):
        page = ttk.Frame(self.root, padding=(16, 10, 16, 8))
        page.pack(fill="both", expand=True)
        header = ttk.Frame(page)
        header.pack(fill="x", pady=(0, 5))
        ttk.Label(header, text="航迹", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="  城市 × 日期，找到合适的航班", style="Muted.TLabel").pack(side="left", padx=8)
        ttk.Button(header, text="使用说明", command=self.help).pack(side="right")
        ttk.Label(header, text="1名成人 · 经济舱 · 北京时间", style="Muted.TLabel").pack(side="right", padx=12)
        tk.Label(page, text="教学模拟数据 · 航司、航班、票价及优惠均为虚构，不提供购买。", anchor="w",
                 bg="#FFF2D8", fg="#855C17", padx=10, pady=4, font=(self.family, 9)).pack(fill="x", pady=(0, 5))
        card = ttk.Frame(page, style="Card.TFrame", padding=(10, 5, 10, 6))
        card.pack(fill="x")
        self.tabs = ttk.Notebook(card)
        self.tabs.pack(fill="x")
        regular = ttk.Frame(self.tabs, style="Card.TFrame", padding=(8, 4))
        flexible = ttk.Frame(self.tabs, style="Card.TFrame", padding=(8, 4))
        self.tabs.add(regular, text="  常规查询 · 单程 / 往返  ")
        self.tabs.add(flexible, text="  灵活低价 · 多城市 / 日期范围  ")
        if self.range_service is None:
            self.tabs.tab(1, state="disabled")
        self.tabs.bind("<<NotebookTabChanged>>", self._mode_changed)
        top = ttk.Frame(regular, style="Card.TFrame")
        top.pack(fill="x", pady=(0, 4))
        for trip in ("单程", "往返"):
            ttk.Radiobutton(top, text=trip, value=trip, variable=self.trip).pack(side="left", padx=(0, 16))
        coverage = (f"数据日期 {self.provider.dates[0]} 至 {self.provider.dates[-1]}"
                    if self.provider.dates else "当前数据没有航班")
        ttk.Label(top, text=coverage, style="CardMuted.TLabel").pack(side="right")
        fields = ttk.Frame(regular, style="Card.TFrame")
        fields.pack(fill="x")
        for col in (0, 2, 3, 4):
            fields.columnconfigure(col, weight=1, uniform="regular")
        for col, label in ((0, "出发城市"), (2, "到达城市"), (3, "出发日期"), (4, "返程日期")):
            ttk.Label(fields, text=label, style="CardMuted.TLabel").grid(row=0, column=col, sticky="w", pady=(0, 4))
        self.origin_box = ttk.Combobox(fields, textvariable=self.origin, values=self.provider.cities, state="readonly", width=12)
        self.origin_box.grid(row=1, column=0, sticky="ew")
        ttk.Button(fields, text="⇄", command=self.swap, width=3).grid(row=1, column=1, padx=8)
        self.destination_box = ttk.Combobox(fields, textvariable=self.destination, values=self.provider.cities, state="readonly", width=12)
        self.destination_box.grid(row=1, column=2, sticky="ew", padx=(0, 12))
        self.dep_field = DateField(fields, self.dep_date)
        self.dep_field.grid(row=1, column=3, sticky="ew", padx=(0, 12))
        self.return_field = DateField(fields, self.ret_date)
        self.return_field.grid(row=1, column=4, sticky="ew")
        self.return_entry = self.return_field.entry
        range_top = ttk.Frame(flexible, style="Card.TFrame")
        range_top.pack(fill="x", pady=(0, 4))
        ttk.Label(range_top, text="多选城市，比较整个日期范围内的单程最低价", style="CardMuted.TLabel").pack(side="left")
        ttk.Checkbutton(range_top, text="应用模拟优惠", variable=self.use_discount).pack(side="right")
        ttk.Button(range_top, text="优惠规则", command=self.show_discount).pack(side="right", padx=8)
        range_fields = ttk.Frame(flexible, style="Card.TFrame")
        range_fields.pack(fill="x")
        for col in range(4):
            range_fields.columnconfigure(col, weight=1, uniform="range")
        for col, label in enumerate(("出发城市（可多选）", "到达城市（可多选）", "开始日期（含）", "结束日期（含）")):
            ttk.Label(range_fields, text=label, style="CardMuted.TLabel").grid(row=0, column=col, sticky="w", pady=(0, 4))
        ttk.Button(range_fields, textvariable=self.origin_caption, command=lambda: self.pick_cities(True)).grid(row=1, column=0, sticky="ew", padx=(0, 12))
        ttk.Button(range_fields, textvariable=self.destination_caption, command=lambda: self.pick_cities(False)).grid(row=1, column=1, sticky="ew", padx=(0, 12))
        DateField(range_fields, self.range_start).grid(row=1, column=2, sticky="ew", padx=(0, 12))
        DateField(range_fields, self.range_end).grid(row=1, column=3, sticky="ew")
        options = ttk.Frame(card, style="Card.TFrame")
        options.pack(fill="x", pady=(6, 0))
        ttk.Label(options, text="预算上限 ¥", style="Card.TLabel").pack(side="left")
        self.budget_entry = ttk.Entry(options, textvariable=self.budget, width=10)
        self.budget_entry.pack(side="left", padx=(6, 6))
        ttk.Label(options, text="留空不限", style="CardMuted.TLabel").pack(side="left", padx=(0, 14))
        ttk.Label(options, text="全程航司", style="Card.TLabel").pack(side="left")
        ttk.Combobox(options, textvariable=self.airline, values=("不限",)+self.provider.airlines,
                     state="readonly", width=16).pack(side="left", padx=(6, 12))
        ttk.Checkbutton(options, text="仅直飞", variable=self.direct).pack(side="left")
        self.search_button = ttk.Button(options, text="查询航班", style="Primary.TButton", command=self.search)
        self.search_button.pack(side="right")
        self.cancel_button = ttk.Button(options, text="取消", command=self.cancel_query, state="disabled")
        self.cancel_button.pack(side="right", padx=6)
        ttk.Button(options, text="恢复示例", command=self.reset).pack(side="right")
        self.progress_bar = ttk.Progressbar(page, mode="determinate", maximum=100)
        self.progress_bar.pack(fill="x", pady=(5, 0))
        bar = ttk.Frame(page)
        bar.pack(fill="x", pady=(5, 4))
        ttk.Label(bar, textvariable=self.summary, style="Heading.TLabel").pack(side="left")
        ttk.Label(bar, textvariable=self.count, style="Muted.TLabel").pack(side="left", padx=10)
        self.export_button = ttk.Button(bar, text="导出 CSV", command=self.export, state="disabled")
        self.export_button.pack(side="right")
        self.sort_box = ttk.Combobox(bar, textvariable=self.sort_order, values=tuple(s.value for s in SortOrder), state="readonly", width=18)
        self.sort_box.pack(side="right", padx=8)
        self.sort_box.bind("<<ComboboxSelected>>", self.resort)
        metrics = ttk.Frame(page)
        metrics.pack(fill="x", pady=(0, 4))
        ttk.Label(metrics, textvariable=self.cheapest, foreground=BLUE, font=(self.family, 11, "bold")).pack(side="left")
        self.cheapest_button = ttk.Button(metrics, text="定位最低价", command=self.locate_cheapest, state="disabled")
        self.cheapest_button.pack(side="left", padx=10)
        ttk.Label(metrics, text="修改条件后需重新查询；导出保留当前结果的条件。", style="Muted.TLabel").pack(side="right")
        self.body = ttk.Panedwindow(page, orient="horizontal")
        bottom = ttk.Frame(page)
        bottom.pack(side="bottom", fill="x", pady=(5, 0))
        self.status_label = ttk.Label(bottom, textvariable=self.status, style="Muted.TLabel", wraplength=980)
        self.status_label.pack(anchor="w")
        self.body.pack(fill="both", expand=True)
        left = ttk.Frame(self.body, style="Card.TFrame")
        right = ttk.Frame(self.body, style="Card.TFrame", padding=8)
        self.body.add(left, weight=3)
        self.body.add(right, weight=1)
        columns = ("route", "out", "back", "airline", "type", "price")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse", height=5)
        for col, label, width in (("route", "实际路线", 128), ("out", "出发 / 到达", 174), ("back", "返程 / 到达", 174),
                                  ("airline", "航司", 100), ("type", "行程", 76), ("price", "最终价 ¥", 100)):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, minwidth=60, anchor="e" if col=="price" else "w")
        ys = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        pager = ttk.Frame(left, style="Card.TFrame", padding=(8, 3))
        pager.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.previous_button = ttk.Button(pager, text="上一页", command=lambda: self.change_page(-1), state="disabled")
        self.previous_button.pack(side="left")
        ttk.Label(pager, textvariable=self.page_label, style="CardMuted.TLabel").pack(side="left", padx=8)
        self.next_button = ttk.Button(pager, text="下一页", command=lambda: self.change_page(1), state="disabled")
        self.next_button.pack(side="left")
        ttk.Label(pager, text="每页100条 · CSV导出全部结果", style="CardMuted.TLabel").pack(side="right")
        self.tree.tag_configure("alternate", background="#F7F9FC")
        self.tree.bind("<<TreeviewSelect>>", self.show_selected)
        ttk.Label(right, text="行程详情", style="Card.TLabel", font=(self.family, 11, "bold")).pack(anchor="w")
        ttk.Label(right, textvariable=self.selected_route, style="CardMuted.TLabel", wraplength=265).pack(anchor="w", pady=(3, 2))
        ttk.Label(right, textvariable=self.selected_price, style="Price.TLabel").pack(anchor="w", pady=(0, 5))
        ttk.Label(right, textvariable=self.selected_breakdown, style="CardMuted.TLabel", wraplength=265).pack(anchor="w", pady=(0, 4))
        detail_frame = ttk.Frame(right, style="Card.TFrame")
        detail_frame.pack(fill="both", expand=True)
        self.details = tk.Text(detail_frame, width=29, height=4, wrap="word", relief="flat", borderwidth=0,
                               background="white", foreground=INK, font=(self.family, 9),
                               spacing1=2, spacing3=4, state="disabled")
        scroll = ttk.Scrollbar(detail_frame, orient="vertical", command=self.details.yview)
        self.details.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.details.pack(side="left", fill="both", expand=True)
        self._set_details("选择城市和日期后查询。\n\n常规查询：指定日期单程或往返。\n\n灵活低价：多个城市和一段日期，比较模拟优惠后的价格。\n\n选择结果可查看航段、余票及原价与优惠明细。")
        self._layout_job = self.root.after(80, self._initial_split)

    def _initial_split(self):
        self._layout_job = None
        if self._closed:
            return
        width = self.body.winfo_width()
        if width < 900:
            self._layout_job = self.root.after(25, self._initial_split)
            return
        self.body.sashpos(0, width-310)

    def is_range(self):
        return self.tabs.index(self.tabs.select()) == 1

    def _mode_changed(self, _event=None):
        if not hasattr(self, "tree"):
            return
        self.cancel_query()
        self._clear_results()
        self.status.set("灵活低价仅查询单程，可多选城市；勾选后应用本地模拟满减。" if self.is_range()
                        else "常规查询保留原价，往返为两张模拟单程票的组合。")

    def _trip_changed(self):
        self.return_field.set_enabled(self.trip.get() == "往返")

    def _mark_dirty(self):
        if self.last_criteria and not self._busy and not self._resetting:
            self.status.set("条件已修改，请重新查询。当前列表与CSV仍对应上一次查询快照。")

    def _enter_search(self, event):
        if event.widget.winfo_toplevel() is not self.root or event.widget is self.details:
            return
        # 按钮的Enter交给按钮自身，避免导出、翻页被误解释为新查询。
        if isinstance(event.widget, (ttk.Button, ttk.Checkbutton, ttk.Radiobutton)):
            return
        self.search()

    def _city_captions(self):
        for selected, variable in ((self.range_origins, self.origin_caption), (self.range_destinations, self.destination_caption)):
            caption = " / ".join(selected[:3])
            if len(selected) > 3:
                caption += f" 等{len(selected)}城"
            variable.set(caption or "点击选择城市")

    def pick_cities(self, origin):
        def confirm(cities):
            if origin:
                self.range_origins = cities
            else:
                self.range_destinations = cities
            self._city_captions()
            self._mark_dirty()
        return choose_cities(self.root, "选择出发城市" if origin else "选择到达城市", self.provider.cities,
                             self.range_origins if origin else self.range_destinations, confirm)

    def swap(self):
        a, b = self.origin.get(), self.destination.get()
        self.origin.set(b)
        self.destination.set(a)

    def reset(self):
        if self._busy:
            return
        self._resetting = True
        self.trip.set("单程")
        self.origin.set(self._default_city("深圳", 0))
        self.destination.set(self._default_city("北京", -1))
        self.dep_date.set(self._default_date(9, "2026-11-10"))
        self.ret_date.set(self._default_date(14, "2026-11-15"))
        self.range_start.set(self.dep_date.get())
        self.range_end.set(self.ret_date.get())
        self.range_origins = tuple(c for c in ("深圳", "广州", "珠海") if c in self.provider.cities) or (self.origin.get(),)
        self.range_destinations = (self.destination.get(),)
        self.use_discount.set(True)
        self._city_captions()
        self.budget.set("")
        self.direct.set(False)
        self.airline.set("不限")
        self.sort_order.set(SortOrder.PRICE.value)
        self._clear_results()
        self._resetting = False
        self.status.set("已恢复当前模式的示例，点击查询。")

    def _criteria(self):
        common = dict(budget_cents=parse_budget(self.budget.get()), direct_only=self.direct.get(),
                      airline=None if self.airline.get()=="不限" else self.airline.get(),
                      sort_order=SortOrder(self.sort_order.get()))
        if self.is_range():
            return RangeCriteria(tuple(self.range_origins), tuple(self.range_destinations),
                                 parse_date(self.range_start.get(), "开始日期"),
                                 parse_date(self.range_end.get(), "结束日期"),
                                 **common, discount_enabled=self.use_discount.get())
        return SearchCriteria(self.origin.get(), self.destination.get(), parse_date(self.dep_date.get(), "出发日期"),
                              parse_date(self.ret_date.get(), "返程日期") if self.trip.get()=="往返" else None, **common)

    def _clear_results(self):
        self.results = ()
        self.last_criteria = None
        self.last_discount_summary = ""
        self._page = 0
        self.tree.delete(*self.tree.get_children())
        for button in (self.export_button, self.cheapest_button, self.previous_button, self.next_button):
            button.configure(state="disabled")
        self.count.set("尚无结果")
        self.summary.set("查询结果")
        self.cheapest.set("最低价 —")
        self.page_label.set("第 0 / 0 页")
        self.selected_route.set("选中一条结果查看行程")
        self.selected_price.set("—")
        self.selected_breakdown.set("原价与优惠将在查询后显示")
        self.progress_bar["value"] = 0
        self._set_details("尚无可显示的行程。")

    def search(self):
        if self._busy or self._closed:
            return
        self._clear_results()
        try:
            criteria = self._criteria()
            if isinstance(criteria, RangeCriteria):
                if self.range_service is None:
                    return
                service = self.range_service if criteria.discount_enabled else self.range_no_discount
                service.validate(criteria)
            else:
                validate_criteria(criteria, self.provider.cities)
                service = self.service
        except FlightAppError as exc:
            self.status.set(str(exc))
            messagebox.showwarning("请检查查询条件", str(exc), parent=self.root)
            return
        self._busy = True
        self._serial += 1
        serial = self._serial
        self._cancel = Event()
        cancel = self._cancel
        self.search_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.status.set("正在查询本地模拟航班，可随时取消…")
        discount_text = (self.discount_summary if criteria.discount_enabled else "未应用模拟优惠") if isinstance(criteria, RangeCriteria) else "常规查询不应用优惠"
        def worker():
            try:
                if isinstance(criteria, RangeCriteria):
                    def progress(done, total):
                        if done == total or done % max(1, total//100) == 0:
                            self._queue.put((serial, "progress", (done, total)))
                    result = service.search_range(criteria.origins, criteria.destinations, criteria.start_date, criteria.end_date,
                                                  criteria.budget_cents, criteria.direct_only, criteria.airline, criteria.sort_order,
                                                  cancel_check=cancel.is_set, progress=progress)
                else:
                    result = service.search(criteria)
                if not cancel.is_set():
                    self._queue.put((serial, "done", (criteria, result, discount_text)))
            except SearchCancelled:
                self._queue.put((serial, "cancelled", None))
            except FlightAppError as exc:
                self._queue.put((serial, "error", str(exc)))
            except Exception:
                logging.exception("Unexpected search error")
                self._queue.put((serial, "error", "查询发生未预期错误，详细错误已输出到终端。"))
        Thread(target=worker, daemon=True, name=f"flight-query-{serial}").start()
        self._pending = self.root.after(20, self._poll)

    def _poll(self):
        self._pending = None
        if self._closed:
            return
        for _ in range(250):
            try:
                serial, kind, payload = self._queue.get_nowait()
            except Empty:
                break
            if serial != self._serial or not self._busy:
                continue
            if kind == "progress":
                done, total = payload
                self.progress_bar["value"] = done * 100 / total
                self.status.set(f"已检查 {done} / {total} 个城市日期组合…")
            elif kind == "done":
                self.last_criteria, self.results, self.last_discount_summary = payload
                self._finish_query()
                self.progress_bar["value"] = 100
                self._render_results()
            elif kind == "error":
                self._finish_query()
                self.status.set(payload)
                messagebox.showwarning("查询未完成", payload, parent=self.root)
            else:
                self._finish_query()
                self.status.set("查询已取消。")
        if self._busy:
            self._pending = self.root.after(20, self._poll)

    def _finish_query(self):
        self._busy = False
        self.search_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")

    def cancel_query(self):
        if not self._busy:
            return
        self._cancel.set()
        self._serial += 1
        if self._pending:
            self.root.after_cancel(self._pending)
            self._pending = None
        self._finish_query()
        self._clear_results()
        self.status.set("查询已取消，可以修改条件重新查询。")

    def _render_results(self, select_index=None):
        c = self.last_criteria
        if c is None:
            return
        flexible = isinstance(c, RangeCriteria)
        self.tree.configure(displaycolumns=("route", "out", "airline", "type", "price") if flexible or c.return_date is None
                            else ("route", "out", "back", "airline", "type", "price"))
        self.tree.delete(*self.tree.get_children())
        start = self._page * PAGE_SIZE
        end = min(len(self.results), start + PAGE_SIZE)
        for index in range(start, end):
            q = self.results[index]
            a, b = q.itinerary.outbound, q.itinerary.inbound
            airlines = " / ".join(dict.fromkeys(s.airline.replace("（模拟）", "") for leg in q.itinerary.legs for s in leg.segments))
            kind = "直飞" if all(f.direct for f in q.itinerary.legs) else "含中转"
            if q.discount_cents:
                kind += " · 惠"
            self.tree.insert("", "end", iid=str(index), values=(f"{a.origin.city} → {a.destination.city}", leg_label(a), leg_label(b),
                             airlines, kind, money(q.final_price_cents)), tags=("alternate",) if index%2 else ())
        self.summary.set("灵活单程结果" if flexible else f"{c.origin} → {c.destination} {'往返' if c.return_date else '单程'}")
        self.count.set(f"共 {len(self.results)} 条")
        pages = (len(self.results) + PAGE_SIZE-1)//PAGE_SIZE
        self.page_label.set(f"第 {self._page+1 if pages else 0} / {pages} 页")
        self.previous_button.configure(state="normal" if self._page else "disabled")
        self.next_button.configure(state="normal" if self._page+1 < pages else "disabled")
        for button in (self.export_button, self.cheapest_button):
            button.configure(state="normal" if self.results else "disabled")
        if self.results:
            minimum = min(self.results, key=lambda q: (q.final_price_cents, q.itinerary.outbound.departure, q.itinerary.id))
            f = minimum.itinerary.outbound
            self.cheapest.set(f"最低价 ¥{money(minimum.final_price_cents)} · {f.departure:%m-%d} {f.origin.city}→{f.destination.city}")
            index = select_index if select_index is not None and start <= select_index < end else start
            self.tree.selection_set(str(index))
            self.tree.focus(str(index))
            self.tree.see(str(index))
            self.show_selected()
            query_date = f"{c.start_date} 至 {c.end_date}" if flexible else str(c.departure_date)
            self.status.set(f"查询完成：{query_date}，共{len(self.results)}条，当前第{start+1}–{end}条；CSV导出全部结果。")
        else:
            self.selected_route.set("没有符合条件的行程")
            self.selected_price.set("—")
            self._set_details("没有符合条件的行程。\n\n试着放宽预算、航司或直飞条件；并确认城市间存在模拟航线。\n\n模拟数据只覆盖指定日期，不能用于实际出行。")
            self.status.set("没有符合条件的行程，请调整城市、日期或筛选条件。")

    def change_page(self, step):
        pages = (len(self.results)+PAGE_SIZE-1)//PAGE_SIZE
        target = self._page + step
        if 0 <= target < pages and not self._busy:
            self._page = target
            self._render_results()

    def locate_cheapest(self):
        if not self.results or self._busy:
            return
        index = min(range(len(self.results)), key=lambda i: (self.results[i].final_price_cents,
                    self.results[i].itinerary.outbound.departure, self.results[i].itinerary.id))
        self._page = index//PAGE_SIZE
        self._render_results(index)

    def resort(self, event=None):
        if not self.last_criteria or self._busy:
            return
        self.last_criteria = replace(self.last_criteria, sort_order=SortOrder(self.sort_order.get()))
        self.results = sort_quotes(list(self.results), self.last_criteria.sort_order)
        self._page = 0
        self._render_results()

    def _set_details(self, text):
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")
        self.details.yview_moveto(0)

    def show_selected(self, event=None):
        selection = self.tree.selection()
        if not selection or not self.tree.exists(selection[0]):
            return
        index = int(selection[0])
        if index >= len(self.results):
            return
        q = self.results[index]
        self.selected_route.set(f"{q.itinerary.outbound.origin.city} → {q.itinerary.outbound.destination.city}" +
                                (" → "+q.itinerary.inbound.destination.city if q.itinerary.inbound else ""))
        self.selected_price.set(f"¥ {money(q.final_price_cents)}")
        self.selected_breakdown.set(f"原价 ¥{money(q.base_price_cents)}  ·  优惠 ¥{money(q.discount_cents)}")
        self._set_details(detail_text(q))

    def export(self):
        if not self.results or self.last_criteria is None or self._busy:
            return
        # 保存对话框开启前固定快照；后续界面变化不会污染导出。
        criteria, quotes, description = self.last_criteria, self.results, self.last_discount_summary
        path = filedialog.asksaveasfilename(parent=self.root, title="导出全部当前查询结果", defaultextension=".csv",
                                            filetypes=[("CSV文件", "*.csv")], initialfile="模拟机票查询结果.csv")
        if not path:
            return
        try:
            if isinstance(criteria, RangeCriteria):
                count = export_range_quotes(Path(path), quotes, criteria, description)
            else:
                count = export_quotes(Path(path), quotes, criteria)
            self.status.set(f"已导出全部{count}条结果：{path}")
        except (OSError, UnicodeError, ValueError) as exc:
            messagebox.showerror("导出失败", f"请检查路径和权限，或关闭占用文件的程序。\n{exc}", parent=self.root)

    def show_discount(self):
        messagebox.showinfo("模拟优惠规则", self.discount_summary + "\n\n仅用于灵活低价的单程查询。\n修改data/discount.json后重启生效。常规查询保持原价。", parent=self.root)

    def help(self):
        messagebox.showinfo("航迹使用说明", "1. 常规查询：选择单程或往返，填写城市与日期。\n"
                            "2. 灵活低价：点击城市按钮勾选多个城市，选择起止日期（含首尾，最多31天）。\n"
                            "3. 预算留空不限；0是0元。航司筛选要求全程匹配。\n"
                            "4. 查询完成后可排序、定位最低价、翻页、查看详情或导出全部CSV。\n"
                            "5. 修改条件后请重新查询；界面与CSV保留上次查询快照。\n\n"
                            "快捷键：Enter查询，Esc取消，Ctrl+E导出。\n"
                            "日期可输入YYYY-MM-DD，也可点击日历选择。\n"
                            "数据与优惠为固定教学模拟内容，不代表实时票价，不提供购买。", parent=self.root)

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._cancel.set()
        self._serial += 1
        for callback in (self._pending, self._layout_job):
            if callback:
                self.root.after_cancel(callback)
        self.root.destroy()
