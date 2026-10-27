"""入口：python main.py。支持--check进行不依赖图形显示的自检。"""
import argparse
import sys
from pathlib import Path

from flight_app.errors import FlightAppError
from flight_app.models import SearchCriteria
from flight_app.provider import JsonFlightProvider
from flight_app.service import SearchService

BASE_DIR = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description="本地模拟机票查询GUI")
    parser.add_argument("--data", type=Path, default=BASE_DIR / "data" / "flights.json", help="指定模拟数据JSON文件")
    parser.add_argument("--check", action="store_true", help="只验证数据与查询服务，不打开GUI")
    args = parser.parse_args()
    try:
        provider = JsonFlightProvider(args.data)
    except FlightAppError as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 1
    if args.check:
        if not provider.dates:
            print("数据格式有效，但没有航班。")
            return 0
        origin, destination = next(( (a, b) for a in provider.cities for b in provider.cities
                                    if a != b and provider.search(a, b, provider.dates[0]) ),
                                  (provider.cities[0], provider.cities[-1]))
        criteria = SearchCriteria(origin, destination, provider.dates[0])
        results = SearchService(provider).search(criteria)
        print(f"数据检查通过：{len(provider.cities)}个城市，{len(provider.dates)}个出发日期。")
        print(f"示例查询 {origin}→{destination} {provider.dates[0]}：{len(results)}条结果。")
        return 0
    try:
        import tkinter as tk
        from flight_app.gui import FlightApp
        root = tk.Tk()
        FlightApp(root, provider)
        root.mainloop()
    except ImportError as exc:
        print(f"无法启动界面：请使用带Tkinter的Python安装。{exc}", file=sys.stderr)
        return 1
    except tk.TclError as exc:
        print(f"无法创建GUI窗口：请在有桌面显示的环境运行，并确认Tkinter可用。{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
