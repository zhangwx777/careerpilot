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


if __name__ == "__main__":
    unittest.main()
