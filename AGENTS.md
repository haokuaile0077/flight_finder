# 航迹开发约定

- Python 3.11+，标准库及Tkinter，本地固定模拟数据；不接API、不启动HTTP服务、不购买。
- main.py装配和启动；业务模块不导入GUI或弹窗。公共不可变模型集中在models.py。
- 金额为整数分，时间带+08:00；不修改Flight原价，不复制另一套模型或单日期查询。
- 常规单程、往返保留原价；灵活单程联合查询日期范围、多城市及可关闭的配置满减。
- 范围输入、价格、明细、预算及CSV必须一致；空结果和异常分开。导出使用查询快照。
- 查询在后台计算，Tk控件只在主线程更新；取消、关闭及旧任务返回必须安全。
- 公共接口变更需同步调用方、测试、说明，并向组长列明兼容影响。
- 执行 python -m unittest discover -s tests -v 和 python main.py --check。
- 有桌面时执行 python tools/run_tests.py --require-gui；GUI跳过不能写成实际通过。
- 使用AI审查实际差异并记录修复与复查，合并负责人确认；不虚构其他成员审查或贡献。
- 仅test、beta、master三个分支；提交test前拉取，禁止强推；beta及master由组长确认合并。
- 保留教学模拟标记，README与实际代码同步，不伪造实时票价、CI运行或Windows实测记录。
- 4空格、snake_case函数、PascalCase类；公共接口标类型和单位；不用个人绝对路径。
