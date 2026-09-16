import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main() -> int:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    print("正在安装职航 CareerPilot...")
    with tempfile.TemporaryDirectory(prefix="CareerPilotSetup-") as temp:
        extract = Path(temp)
        with zipfile.ZipFile(root / "payload.zip") as archive:
            archive.extractall(extract)
        powershell = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        result = subprocess.run(
            [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(extract / "install.ps1")],
            cwd=extract,
        )
    if result.returncode == 0:
        print("安装完成，正在启动职航...")
    else:
        print("安装失败，请检查安装目录后重试。")
        input("按 Enter 关闭此窗口...")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
