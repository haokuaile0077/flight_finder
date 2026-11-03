"""标准库测试入口；可要求GUI用例实际执行，并导出真实JSON记录。"""
import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-gui", action="store_true", help="任何GUI跳过都视为验证未通过")
    parser.add_argument("--report", type=Path, help="保存本次运行记录JSON")
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.discover(str(ROOT/"tests"), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    skipped = [(str(test), reason) for test, reason in result.skipped]
    passed = result.wasSuccessful() and not (args.require_gui and skipped)
    if args.require_gui and skipped:
        print("验证未通过：要求GUI实测，但存在跳过用例。", file=sys.stderr)
    try:
        import tkinter
        tk_version = tkinter.TkVersion
    except ImportError:
        tk_version = None
    report = {"time_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version,
              "platform": platform.platform(), "tk_version": tk_version,
              "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "skipped": skipped, "require_gui": args.require_gui, "passed": passed}
    if args.report:
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
