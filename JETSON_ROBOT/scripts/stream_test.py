"""[2026-08-04] 독립 WebRTC 스트림 테스트: RAW 카메라 + 검출 박스 -> AWS StreamSession -> 대시보드.

로봇(main.py) 없이 카메라 영상(검출 박스 포함)을 AWS로 라이브 스트리밍한다.
흐름: RAW 카메라 -> (엔진 추론 + 박스 그리기) -> DiseaseStreamPublisher(aiortc) -> AWS /stream/session
      -> 관리자 대시보드 live 뷰에서 확인.

필요: aiortc, av (미설치면 pub.start()에서 ImportError - 나노 설치는 별도, README 참고).
      AWS 서버가 로컬로 켜져 있어야 함(cfg.aws_api_base). best.engine + RAW 카메라 설정.

실행:
    python3 scripts/stream_test.py                 # 박스 포함 스트리밍
    python3 scripts/stream_test.py --no-boxes       # RAW 영상만(가벼움)
    python3 scripts/stream_test.py --minutes 5
"""

import argparse
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from config.settings import settings as cfg  # noqa: E402
from ai.detector.frame_hub import SharedFrameCamera  # noqa: E402
from ai.detector.yolo_postprocess import (  # noqa: E402
    letterbox_params, nms, decode_yolov5_output, decode_yolov8_output,
)
from cloud.api_client import CloudClient  # noqa: E402
from robot.webrtc_publisher import DiseaseStreamPublisher  # noqa: E402

CLASS_NAMES = list(cfg.yolo_class_names)
COLORS = {0: (0, 220, 0), 1: (0, 140, 255), 2: (0, 0, 255)}


class AnnotatedCamera:
    """raw 카메라 프레임에 검출 박스를 그려 get_latest_frame()로 내보내는 래퍼.
    자체 스레드에서 추론(자체 CUDA 컨텍스트)하고 최신 '박스 그린' 프레임만 저장한다.
    DiseaseStreamPublisher가 get_latest_frame()을 읽어 스트리밍하므로 박스가 그대로 전송된다.
    (추론은 이 스레드에서만 -> aiortc recv 스레드에서 CUDA 안 건드려 안전.)"""

    def __init__(self, raw_cam, engine_path, draw=True):
        self.raw_cam = raw_cam
        self.draw = draw
        self._latest = None
        self._lock = threading.Lock()
        self._running = True
        self._t = threading.Thread(target=self._loop, args=(engine_path,), daemon=True)
        self._t.start()

    def _loop(self, engine_path):
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
            print("[stream] engine layout={} det_w={}".format(layout, det_w))
            s = cfg.yolo_input_size

            while self._running:
                frame = self.raw_cam.get_latest_frame()
                if frame is None:
                    time.sleep(0.02); continue
                out = frame
                if self.draw:
                    out = self._infer_draw(frame, host, dev, bindings, context, stream,
                                           in_i, det_i, det_w, layout, nc, s, cuda)
                with self._lock:
                    self._latest = out
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
            raw = np.asarray(host[det_i]).reshape(-1, det_w)
            dets = decode_yolov5_output(raw, nc, cfg.yolo_conf_threshold)
        else:
            raw = np.asarray(host[det_i]).reshape(4 + nc, -1)
            dets = decode_yolov8_output(raw, nc, cfg.yolo_conf_threshold)
        kept = nms(dets, cfg.yolo_iou_threshold)
        out = frame.copy()
        for conf, cid, cx, cy, w, h in kept:
            x1 = int((cx - w / 2 - px) / scale); y1 = int((cy - h / 2 - py) / scale)
            x2 = int((cx + w / 2 - px) / scale); y2 = int((cy + h / 2 - py) / scale)
            col = COLORS.get(cid, (200, 200, 200))
            name = CLASS_NAMES[cid] if cid < nc else str(cid)
            cv2.rectangle(out, (x1, y1), (x2, y2), col, 2)
            cv2.putText(out, "%s %.2f" % (name, conf), (x1, max(20, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
        return out

    def get_latest_frame(self):
        with self._lock:
            return None if self._latest is None else self._latest.copy()

    def close(self):
        self._running = False
        try:
            self._t.join(timeout=1.5)
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description="독립 WebRTC 스트림 테스트")
    ap.add_argument("--no-boxes", action="store_true", help="박스 없이 RAW 영상만 스트리밍")
    ap.add_argument("--minutes", type=float, default=10, help="스트리밍 유지 시간(분)")
    args = ap.parse_args()

    cloud = CloudClient(cfg.aws_api_base, cfg.api_key)
    print("AWS:", cfg.aws_api_base, "| robot:", cfg.robot_id)

    # 대시보드에 라이브뷰가 뜨도록 vision event + decision request 생성(테스트용).
    ev = cloud.post_vision_event(cfg.robot_id, {"status": "powdery_mildew", "confidence": 0.5, "cell_id": 1})
    req = cloud.create_decision_request(cfg.robot_id, ev["id"], "powdery_mildew", cell=1)
    print("decision request id:", req.get("id"))

    raw = SharedFrameCamera(cv2, cfg.csi_camera_index, cfg.frame_width, cfg.frame_height)
    ann = AnnotatedCamera(raw, cfg.yolo_model_path, draw=not args.no_boxes)

    print("첫 프레임 대기...")
    t_end = time.time() + 8
    while ann.get_latest_frame() is None and time.time() < t_end:
        time.sleep(0.1)
    if ann.get_latest_frame() is None:
        print("[FAIL] 프레임 없음 - 카메라 확인")
        ann.close(); raw.close(); return 1

    pub = DiseaseStreamPublisher(cloud, ann, cfg.robot_id)
    try:
        sid = pub.start(req["id"])
        print("스트림 세션 시작:", sid)
        print("대시보드에서 이 요청의 라이브뷰 열어봐 -> {}/".format(cfg.aws_api_base))
        print("Ctrl+C 로 종료. {}분 유지.".format(args.minutes))
        time.sleep(args.minutes * 60)
    except ImportError as e:
        print("[FAIL] aiortc/av 미설치:", e)
        print("  설치 필요 (나노): apt로 ffmpeg dev + pip install av aiortc (README 참고)")
    except KeyboardInterrupt:
        print("\n중단")
    finally:
        try:
            pub.stop()
        except Exception as e:
            print("pub.stop 오류(무시):", e)
        ann.close(); raw.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
