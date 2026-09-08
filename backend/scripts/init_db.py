"""建表脚本：创建 5 张表。直接运行 `python -m scripts.init_db`。"""

from app.db import Base, engine

# 导入 models 触发 ORM 注册（否则 Base.metadata 里没有表）
import app.models  # noqa: F401


def main() -> None:
    Base.metadata.create_all(engine)
    tables = ", ".join(sorted(Base.metadata.tables.keys()))
    print(f"建表完成：{tables}")


if __name__ == "__main__":
    main()
