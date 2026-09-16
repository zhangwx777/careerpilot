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

    def test_install_script_targets_the_desktop_application(self):
        script = Path(__file__).with_name("install.ps1").read_text(encoding="utf-8")
        self.assertIn("CareerPilot.exe", script)
        self.assertIn("-WorkingDirectory $installRoot", script)
        self.assertNotIn("start.vbs", script)
        self.assertNotIn("wscript.exe", script)

    def test_desktop_shell_owns_the_service_lifecycle(self):
        script = Path(__file__).parents[2].joinpath("desktop", "main.cjs").read_text(encoding="utf-8")
        self.assertIn("app.requestSingleInstanceLock()", script)
        self.assertIn("spawn(backendExe", script)
        self.assertIn("pg_ctl.exe", script)
        self.assertIn("app.on(\"before-quit\", shutdown)", script)
        self.assertIn("await stopPostgres()", script)
        self.assertNotIn("postgres-start.log", script)

    def test_desktop_shell_uses_ninety_percent_zoom(self):
        script = Path(__file__).parents[2].joinpath("desktop", "main.cjs").read_text(encoding="utf-8")
        self.assertIn("zoomFactor: 0.9", script)

    def test_build_pins_the_electron_runtime_version(self):
        script = Path(__file__).parents[1].joinpath("build.ps1").read_text(encoding="utf-8")
        self.assertIn("--electron-version=37.10.3", script)

    def test_build_splits_runtime_and_app_layers(self):
        script = Path(__file__).parents[1].joinpath("build.ps1").read_text(encoding="utf-8")
        # 运行时层放冻结依赖与内嵌 PG，应用层放明文源码与前端 dist
        self.assertIn("$runtimeRoot = Join-Path $payloadRoot 'runtime'", script)
        self.assertIn("$appLayer = Join-Path $payloadRoot 'app'", script)
        self.assertIn("--onedir --name CareerPilotBackend", script)

    def test_build_supports_app_only_fast_rebuild(self):
        script = Path(__file__).parents[1].joinpath("build.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$AppOnly", script)

    def test_desktop_shell_targets_layered_paths(self):
        script = Path(__file__).parents[2].joinpath("desktop", "main.cjs").read_text(encoding="utf-8")
        # 后端与 PG 位于运行时层，源码根经环境变量注入应用层
        self.assertIn('path.join(runtimeRoot, "backend", "CareerPilotBackend.exe")', script)
        self.assertIn('path.join(runtimeRoot, "postgresql", "bin")', script)
        self.assertIn("CAREERPILOT_APP_ROOT: appLayer", script)


if __name__ == "__main__":
    unittest.main()
