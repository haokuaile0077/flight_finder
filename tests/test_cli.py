"""验证解压后的入口、非项目工作目录和启动错误处理。"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def command(self, *args, cwd=None):
        # 子进程写入与父进程解码统一使用UTF-8，不依赖Windows区域或IDE环境。
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run([sys.executable, str(ROOT/"main.py"), *args], cwd=cwd,
                              text=True, encoding="utf-8", capture_output=True, timeout=15, env=env)

    def test_check_from_another_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            result = self.command("--check", cwd=folder)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("灵活查询检查通过", result.stdout)

    def test_missing_data_clean_error(self):
        result = self.command("--check", "--data", str(ROOT/"absent.json"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("启动失败", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_discount_clean_error(self):
        result = self.command("--check", "--discount", str(ROOT/"absent.json"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("优惠配置", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
