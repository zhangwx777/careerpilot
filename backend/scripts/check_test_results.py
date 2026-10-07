"""Reject skipped or empty suites when verifying the full release baseline."""

import sys
from xml.etree import ElementTree


def main() -> None:
    root = ElementTree.parse(sys.argv[1]).getroot()
    cases = list(root.iter("testcase"))
    if not cases or any(case.find("skipped") is not None for case in cases):
        raise SystemExit("完整验证要求运行全部测试；空测试集或 skipped 不算通过")
    print(f"完整验证：{len(cases)} 个测试，0 skipped")


if __name__ == "__main__":
    main()
