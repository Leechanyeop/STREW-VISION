"""[2026-08-04] 대시보드 라이브 스트림 서버 (MJPEG, main.py 안에서 구동).

카메라 1개를 로봇 추론과 공유(SharedFrameCamera)하기 위해, 별도 프로세스(stream_mjpeg.py)가
아니라 main.py(RobotAgent) 안에서 이 서버를 띄운다. 자체 추론은 하지 않고, get_frame 콜백
(보통 CsiCameraVisionSource.get_stream_frame - 최근 검사 박스가 있으면 그걸, 없으면 raw 라이브)
이 주는 프레임을 JPEG로 인코딩해 HTTP multipart로 송출한다.

의존성: 표준 http.server + cv2. 추가 설치 0.
브라우저/대시보드:  http://<젯슨IP>:8090/  (또는 <img src="...:8090/stream">)
"""

import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


_PAGE = b"""<!doctype html><html><head><meta charset=utf-8><title>STREW_VISION Live</title>
<style>body{margin:0;background:#111}img{width:100%;height:auto;display:block}</style></head>
<body><img src="/stream"></body></html>"""


class VisionStreamServer:
    """get_frame() 콜백이 주는 BGR 프레임을 MJPEG로 송출하는 경량 서버."""

    def __init__(self, get_frame, port=8090, fps=12, quality=80):
        import cv2
        self.cv2 = cv2
        self.get_frame = get_frame
        self.quality = quality
        self._jpg = None
        self._lock = threading.Lock()
        self._running = True

        self._enc_t = threading.Thread(target=self._encode_loop, args=(fps,), daemon=True)
        self._enc_t.start()

        server = self  # 핸들러가 최신 JPEG를 읽도록 참조 주입

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(_PAGE)
                    return
                if self.path.startswith("/stream"):
                    self.send_response(200)
                    self.send_header("Cache-Control", "no-cache, private")
                    self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                    self.end_headers()
                    interval = 1.0 / max(fps, 1)
                    try:
                        while server._running:
                            jpg = server.get_jpg()
                            if jpg is None:
                                time.sleep(0.05); continue
                            self.wfile.write(b"--frame\r\n")
                            self.wfile.write(b"Content-Type: image/jpeg\r\n")
                            self.wfile.write(("Content-Length: %d\r\n\r\n" % len(jpg)).encode())
                            self.wfile.write(jpg)
                            self.wfile.write(b"\r\n")
                            time.sleep(interval)
                    except (BrokenPipeError, ConnectionResetError):
                        return
                    return
                self.send_error(404)

        self._srv = _ThreadingHTTPServer(("0.0.0.0", port), Handler)
        self._srv_t = threading.Thread(target=self._srv.serve_forever, daemon=True)
        self._srv_t.start()
        print("[stream] MJPEG 라이브 스트림 시작: http://0.0.0.0:%d/  (대시보드 Live Stream에서 이 주소)" % port)

    def _encode_loop(self, fps):
        interval = 1.0 / max(fps, 1)
        params = [self.cv2.IMWRITE_JPEG_QUALITY, self.quality]
        while self._running:
            frame = None
            try:
                frame = self.get_frame()
            except Exception:
                frame = None
            if frame is not None:
                ok, buf = self.cv2.imencode(".jpg", frame, params)
                if ok:
                    with self._lock:
                        self._jpg = buf.tobytes()
            time.sleep(interval)

    def get_jpg(self):
        with self._lock:
            return self._jpg

    def close(self):
        self._running = False
        try:
            self._srv.shutdown()
        except Exception:
            pass
        try:
            self._srv.server_close()
        except Exception:
            pass
