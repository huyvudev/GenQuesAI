"""CDI · watch-folder — bỏ PDF vào thư mục → TỰ nạp (CDI-4a; gỡ G1).

"Đặt PDF vào inbox, hệ thống tự ingest" — không cần nhớ chạy lệnh.
Dùng `watchdog` nếu đã cài (event-driven); nếu chưa → POLLING fallback (không thêm dep cứng).
Mỗi mẻ file mới gọi `ingest_pdfs` (AUTO: dedup + validation gate làm lưới an toàn).
File đã xử lý được CHUYỂN sang `<inbox>/_done` để không nạp lại.
"""
from __future__ import annotations
import time
from pathlib import Path
from typing import Callable


def _stable(p: Path, settle: float = 1.5) -> bool:
    """File đã ghi xong? (kích thước không đổi sau `settle` giây) — tránh đọc file đang copy."""
    try:
        s1 = p.stat().st_size
        time.sleep(settle)
        return p.exists() and p.stat().st_size == s1
    except OSError:
        return False


def _process(inbox: Path, done: Path, handler: Callable[[Path], dict], log) -> None:
    pdfs = [p for p in sorted(inbox.glob("*.pdf")) if _stable(p)]
    if not pdfs:
        return
    log(f"[watch] {len(pdfs)} PDF mới → nạp")
    # handler nhận THƯ MỤC inbox (ingest_pdfs glob *.pdf trong đó), rồi move file đã xử lý
    res = handler(inbox)
    log(f"[watch] kết quả: {res.get('nap', 0)} nạp / {res.get('bo_trung', 0)} trùng / "
        f"{len(res.get('quarantine', []))} quarantine")
    done.mkdir(parents=True, exist_ok=True)
    for p in pdfs:
        try:
            p.rename(done / p.name)
        except OSError:
            pass


def watch_folder(inbox, handler: Callable[[Path], dict], *, poll_interval: float = 5.0,
                 use_watchdog: bool = True, log=print) -> None:
    """Vòng lặp theo dõi inbox (BLOCKING — cho CLI `cdi watch`). handler(inbox_dir) -> dict tổng kết."""
    inbox = Path(inbox)
    inbox.mkdir(parents=True, exist_ok=True)
    done = inbox / "_done"
    log(f"[watch] theo dõi {inbox} (Ctrl-C để dừng)")
    _process(inbox, done, handler, log)        # nạp các file đã có sẵn lúc khởi động

    if use_watchdog:
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ModuleNotFoundError:
            log("[watch] chưa cài 'watchdog' → dùng polling. (uv add watchdog để bật event-driven)")
            use_watchdog = False

    if use_watchdog:
        class _H(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory and str(event.src_path).lower().endswith(".pdf"):
                    _process(inbox, done, handler, log)

            on_moved = lambda self, e: self.on_created(e)  # noqa: E731

        obs = Observer()
        obs.schedule(_H(), str(inbox), recursive=False)
        obs.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            obs.stop()
        obs.join()
    else:
        try:
            while True:
                time.sleep(poll_interval)
                _process(inbox, done, handler, log)
        except KeyboardInterrupt:
            pass
