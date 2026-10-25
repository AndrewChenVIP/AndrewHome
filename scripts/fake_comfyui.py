"""假 ComfyUI——测试专用：起一个 /system_stats 服务，写日志，直到被杀。

用法: python fake_comfyui.py --port 18188 --log-file x.log [--delay 1.0]
"""
from __future__ import annotations

import argparse
import http.server
import time


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--log-file", required=True)
    ap.add_argument("--delay", type=float, default=0.0, help="就绪前人为延迟（秒）")
    args = ap.parse_args()

    with open(args.log_file, "a", encoding="utf-8") as log:
        log.write(f"fake-comfyui starting port={args.port}\n")
        log.flush()
        if args.delay:
            time.sleep(args.delay)

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path == "/system_stats":
                    body = b'{"status": "ok"}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, fmt, *a):
                log.write(fmt % a + "\n")
                log.flush()

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
        log.write("fake-comfyui READY\n")
        log.flush()
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            srv.server_close()


if __name__ == "__main__":
    main()
