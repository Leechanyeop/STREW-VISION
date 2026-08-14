"""[2026-08-04] MJPEG HTTP 스트리머 - RAW 카메라 + 검출 박스를 브라우저로 라이브 전송.

aiortc/WebRTC 없이(나노에서 빌드 지옥이라) 카메라 영상을 원격에서 본다.
의존성: 표준 http.server + cv2 + tensorrt/pycuda(이미 있음). 추가 설치 0. LAN만 있으면 됨.

흐름: RAW 카메라 -> (엔진 추론 + 박스 그리기, 자체 스레드+CUDA) -> JPEG 인코딩
      -> HTTP multipart/x-mixed-replace 로 계속 전송.

실행 (젯슨):
    python3 scripts/stream_mjpeg.py                 # 박스 포함, 포트 8090
    python3 scripts/stream_mjpeg.py --no-boxes       # RAW 영상만(가벼움)
    python3 scripts/stream_mjpeg.py --port 8090 --fps 12 --quality 80

보기: 같은 공유기의 PC 브라우저에서  http://<젯슨IP>:8090/
대시보드에 넣기:  <img src="http://<젯슨IP>:8090/stream">
"""

import argparse
import sys
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from config.settings import settings as cfg  # noqa: E402
from ai.detector.frame_hub import SharedFrameCamera  # noqa: E402
from ai.detector.yolo_postprocess import (  # noqa: E402
    letterbox_params, nms, decode_yolov5_output, decode_yolov8_output,
)

CLASS_NAMES = list(cfg.yolo_class_names)
COLORS = {0: (0, 220, 0), 1: (0, 140, 255), 2: (0, 0, 255)}

STREAMER = None   # 전역: HTTP 핸들러가 최신 JPEG를 읽는다


