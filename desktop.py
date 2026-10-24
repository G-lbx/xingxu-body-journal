"""Small desktop controller for the loopback-only Body Journal server."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import uuid
import urllib.error
import urllib.request
import webbrowser

from server import create_server, default_data_dir


APP_TITLE = "形序 · 身体控制中心"
INSTANCE_FILE = "desktop-service.json"


def _read_metadata(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _matching_instance(metadata):
    """A health response must match our data folder's random instance token."""
    port = metadata.get("port")
    token = metadata.get("token")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        return False
    if not isinstance(token, str) or len(token) != 32:
        return False
    try:
        # Do not route localhost through proxy settings on a friend's computer.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/api/health", timeout=0.8) as response:
            result = json.loads(response.read(4096))
        return (
            isinstance(result, dict)
            and result.get("status") == "ok"
            and result.get("app") == "body-journal"
            and result.get("desktop_instance") == token
        )
    except (OSError, ValueError, urllib.error.URLError):
        return False


class DesktopService:
    """Own one HTTP server, or safely refer to an already running instance."""

    def __init__(self, data_dir, port, server=None, thread=None, token=None):
        self.data_dir = Path(data_dir).resolve()
        self.port = port
        self.server = server
        self.thread = thread
        self.token = token
        self.owned = server is not None
        self.stopped = False

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/#overview"

    def stop(self):
        """Never send a shutdown request to an instance owned by another window."""
        if self.stopped:
            return
        self.stopped = True
        if not self.owned:
            return
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        metadata_path = self.data_dir / INSTANCE_FILE
        if _read_metadata(metadata_path).get("token") == self.token:
            try:
                metadata_path.unlink(missing_ok=True)
            except OSError:
                pass


def start_service(port=8765, data_dir=None, max_port=None):
    """Start at the preferred port and try at most 15 higher ports if needed."""
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("端口须为 0 至 65535 之间的整数。")
    directory = Path(data_dir or default_data_dir()).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    metadata_path = directory / INSTANCE_FILE
    metadata = _read_metadata(metadata_path)
    if _matching_instance(metadata):
        return DesktopService(directory, metadata["port"])
    last_port = min(65535, port + 15) if max_port is None else max_port
    if port == 0:
        ports = [0]
    else:
        if not port <= last_port <= 65535:
            raise ValueError("候选端口范围无效。")
        ports = range(port, last_port + 1)
    last_error = None
    for candidate in ports:
        try:
            http_server = create_server(host="127.0.0.1", port=candidate, data_dir=directory, seed=False)
        except OSError as error:
            # Only a busy/forbidden port justifies trying a different port. Disk
            # errors must retain their real cause and must not be reported as busy.
            if getattr(error, "winerror", None) not in {10013, 10048} and error.errno not in {13, 48, 98, 10013, 10048}:
                raise
            last_error = error
            continue
        token = uuid.uuid4().hex
        http_server.desktop_instance = token
        thread = threading.Thread(target=http_server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True, name="body-journal-http")
        service = DesktopService(directory, http_server.server_port, http_server, thread, token)
        temporary = metadata_path.with_name(f".{INSTANCE_FILE}.{os.getpid()}.tmp")
        try:
            temporary.write_text(json.dumps({"port": service.port, "token": token, "pid": os.getpid()}, ensure_ascii=False), encoding="utf-8")
            temporary.replace(metadata_path)
            thread.start()
        except BaseException:
            http_server.server_close()
            temporary.unlink(missing_ok=True)
            if _read_metadata(metadata_path).get("token") == token:
                metadata_path.unlink(missing_ok=True)
            raise
        return service
    raise RuntimeError(f"本机 {port}–{last_port} 端口均不可用。请关闭占用端口的程序，或使用 --port 指定其他端口。") from last_error


