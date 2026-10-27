# 初版模块与扩展接口

本文依据初版实现整理，接口以代码及测试为准。

## 模块职责

| 文件 | 职责 |
| --- | --- |
| main.py | 定位数据、创建依赖、启动GUI或自检 |
| models.py | 冻结数据类及枚举，公共字段定义 |
| provider.py | FlightProvider协议、JSON加载验证与路线日期索引 |
| validation.py | 界面文字解析、查询条件验证 |
| service.py | 单程查询、往返组合、调用计价及最终预算筛选 |
| filters.py | 航班筛选、统一排序 |
| pricing.py | PricingPolicy协议、无优惠计价实现 |
| exporting.py | CSV快照导出和原子替换 |
| presentation.py | GUI与导出的显示格式、详情明细 |
| gui.py | 输入收集、显示结果和用户反馈 |

## 公共模型

- Airport：机场代码、城市、名称。查询以城市为键，航段保留真实的机场粒度。
- Segment：航班号、航司、起降机场及带北京时间时区的起降datetime。
- Flight：唯一报价ID、一个或多个Segment、整数分票价、余票和economy舱位。代表一次单程报价；中转是明确的多个航段。
- SearchCriteria：出发城市、目的地、出发date、可空返程date、可空预算分、直飞条件、可空航司、SortOrder、固定1名乘客。
- Itinerary：去程Flight及可空返程Flight。组合ID包含每程的报价ID。
- Quote：Itinerary、原价、优惠额、最终价格、PriceLine明细和CNY币种。

数据对象使用frozen dataclass，不就地改价。复制条件时使用dataclasses.replace。

## 查询调用

```python
from datetime import date
from pathlib import Path
from flight_app.models import SearchCriteria
from flight_app.provider import JsonFlightProvider
from flight_app.service import SearchService

provider = JsonFlightProvider(Path("data/flights.json"))
service = SearchService(provider)
criteria = SearchCriteria("深圳", "北京", date(2026, 11, 10),
                          return_date=date(2026, 11, 15), budget_cents=150000)
quotes = service.search(criteria)
```

`search`返回不可变的`tuple[Quote, ...]`；无结果返回空tuple。输入错误抛ValidationError，数据错误抛DataError，业务层不弹窗口，也不把错误字符串混进结果列表。

`FlightProvider.search(origin, destination, on_date)`返回`tuple[Flight, ...]`。数据源须保证模型数据有效；JsonFlightProvider会在载入时检查schema、ID重复、金额、余票、机场引用、时区和航段衔接。

## 后续功能如何接入

1. 日期范围与多城市：在独立的组合搜索服务中展开条件，复用SearchService；合并后按Itinerary.id去重，再使用统一排序。不要往单次查询塞入难以解释的字符串参数。
2. 优惠：实现`PricingPolicy.quote(itinerary) -> Quote`并注入SearchService。原价须等于各程价之和，优惠在0与原价之间，最终价等于原价减优惠，PriceLine之和须等于最终价。预算在优惠后判断。
3. 其他本地数据源：实现FlightProvider协议，改入口的依赖装配。JsonFlightProvider独有的日期元数据展示需要一起更新，不宣称GUI已对任意数据源完全解耦。
4. 大规模查询：将计算移到受控后台任务；结果只通过GUI主线程更新。增加查询上限、取消、进度及关闭清理。
5. 新筛选条件：扩展SearchCriteria和对应筛选逻辑，同时补输入校验与测试。代码改动应集中于该规则及GUI输入，不改变Quote的基础含义。

JSON格式版本为1，顶层字段为schema_version、simulated、description、airports、flights。字段示例见data/flights.json及生成器；不存储个人信息或账号密钥。

## 验收方式

先运行全部业务测试，再打开GUI检查单程、往返、筛选、详情和导出。更改公共接口必须同步调用方和测试。CI文件已配置，首次推送后核实运行结果，不把配置文件视为CI运行证据。
