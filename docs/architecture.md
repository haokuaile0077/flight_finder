# 实现架构与扩展规范

## 模块边界

| 模块 | 职责 |
| --- | --- |
| main.py | 定位JSON、装配数据源与计价策略、启动或自检 |
| models.py | frozen dataclass：SearchCriteria、RangeCriteria、Flight、Itinerary、Quote等 |
| provider.py | FlightProvider协议；JSON严格校验、路线日期索引 |
| service.py / filters.py | 单日单程、往返组合、筛选、计价、优惠后预算、稳定排序 |
| date_search.py | 首尾包含的日期展开，逐日复用SearchService，取消与进度 |
| range_search.py | 城市集合组合、排除同城、聚合去重、全局排序 |
| pricing.py / discount_pricing.py | PricingPolicy协议、原价策略、可配置单航司模拟满减 |
| validation.py / errors.py | 输入校验和业务异常，包括SearchCancelled |
| presentation.py / exporting.py | 统一格式、价格明细、条件快照CSV与原子替换 |
| widgets.py | 可输入日期与日历、多选城市弹窗 |
| gui.py | 条件采集、后台任务、分页、主线程显示 |

## 联合查询流程

RangeCriteria统一保存城市集合、日期范围、预算、航司、直飞、排序和优惠开关。GUI根据开关选择已注入优惠策略或无优惠策略的范围服务。RangeSearchService公开search_range接口本身不接收优惠开关，其价格行为由构造时注入的SearchService决定。

校验全部条件→出发集合×到达集合（排除同城）→逐路线逐日复用单日期服务→航段/航司/直飞/余票筛选→策略计价→最终价预算筛选→按Itinerary.id去重→统一排序。日期含首尾，最多31天。范围服务可注入数据日期边界，入口已启用。空结果返回空tuple，输入错误抛ValidationError，取消抛SearchCancelled；业务层不弹窗。

示例（关闭优惠则改用SearchService(provider)）：

```python
from datetime import date
from pathlib import Path
from flight_app.provider import JsonFlightProvider
from flight_app.discount_pricing import load_pricing
from flight_app.service import SearchService
from flight_app.range_search import RangeSearchService

provider = JsonFlightProvider(Path("data/flights.json"))
service = RangeSearchService(
    SearchService(provider, load_pricing(Path("data/discount.json"))),
    provider.cities, date_bounds=(provider.dates[0], provider.dates[-1]))
quotes = service.search_range(("深圳", "广州", "珠海"), ("北京",),
                              date(2026, 11, 10), date(2026, 11, 15))
```

## 价格与模型约定

金额用整数分，bool不能充当金额；时间带+08:00。模型不可变，不就地修改Flight。Quote原价等于各程原价之和，0≤优惠≤原价，最终价=原价−优惠，PriceLine合计=最终价。优惠明细为负数。替换策略需实现quote(itinerary)→Quote并保持这些约束。配置使用单条满减，不涉及全平台优惠或实时来源。

## 并发与快照

只在主线程操作Tk。后台线程处理本地查询，Queue传递带任务编号的消息，Event表示取消。新任务或取消后忽略旧编号消息，关闭窗口取消回调。取消常规查询会丢弃结果，单次计算本身不保证中途停止；范围查询在路线和日期之间检查取消。不向界面显示半成品结果。

输入对象、结果tuple与规则描述形成查询快照；排序仅重排当前结果，导出保留相同条件并记录当前排序。每页100条，CSV导出全部，定位最低价依据全量结果。输入变化不悄悄改变已显示结果。

## 后续扩展

新优惠实现PricingPolicy并注入；新本地数据源实现FlightProvider并适配元数据。新筛选项同步模型、校验、筛选、GUI和CSV。范围往返需单独定义去返日期配对与组合上限，不能直接当作现有范围单程。GUI目前仍使用JSON数据源的城市/日期元数据，不宣称完全通用。
