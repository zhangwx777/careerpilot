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

    def test_start_script_does_not_redirect_pg_ctl_start(self):
        script = Path(__file__).parents[1].joinpath("installed", "start.ps1").read_text(encoding="utf-8")
        self.assertNotIn("-o \"-h 127.0.0.1 -p $dbPort\" start *>", script)
        self.assertIn("Start-Process -FilePath $pgCtl", script)


if __name__ == "__main__":
    unittest.main()