def run_window(service, open_browser=True):
    import tkinter as tk
    from tkinter import messagebox

    window = tk.Tk()
    window.title(APP_TITLE)
    window.geometry("550x385")
    window.minsize(510, 365)
    window.configure(bg="#101116")
    font = ("PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei UI", 10)
    frame = tk.Frame(window, bg="#101116", padx=28, pady=24)
    frame.pack(expand=True, fill="both")
    tk.Label(frame, text="形序  /  BODY JOURNAL", fg="#edc375", bg="#101116", font=(font[0], 17, "bold")).pack(anchor="w")
    status = "本机服务已启动" if service.owned else "已连接正在运行的形序"
    tk.Label(frame, text="●  " + status, fg="#80ddd4", bg="#101116", font=font, pady=14).pack(anchor="w")
    tk.Label(frame, text=service.url, fg="#eeeeef", bg="#101116", font=font).pack(anchor="w")
    description = "数据只保存在这台电脑上。\n使用期间请保留此控制窗口，关闭浏览器不会丢失记录。" if service.owned else "这是已有服务的辅助窗口。\n关闭此窗口不会停止原来运行的形序。"
    tk.Label(frame, text=description, justify="left", fg="#a8a9b2", bg="#101116", font=font, pady=14).pack(anchor="w")
    row = tk.Frame(frame, bg="#101116")
    row.pack(fill="x", pady=(4, 18))

    def open_page():
        if not webbrowser.open(service.url):
            messagebox.showinfo(APP_TITLE, "请复制以下地址到浏览器打开：\n" + service.url, parent=window)

    def open_folder():
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["/usr/bin/open", str(service.data_dir)])
            else:
                os.startfile(str(service.data_dir))
        except OSError as error:
            messagebox.showerror(APP_TITLE, f"无法打开数据文件夹：{error}", parent=window)

    def close():
        if service.owned and not messagebox.askokcancel(APP_TITLE, "停止本机服务并退出形序？\n已保存的记录会保留，网页将暂时无法连接。", parent=window):
            return
        service.stop()
        window.destroy()

    button_style = dict(font=font, relief="flat", borderwidth=0, padx=16, pady=10, cursor="hand2", activeforeground="#ffffff")
    tk.Button(row, text="打开网页", command=open_page, bg="#a12c30", fg="#fff5ed", activebackground="#c03b40", **button_style).pack(side="left", padx=(0, 10))
    tk.Button(row, text="打开数据文件夹", command=open_folder, bg="#282a33", fg="#edc375", activebackground="#3a3d49", **button_style).pack(side="left")
    tk.Button(frame, text="停止并退出" if service.owned else "关闭此窗口", command=close, bg="#1c1e26", fg="#c7c8d0", activebackground="#323542", **button_style).pack(anchor="w")
    window.protocol("WM_DELETE_WINDOW", close)
    if open_browser:
        window.after(150, open_page)
    try:
        window.mainloop()
    finally:
        service.stop()


def main(argv=None):
    parser = argparse.ArgumentParser(description="形序桌面控制器：只在本机运行")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--headless", action="store_true", help="不显示控制窗口，供自动测试或终端运行")
    parser.add_argument("--check-runtime", action="store_true", help="检查桌面组件与本机 OCR 后退出，供安装排查")
    args = parser.parse_args(argv)
    service = None
    try:
        if args.check_runtime:
            import tkinter as tk
            import ocr
            window = tk.Tk()
            window.withdraw()
            window.update()
            window.destroy()
            if not ocr.available():
                raise RuntimeError("本机 OCR 组件未就绪。")
            return 0
        service = start_service(args.port, args.data_dir)
        if args.headless:
            if sys.stdout is not None:
                print(json.dumps({"url": service.url, "port": service.port, "owned": service.owned}), flush=True)
            if not args.no_browser:
                webbrowser.open(service.url)
            stopped = threading.Event()
            signal.signal(signal.SIGINT, lambda *_: stopped.set())
            if hasattr(signal, "SIGTERM"):
                signal.signal(signal.SIGTERM, lambda *_: stopped.set())
            while not stopped.wait(0.5):
                if service.owned and not service.thread.is_alive():
                    break
        else:
            run_window(service, open_browser=not args.no_browser)
        return 0
    except Exception as error:
        if args.headless:
            if sys.stderr is not None:
                print(f"形序启动失败：{error}", file=sys.stderr)
        else:
            import tkinter as tk
            from tkinter import messagebox
            window = tk.Tk()
            window.withdraw()
            messagebox.showerror(APP_TITLE, f"形序启动失败：\n{error}\n\n数据目录：{args.data_dir}", parent=window)
            window.destroy()
        return 1
    finally:
        if service is not None:
            service.stop()


if __name__ == "__main__":
    raise SystemExit(main())
