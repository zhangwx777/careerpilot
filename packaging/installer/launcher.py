import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path


def main() -> int:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    with tempfile.TemporaryDirectory(prefix="CareerPilotSetup-") as temp:
        extract = Path(temp)
        with zipfile.ZipFile(root / "payload.zip") as archive:
            archive.extractall(extract)
        powershell = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        return subprocess.run(
            [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(extract / "install.ps1")],
            cwd=extract,
        ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
