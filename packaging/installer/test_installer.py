import unittest
from pathlib import Path


class InstallerContractTests(unittest.TestCase):
    def test_install_script_uses_already_extracted_source(self):
        script = Path(__file__).with_name("install.ps1").read_text(encoding="utf-8")
        self.assertNotIn("payload.zip", script)
        self.assertNotIn("Expand-Archive", script)

    def test_build_uses_a_standard_ico_container(self):
        script = Path(__file__).parents[1].joinpath("build.ps1").read_text(encoding="utf-8")
        self.assertNotIn("ImageFormat]::Icon", script)

    def test_start_script_waits_for_postgres_readiness_without_waiting_for_pg_ctl(self):
        script = Path(__file__).parents[1].joinpath("installed", "start.ps1").read_text(encoding="utf-8")
        self.assertNotIn("-o \"-h 127.0.0.1 -p $dbPort\" start *>", script)
        self.assertNotIn("start\" -Wait", script)
        self.assertIn("start -W", script)
        self.assertIn("function Test-Postgres", script)
        self.assertIn("$originalErrorActionPreference = $ErrorActionPreference", script)

    def test_start_script_allows_an_uninitialized_database_directory(self):
        script = Path(__file__).parents[1].joinpath("installed", "start.ps1").read_text(encoding="utf-8")
        self.assertIn("$pgStatus = & $pgCtl -D $dbData status 2>$null", script)
        self.assertNotIn("$pgCtl -D $dbData status 2>&1", script)

    def test_launchers_show_progress_instead_of_hiding_it(self):
        vbs = Path(__file__).parents[1].joinpath("installed", "start.vbs").read_text(encoding="utf-8")
        script = Path(__file__).parents[1].joinpath("installed", "start.ps1").read_text(encoding="utf-8")
        launcher = Path(__file__).with_name("launcher.py").read_text(encoding="utf-8")
        self.assertIn("shell.Run command, 1, False", vbs)
        self.assertIn("Write-Host '职航正在启动，请稍候...'", script)
        self.assertIn('print("正在安装职航 CareerPilot...")', launcher)


if __name__ == "__main__":
    unittest.main()
