#!/usr/bin/env python3
"""
Создание компактного текстового снапшота проекта.
Исключает бинарники и большие файлы (включая JSON-дампы).
"""

from pathlib import Path
from datetime import datetime

# === Настройка ===
PROJECT_DIR   = Path(r"C:\Code Projects\Bet_AI_pythone")  # ваш проект
SNAP_DIR      = PROJECT_DIR / "snapshots"
MAX_SNAPS     = 5
MAX_INLINE_KB = 200  # порог для встраивания содержимого

# Директории и файлы, которые не нужно обрабатывать
EXCLUDE_DIRS   = {".venv", "snapshots", "__pycache__", ".git", ".streamlit"}
EXCLUDE_NAMES  = {".env", "secrets.toml"}

# Расширения, которые считаются «бинарными» и полностью пропускаются
BINARY_EXTS = {
    ".sqlite", ".db", ".log",
    ".png", ".jpg", ".jpeg", ".gif",
    ".bin", ".exe", ".pkl",
    ".json"    # теперь исключаем и JSON-файлы
}

# Создадим папку для снапшотов, если её нет
SNAP_DIR.mkdir(exist_ok=True)

# Имя нового снапшота
timestamp     = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
snapshot_file = SNAP_DIR / f"snapshot_{timestamp}.txt"


def should_skip(path: Path) -> bool:
    """
    Возвращает True, если данный путь нужно полностью пропустить.
    """
    # по части пути (директория)
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return True
    # по точному имени
    if path.name in EXCLUDE_NAMES:
        return True
    # по расширению
    if path.suffix.lower() in BINARY_EXTS:
        return True
    return False


def create_snapshot():
    with snapshot_file.open("w", encoding="utf-8") as out:
        out.write(f"=== Snapshot of {PROJECT_DIR} at {datetime.now()} ===\n\n")

        for p in sorted(PROJECT_DIR.rglob("*")):
            rel = p.relative_to(PROJECT_DIR)
            if should_skip(p):
                continue

            if p.is_dir():
                out.write(f"[DIR ] {rel}\n")
            else:
                size_kb = p.stat().st_size // 1024
                out.write(f"[FILE] {rel} ({size_kb} KB)\n")

                # Если файл слишком большой — не встраиваем содержимое
                if size_kb > MAX_INLINE_KB:
                    out.write(f"  # skipped content ({size_kb} KB > {MAX_INLINE_KB} KB)\n\n")
                    continue

                # Встроим текстовый файл
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    out.write(f"  # unable to read file: {e}\n\n")
                    continue

                out.write("----- begin content -----\n")
                out.write(text)
                out.write("\n-----  end content  -----\n\n")

        out.write("=== End of snapshot ===\n")

    print(f"✅ Snapshot saved to: {snapshot_file}")


def prune_old_snapshots():
    snaps = sorted(
        SNAP_DIR.glob("snapshot_*.txt"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )
    for old in snaps[MAX_SNAPS:]:
        try:
            old.unlink()
            print(f"🗑 Removed old snapshot: {old.name}")
        except Exception:
            pass


if __name__ == "__main__":
    create_snapshot()
    prune_old_snapshots()
