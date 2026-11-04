"""Tkinter桌面界面。无网络、浏览器及HTTP服务依赖。"""
import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .errors import FlightAppError
from .exporting import export_quotes
from .models import Quote, SearchCriteria, SortOrder
from .presentation import detail_text, leg_label, money
from .pricing import (CompositePricing, NoDiscountPricing, PercentageDiscountPricing,
                      PricingPolicy, ThresholdDiscountPricing)
from .provider import JsonFlightProvider
from .service import SearchService
from .validation import parse_date

BG = "#F3F6FA"
INK = "#162B45"
MUTED = "#5C7088"
BLUE = "#2563EB"

# 查询模式常量
MODE_SINGLE = "单日查询"
MODE_RANGE = "日期范围"
MODE_MULTI = "多城市"


class FlightApp:
    def __init__(self, root: tk.Tk, provider: JsonFlightProvider):
        self.root, self.provider = root, provider
        self.pricing: PricingPolicy = NoDiscountPricing()
        self.service = SearchService(provider, self.pricing)
        self.results: tuple[Quote, ...] = ()
        self.last_criteria: SearchCriteria | None = None
        self.last_mode: str = MODE_SINGLE
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
        # 原有变量
        self.trip = tk.StringVar(value="单程")
        self.origin = tk.StringVar(value="深圳" if "深圳" in provider.cities else (provider.cities[0] if provider.cities else ""))
        self.destination = tk.StringVar(value="北京" if "北京" in provider.cities else (provider.cities[-1] if provider.cities else ""))
        initial = provider.dates[min(9, len(provider.dates)-1)] if provider.dates else None
        return_initial = provider.dates[min(14, len(provider.dates)-1)] if provider.dates else None
        self.dep_date = tk.StringVar(value=initial.isoformat() if initial else "2026-11-10")
        self.ret_date = tk.StringVar(value=return_initial.isoformat() if return_initial else "2026-11-15")
        self.airline = tk.StringVar(value="不限")
        self.direct = tk.BooleanVar(value=False)
        self.sort_order = tk.StringVar(value=SortOrder.PRICE.value)
        # 新增：查询模式
        self.query_mode = tk.StringVar(value=MODE_SINGLE)
        # 新增：日期范围
        self.range_start = tk.StringVar(value=initial.isoformat() if initial else "2026-11-10")
        self.range_end = tk.StringVar(value=(provider.dates[min(19, len(provider.dates)-1)] if provider.dates else initial).isoformat() if initial else "2026-11-20")
        # 新增：多城市选择状态 (index -> boolean)
        self._origin_checks: dict[int, tk.BooleanVar] = {}
        self._dest_checks: dict[int, tk.BooleanVar] = {}
        # 新增：优惠策略
        self.promo_type = tk.StringVar(value="无优惠")
        self.promo_discount_pct = tk.StringVar(value="20")  # 20% 折扣 = 8折
        self.promo_threshold = tk.StringVar(value="500")   # 满500
        self.promo_reduce = tk.StringVar(value="50")       # 减50
        # 状态
        self.status = tk.StringVar(value="选择条件后点击查询。默认示例：深圳 → 北京，2026-11-10。")
        self.summary = tk.StringVar(value="查询结果")
        self.count = tk.StringVar(value="尚未查询")
        self.selected_price = tk.StringVar(value="—")
        self.selected_route = tk.StringVar(value="选中一条结果查看行程")
        self._build()
        self.trip.trace_add("write", lambda *_: self._trip_changed())
        self.query_mode.trace_add("write", lambda *_: self._mode_changed())
        self.promo_type.trace_add("write", lambda *_: self._promo_changed())
        self._trip_changed()
        self._mode_changed()
        self._promo_changed()
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

        # 第一行：单程/往返 + 查询模式
        top = ttk.Frame(card, style="Card.TFrame")
        top.pack(fill="x", pady=(0, 8))
        for trip in ("单程", "往返"):
            ttk.Radiobutton(top, text=trip, value=trip, variable=self.trip).pack(side="left", padx=(0, 18))
        ttk.Label(top, text="|", style="CardMuted.TLabel").pack(side="left", padx=6)
        ttk.Label(top, text="查询模式", style="Card.TLabel").pack(side="left", padx=(0, 6))
        for mode in (MODE_SINGLE, MODE_RANGE, MODE_MULTI):
            ttk.Radiobutton(top, text=mode, value=mode, variable=self.query_mode).pack(side="left", padx=(0, 12))
        ttk.Label(top, text="数据覆盖  2026-11-01 至 2026-11-30", style="CardMuted.TLabel").pack(side="right")

        # 动态字段区域（根据模式切换）
        self.fields_frame = ttk.Frame(card, style="Card.TFrame")
        self.fields_frame.pack(fill="x", pady=(0, 4))
        # 单日模式字段
        self.single_frame = ttk.Frame(self.fields_frame, style="Card.TFrame")
        for col, weight in ((0, 2), (1, 0), (2, 2), (3, 2), (4, 2)):
            self.single_frame.columnconfigure(col, weight=weight)
        for col, label in ((0, "出发城市"), (2, "到达城市"), (3, "出发日期 YYYY-MM-DD"), (4, "返程日期 YYYY-MM-DD")):
            ttk.Label(self.single_frame, text=label, style="CardMuted.TLabel").grid(row=0, column=col, sticky="w", padx=(0, 12), pady=(0, 5))
        self.origin_box = ttk.Combobox(self.single_frame, textvariable=self.origin, values=self.provider.cities, state="readonly", width=14)
        self.origin_box.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(self.single_frame, text="⇄", command=self.swap, width=3).grid(row=1, column=1, padx=(0, 8))
        self.destination_box = ttk.Combobox(self.single_frame, textvariable=self.destination, values=self.provider.cities, state="readonly", width=14)
        self.destination_box.grid(row=1, column=2, sticky="ew", padx=(0, 12))
        ttk.Entry(self.single_frame, textvariable=self.dep_date, width=16).grid(row=1, column=3, sticky="ew", padx=(0, 12))
        self.return_entry = ttk.Entry(self.single_frame, textvariable=self.ret_date, width=16)
        self.return_entry.grid(row=1, column=4, sticky="ew")

        # 日期范围模式字段
        self.range_frame = ttk.Frame(self.fields_frame, style="Card.TFrame")
        for col, weight in ((0, 2), (1, 0), (2, 2), (3, 2), (4, 2)):
            self.range_frame.columnconfigure(col, weight=weight)
        for col, label in ((0, "出发城市"), (2, "到达城市"), (3, "起始日期 YYYY-MM-DD"), (4, "结束日期 YYYY-MM-DD")):
            ttk.Label(self.range_frame, text=label, style="CardMuted.TLabel").grid(row=0, column=col, sticky="w", padx=(0, 12), pady=(0, 5))
        self.range_origin_box = ttk.Combobox(self.range_frame, textvariable=self.origin, values=self.provider.cities, state="readonly", width=14)
        self.range_origin_box.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.range_swap_btn = ttk.Button(self.range_frame, text="⇄", command=self.swap, width=3)
        self.range_swap_btn.grid(row=1, column=1, padx=(0, 8))
        self.range_dest_box = ttk.Combobox(self.range_frame, textvariable=self.destination, values=self.provider.cities, state="readonly", width=14)
        self.range_dest_box.grid(row=1, column=2, sticky="ew", padx=(0, 12))
        ttk.Entry(self.range_frame, textvariable=self.range_start, width=16).grid(row=1, column=3, sticky="ew", padx=(0, 12))
        ttk.Entry(self.range_frame, textvariable=self.range_end, width=16).grid(row=1, column=4, sticky="ew")
        ttk.Label(self.range_frame, text="范围查询忽略返程日期，每日查一次单程。", style="CardMuted.TLabel").grid(row=2, column=0, columnspan=5, sticky="w", pady=(6, 0))

        # 多城市模式字段
        self.multi_frame = ttk.Frame(self.fields_frame, style="Card.TFrame")
        self.multi_frame.columnconfigure(0, weight=1)
        self.multi_frame.columnconfigure(1, weight=1)
        ttk.Label(self.multi_frame, text="选择出发城市（可多选）", style="CardMuted.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Label(self.multi_frame, text="选择到达城市（可多选）", style="CardMuted.TLabel").grid(row=0, column=1, sticky="w", pady=(0, 4))
        # 出发城市多选项
        self.origin_list = ttk.Frame(self.multi_frame, style="Card.TFrame")
        self.origin_list.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        # 到达城市多选项
        self.dest_list = ttk.Frame(self.multi_frame, style="Card.TFrame")
        self.dest_list.grid(row=1, column=1, sticky="nsew")
        # 填充复选框
        for i, city in enumerate(self.provider.cities):
            var_o = tk.BooleanVar(value=(city == self.origin.get()))
            var_d = tk.BooleanVar(value=(city == self.destination.get()))
            self._origin_checks[i] = var_o
            self._dest_checks[i] = var_d
            ttk.Checkbutton(self.origin_list, text=city, variable=var_o).pack(anchor="w", padx=2, pady=1)
            ttk.Checkbutton(self.dest_list, text=city, variable=var_d).pack(anchor="w", padx=2, pady=1)
        # 多城市日期选择
        self.multi_date_frame = ttk.Frame(self.multi_frame, style="Card.TFrame")
        self.multi_date_frame.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Label(self.multi_date_frame, text="出发日期 YYYY-MM-DD", style="CardMuted.TLabel").pack(side="left")
        ttk.Entry(self.multi_date_frame, textvariable=self.dep_date, width=16).pack(side="left", padx=(6, 0))
        ttk.Label(self.multi_date_frame, text="多城市查询忽略返程日期。", style="CardMuted.TLabel").pack(side="left", padx=(12, 0))

        # 优惠配置行
        promo_row = ttk.Frame(card, style="Card.TFrame")
        promo_row.pack(fill="x", pady=(10, 0))
        ttk.Label(promo_row, text="模拟优惠", style="Card.TLabel").pack(side="left")
        self.promo_box = ttk.Combobox(promo_row, textvariable=self.promo_type,
                                       values=("无优惠", "折扣 %", "满减"), state="readonly", width=10)
        self.promo_box.pack(side="left", padx=(6, 12))
        # 折扣参数
        self.promo_discount_frame = ttk.Frame(promo_row, style="Card.TFrame")
        self.promo_discount_frame.pack(side="left")
        ttk.Label(self.promo_discount_frame, text="折扣减免 %", style="CardMuted.TLabel").pack(side="left")
        ttk.Entry(self.promo_discount_frame, textvariable=self.promo_discount_pct, width=6).pack(side="left", padx=(6, 6))
        ttk.Label(self.promo_discount_frame, text="（如填20即打8折）", style="CardMuted.TLabel").pack(side="left")
        # 满减参数
        self.promo_threshold_frame = ttk.Frame(promo_row, style="Card.TFrame")
        self.promo_threshold_frame.pack(side="left", padx=(12, 0))
        ttk.Label(self.promo_threshold_frame, text="满", style="CardMuted.TLabel").pack(side="left")
        ttk.Entry(self.promo_threshold_frame, textvariable=self.promo_threshold, width=7).pack(side="left", padx=(4, 4))
        ttk.Label(self.promo_threshold_frame, text="元 减", style="CardMuted.TLabel").pack(side="left")
        ttk.Entry(self.promo_threshold_frame, textvariable=self.promo_reduce, width=7).pack(side="left", padx=(4, 4))
        ttk.Label(self.promo_threshold_frame, text="元", style="CardMuted.TLabel").pack(side="left")

        # 航司/直飞/查询按钮
        options = ttk.Frame(card, style="Card.TFrame")
        options.pack(fill="x", pady=(12, 0))
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
        columns = ("route", "out", "back", "airline", "type", "price")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        for col, label, width in (("route", "航线", 120), ("out", "去程 / 起降", 175), ("back", "返程 / 起降", 175), ("airline", "航司", 125), ("type", "行程", 65), ("price", "合计 ¥", 95)):
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, minwidth=55, anchor="e" if col=="price" else "w")
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
        self._set_details("输入查询条件后点击「查询航班」。\n\n试一试：\n深圳 → 北京\n出发 2026-11-10\n返程 2026-11-15\n\n航司筛选适用于行程的每一个航段。\n跨日到达会标记 +1天。")
        bottom = ttk.Frame(page)
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
        state = "normal" if self.trip.get()=="往返" else "disabled"
        self.return_entry.configure(state=state)

    def _mode_changed(self):
        mode = self.query_mode.get()
        # 隐藏所有 frame
        for f in (self.single_frame, self.range_frame, self.multi_frame):
            f.pack_forget()
        # 显示当前模式对应的 frame
        if mode == MODE_SINGLE:
            self.single_frame.pack(fill="x")
        elif mode == MODE_RANGE:
            self.range_frame.pack(fill="x")
        elif mode == MODE_MULTI:
            self.multi_frame.pack(fill="x")
        # 往返选项仅单日模式可用
        self.trip.set("单程")
        self._trip_changed()

    def _promo_changed(self):
        ptype = self.promo_type.get()
        self.promo_discount_frame.pack_forget()
        self.promo_threshold_frame.pack_forget()
        if ptype == "折扣 %":
            self.promo_discount_frame.pack(side="left")
        elif ptype == "满减":
            self.promo_threshold_frame.pack(side="left", padx=(12, 0))

    def _build_pricing(self) -> PricingPolicy:
        """根据当前优惠配置构建 PricingPolicy。"""
        ptype = self.promo_type.get()
        if ptype == "无优惠":
            return NoDiscountPricing()
        elif ptype == "折扣 %":
            pct = int(self.promo_discount_pct.get())
            if not 0 <= pct <= 100:
                raise ValueError("折扣百分比必须在0到100之间。")
            return PercentageDiscountPricing(discount_percent=pct)
        elif ptype == "满减":
            threshold_yuan = int(self.promo_threshold.get())
            reduce_yuan = int(self.promo_reduce.get())
            return ThresholdDiscountPricing(threshold_cents=threshold_yuan * 100,
                                            reduce_cents=reduce_yuan * 100)
        return NoDiscountPricing()

    def _get_selected_origins(self) -> tuple[str, ...]:
        return tuple(self.provider.cities[i] for i, v in self._origin_checks.items() if v.get())

    def _get_selected_dests(self) -> tuple[str, ...]:
        return tuple(self.provider.cities[i] for i, v in self._dest_checks.items() if v.get())

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
        self.range_start.set("2026-11-10");self.range_end.set("2026-11-20")
        self.direct.set(False);self.airline.set("不限");self.sort_order.set(SortOrder.PRICE.value)
        self.query_mode.set(MODE_SINGLE);self.promo_type.set("无优惠")
        self.promo_discount_pct.set("20");self.promo_threshold.set("500");self.promo_reduce.set("50")
        self._clear_results()
        self.status.set("已恢复默认示例，点击查询。")

    def _criteria(self):
        return SearchCriteria(self.origin.get(), self.destination.get(), parse_date(self.dep_date.get(), "出发日期"),
                              parse_date(self.ret_date.get(), "返程日期") if self.trip.get()=="往返" else None,
                              None, self.direct.get(),
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
            # 构建优惠策略和新 service
            self.pricing = self._build_pricing()
            self.service = SearchService(self.provider, self.pricing)
            mode = self.query_mode.get()
            if mode == MODE_SINGLE:
                criteria = self._criteria()
            elif mode == MODE_RANGE:
                criteria = self._criteria_for_range()
            elif mode == MODE_MULTI:
                criteria = self._criteria_for_multi()
        except (FlightAppError, ValueError) as exc:
            self.status.set(str(exc));messagebox.showwarning("请检查查询条件", str(exc), parent=self.root)
            return
        self._busy = True
        self.search_button.configure(state="disabled")
        self.export_button.configure(state="disabled")
        self.status.set("正在查询本地模拟航班…")
        self.last_mode = mode
        self._pending = self.root.after(30, lambda: self._run_search(mode, criteria))

    def _criteria_for_range(self):
        """日期范围模式：校验起始和结束日期，返回用于 search_date_range 的 base criteria。"""
        from datetime import date
        start = parse_date(self.range_start.get(), "起始日期")
        end = parse_date(self.range_end.get(), "结束日期")
        if start > end:
            raise FlightAppError("起始日期不能晚于结束日期。")
        return SearchCriteria(self.origin.get(), self.destination.get(), start, None,
                              None, self.direct.get(),
                              None if self.airline.get()=="不限" else self.airline.get(),
                              SortOrder(self.sort_order.get()))

    def _criteria_for_multi(self):
        """多城市模式：校验至少选一个出发和一个到达城市。"""
        origins = self._get_selected_origins()
        dests = self._get_selected_dests()
        if not origins:
            raise FlightAppError("请至少选择一个出发城市。")
        if not dests:
            raise FlightAppError("请至少选择一个到达城市。")
        # 这里只返回一个标准 criteria，origins 和 dests 在 search 里单独传入
        return SearchCriteria(origins[0], dests[0], parse_date(self.dep_date.get(), "出发日期"), None,
                              None, self.direct.get(),
                              None if self.airline.get()=="不限" else self.airline.get(),
                              SortOrder(self.sort_order.get()))

    def _run_search(self, mode, criteria):
        self._pending = None
        try:
            if mode == MODE_SINGLE:
                results = self.service.search(criteria)
            elif mode == MODE_RANGE:
                from datetime import date
                results = self.service.search_date_range(
                    criteria.origin, criteria.destination,
                    parse_date(self.range_start.get(), "起始日期"),
                    parse_date(self.range_end.get(), "结束日期"),
                    criteria)
            elif mode == MODE_MULTI:
                origins = self._get_selected_origins()
                dests = self._get_selected_dests()
                results = self.service.search_multi_city(origins, dests, criteria)
            else:
                results = ()
            self.results, self.last_criteria = results, criteria
            self._render_results(mode)
        except FlightAppError as exc:
            self.status.set(str(exc));messagebox.showwarning("查询未完成", str(exc), parent=self.root)
        except Exception:
            logging.exception("Unexpected search error")
            self.status.set("查询发生未预期错误，请检查终端记录。")
            messagebox.showerror("查询异常", "查询未完成，详细错误已输出到终端。", parent=self.root)
        finally:
            self._busy = False
            self.search_button.configure(state="normal")

    def _render_results(self, mode: str = MODE_SINGLE):
        self.tree.delete(*self.tree.get_children())
        for index, q in enumerate(self.results):
            a, b = q.itinerary.outbound, q.itinerary.inbound
            route = f"{a.origin.city} → {a.destination.city}"
            airlines = " / ".join(dict.fromkeys(s.airline.replace("（模拟）", "") for leg in q.itinerary.legs for s in leg.segments))
            kind = "全程直飞" if all(f.direct for f in q.itinerary.legs) else "含中转"
            self.tree.insert("", "end", iid=str(index), values=(route, leg_label(a), leg_label(b), airlines, kind, money(q.final_price_cents)), tags=("alternate",) if index%2 else ())
        c = self.last_criteria
        if mode == MODE_SINGLE:
            self.summary.set(f"{c.origin} → {c.destination}  {'往返组合' if c.return_date else '单程'}")
        elif mode == MODE_RANGE:
            self.summary.set(f"{c.origin} → {c.destination}  日期范围 {self.range_start.get()} ~ {self.range_end.get()}")
        elif mode == MODE_MULTI:
            origins = self._get_selected_origins()
            dests = self._get_selected_dests()
            self.summary.set(f"多城市查询  {len(origins)}出发 × {len(dests)}到达")
        self.count.set(f"{len(self.results)} 条结果")
        self.export_button.configure(state="normal" if self.results else "disabled")
        # 优惠信息
        promo_info = ""
        if isinstance(self.pricing, PercentageDiscountPricing):
            promo_info = f"（折扣 {self.pricing.discount_percent}%）"
        elif isinstance(self.pricing, ThresholdDiscountPricing):
            promo_info = f"（满{self.pricing.threshold_cents//100}减{self.pricing.reduce_cents//100}）"
        if self.results:
            self.tree.selection_set("0");self.tree.focus("0");self.show_selected()
            if mode == MODE_SINGLE:
                self.status.set(f"已显示查询快照：{c.departure_date}，{'返程 '+str(c.return_date)+'，' if c.return_date else ''}共{len(self.results)}条{promo_info}。修改条件后需重新查询。")
            elif mode == MODE_RANGE:
                self.status.set(f"日期范围 {self.range_start.get()} ~ {self.range_end.get()} 共{len(self.results)}条{promo_info}。修改条件后需重新查询。")
            elif mode == MODE_MULTI:
                self.status.set(f"多城市组合查询共{len(self.results)}条{promo_info}。修改条件后需重新查询。")
        else:
            self.selected_route.set("没有符合条件的行程");self.selected_price.set("—")
            self._set_details("未找到匹配航班。\n\n请检查数据覆盖日期、航线或放宽航司及直飞条件。\n\n模拟数据仅覆盖2026年11月。")
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