class Streamer:
    """RAW 카메라 프레임에 검출 박스를 그려 JPEG로 인코딩해 최신 1장을 보관(자체 스레드+CUDA)."""

    def __init__(self, engine_path, draw=True, quality=80):
        self.draw = draw
        self.quality = quality
        self._jpg = None
        self._lock = threading.Lock()
        self._running = True
        self.raw = SharedFrameCamera(cv2, cfg.csi_camera_index, cfg.frame_width, cfg.frame_height)
        self._t = threading.Thread(target=self._loop, args=(engine_path,), daemon=True)
        self._t.start()

    def _loop(self, engine_path):
        jpg_params = [cv2.IMWRITE_JPEG_QUALITY, self.quality]

        # [--no-boxes] 박스 없으면 엔진/CUDA 불필요 - RAW 프레임만 인코딩(가볍고 안전).
        if not self.draw:
            print("[mjpeg] draw=False - 엔진 없이 RAW 스트림")
            while self._running:
                frame = self.raw.get_latest_frame()
                if frame is None:
                    time.sleep(0.02); continue
                ok, buf = cv2.imencode(".jpg", frame, jpg_params)
                if ok:
                    with self._lock:
                        self._jpg = buf.tobytes()
            return

        import tensorrt as trt
        import pycuda.driver as cuda
        cuda.init()
        ctx = cuda.Device(0).make_context()
        try:
            logger = trt.Logger(trt.Logger.WARNING)
            with open(engine_path, "rb") as f:
                engine = trt.Runtime(logger).deserialize_cuda_engine(f.read())
            context = engine.create_execution_context()
            stream = cuda.Stream()
            n = engine.num_bindings
            bindings, host, dev = [None] * n, [None] * n, [None] * n
            in_i, outs = None, []
            for i in range(n):
                shp = engine.get_binding_shape(i)
                host[i] = cuda.pagelocked_empty(trt.volume(shp), trt.nptype(engine.get_binding_dtype(i)))
                dev[i] = cuda.mem_alloc(host[i].nbytes)
                bindings[i] = int(dev[i])
                if engine.binding_is_input(i):
                    in_i = i
                else:
                    outs.append((i, tuple(int(x) for x in shp)))
            nc = len(CLASS_NAMES)
            det_i, det_w, layout = outs[0][0], 4 + nc, "v8"
            for i, shp in outs:
                if shp[-1] in (5 + nc, 5 + nc + 32):
                    det_i, det_w, layout = i, shp[-1], "v5"; break
                if len(shp) >= 2 and shp[1] == 4 + nc:
                    det_i, det_w, layout = i, 4 + nc, "v8"; break
            print("[mjpeg] engine layout={} det_w={} draw={}".format(layout, det_w, self.draw))
            s = cfg.yolo_input_size
            jpg_params = [cv2.IMWRITE_JPEG_QUALITY, self.quality]

            while self._running:
                frame = self.raw.get_latest_frame()
                if frame is None:
                    time.sleep(0.02); continue
                out = frame
                if self.draw:
                    out = self._infer_draw(frame, host, dev, bindings, context, stream,
                                           in_i, det_i, det_w, layout, nc, s, cuda)
                ok, buf = cv2.imencode(".jpg", out, jpg_params)
                if ok:
                    with self._lock:
                        self._jpg = buf.tobytes()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print("[mjpeg] 추론 스레드 오류(스트림 중단):", e)
        finally:
            try:
                ctx.pop(); ctx.detach()
            except Exception:
                pass

    def _infer_draw(self, frame, host, dev, bindings, context, stream, in_i, det_i, det_w, layout, nc, s, cuda):
        fh, fw = frame.shape[:2]
        scale, px, py = letterbox_params(fw, fh, s)
        nw, nh = int(round(fw * scale)), int(round(fh * scale))
        canvas = np.full((s, s, 3), 114, np.uint8)
        canvas[py:py + nh, px:px + nw] = cv2.resize(frame, (nw, nh))
        blob = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0)
        np.copyto(host[in_i], blob.ravel())
        cuda.memcpy_htod_async(dev[in_i], host[in_i], stream)
        context.execute_async_v2(bindings, stream.handle)
        cuda.memcpy_dtoh_async(host[det_i], dev[det_i], stream)
        stream.synchronize()
        if layout == "v5":
            dets = decode_yolov5_output(np.asarray(host[det_i]).reshape(-1, det_w), nc, cfg.yolo_conf_threshold)
        else:
            dets = decode_yolov8_output(np.asarray(host[det_i]).reshape(4 + nc, -1), nc, cfg.yolo_conf_threshold)
        out = frame.copy()
        for conf, cid, cx, cy, w, h in nms(dets, cfg.yolo_iou_threshold):
            x1 = int((cx - w / 2 - px) / scale); y1 = int((cy - h / 2 - py) / scale)
            x2 = int((cx + w / 2 - px) / scale); y2 = int((cy + h / 2 - py) / scale)
            col = COLORS.get(cid, (200, 200, 200))
            name = CLASS_NAMES[cid] if cid < nc else str(cid)
            cv2.rectangle(out, (x1, y1), (x2, y2), col, 2)
            cv2.putText(out, "%s %.2f" % (name, conf), (x1, max(20, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
        return out

    def get_jpeg(self):
        with self._lock:
            return self._jpg

    def close(self):
        self._running = False
        try:
            self.raw.close()
        except Exception:
            pass


_PAGE = b"""<!doctype html><html><head><meta charset=utf-8><title>STREW_VISION Live</title>
<style>body{margin:0;background:#111}img{width:100%;height:auto;display:block}</style></head>
<body><img src="/stream"></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # 접속 로그 조용히

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(_PAGE)
            return
        if self.path.startswith("/stream"):
            self.send_response(200)
            self.send_header("Age", "0")
            self.send_header("Cache-Control", "no-cache, private")
            self.send_header("Pragma", "no-cache")
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            interval = 1.0 / max(self.server.fps, 1)
            try:
                while True:
                    jpg = STREAMER.get_jpeg() if STREAMER is not None else None
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


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    global STREAMER
    ap = argparse.ArgumentParser(description="MJPEG 카메라 스트리머")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--fps", type=int, default=12, help="스트림 전송 FPS")
    ap.add_argument("--quality", type=int, default=80, help="JPEG 품질 1~100")
    ap.add_argument("--no-boxes", action="store_true", help="박스 없이 RAW 영상만")
    args = ap.parse_args()

    STREAMER = Streamer(cfg.yolo_model_path, draw=not args.no_boxes, quality=args.quality)
    print("첫 프레임 대기...")
    t_end = time.time() + 8
    while STREAMER.get_jpeg() is None and time.time() < t_end:
        time.sleep(0.1)
    if STREAMER.get_jpeg() is None:
        print("[FAIL] 프레임 없음 - 카메라 확인"); STREAMER.close(); return 1

    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    srv.fps = args.fps
    print("=" * 50)
    print(" MJPEG 스트림 시작")
    print("  브라우저:  http://<젯슨IP>:{}/".format(args.port))
    print("  대시보드:  <img src=\"http://<젯슨IP>:{}/stream\">".format(args.port))
    print("  (젯슨 IP 확인:  hostname -I)")
    print("  Ctrl+C 로 종료")
    print("=" * 50)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n종료 중...")
    finally:
        srv.shutdown()
        STREAMER.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
