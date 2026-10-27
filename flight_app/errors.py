"""界面可安全展示的领域异常。"""


class FlightAppError(Exception):
    """应用的预期错误。"""


class ValidationError(FlightAppError):
    """用户输入不满足查询条件。"""


class DataError(FlightAppError):
    """本地航班数据无法读取或不满足数据约束。"""
