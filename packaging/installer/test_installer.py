import unittest
from pathlib import Path


class InstallerContractTests(unittest.TestCase):
    def test_inno_setup_is_a_current_user_single_exe_installer(self):
        script = Path(__file__).with_name("CareerPilot.iss").read_text(encoding="utf-8")
        self.assertIn("OutputBaseFilename=CareerPilotSetup", script)
        self.assertIn("PrivilegesRequired=lowest", script)
        self.assertIn("DefaultDirName={localappdata}\\Programs\\CareerPilot", script)
        self.assertIn("Filename: \"{app}\\CareerPilot.exe\"", script)
        self.assertIn("[UninstallRun]", script)

    def test_build_uses_a_standard_ico_container(self):
        script = Path(__file__).parents[1].joinpath("build.ps1").read_text(encoding="utf-8")
        self.assertNotIn("ImageFormat]::Icon", script)

    def test_build_uses_inno_setup_and_bundles_queue_runtime(self):
        script = Path(__file__).parents[1].joinpath("build.ps1").read_text(encoding="utf-8")
        self.assertIn("garnet-win-x64", script)
        self.assertIn("dotnet-runtime-", script)
        self.assertIn("ISCC.exe", script)
        self.assertIn("CareerPilot.iss", script)
        self.assertNotIn("--onefile --name CareerPilotSetup", script)

    def test_desktop_shell_owns_the_service_lifecycle(self):
        script = Path(__file__).parents[2].joinpath("desktop", "main.cjs").read_text(encoding="utf-8")
        self.assertIn("app.requestSingleInstanceLock()", script)
        self.assertIn("spawn(backendExe", script)
        self.assertIn("pg_ctl.exe", script)
        self.assertIn("app.on(\"before-quit\", shutdown)", script)
        self.assertIn("await stopPostgres()", script)
        self.assertIn("GarnetServer.exe", script)
        self.assertIn("queue_pid", script)
        self.assertIn("CELERY_BROKER_URL", script)
        self.assertNotIn("请先启动 127.0.0.1:6379", script)

    def test_desktop_shell_uses_ninety_percent_zoom(self):
        script = Path(__file__).parents[2].joinpath("desktop", "main.cjs").read_text(encoding="utf-8")
        self.assertIn("zoomFactor: 0.9", script)

    def test_stop_script_stops_the_embedded_queue(self):
        script = Path(__file__).parents[1].joinpath("installed", "stop.ps1").read_text(encoding="utf-8")
        self.assertIn("$state.queue_pid", script)

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
