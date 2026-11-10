"""Tạo file .ico cho AutoLock.exe từ icon khay (màu xanh lá)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tray import make_icon  # noqa: E402


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("build") / "autolock.ico"
    out.parent.mkdir(parents=True, exist_ok=True)
    make_icon("present", 256).save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(out)


if __name__ == "__main__":
    main()
