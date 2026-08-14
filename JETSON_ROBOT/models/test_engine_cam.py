"""[2026-08-04] best.engine 카메라 단독 테스트 (YOLOv5-seg 출력 1x25200x40 대응).

문제 2개 수정:
  1) cv2.VideoCapture(0)는 IMX708 CSI(RAW10)를 못 읽어 '초록 화면'이 된다
     (젯슨 OpenCV엔 GStreamer가 없음). -> ai/detector/frame_hub.SharedFrameCamera
     (nvargus GStreamer 캡처, 검증됨)를 그대로 재사용해 정상 BGR 프레임을 받는다.
  2) 25200개를 파이썬 for로 디코드하면 매우 느리다 -> numpy 벡터화.

출력 텐서: (1, 25200, 40)  = [cx,cy,w,h, obj, cls0..2, mask0..31]
  -> obj * class 로 confidence, mask 32개는 detection에선 무시.

실행 (젯슨, 모니터 or ssh -X):
    cd /home/STREW-VISION/JETSON_ROBOT/models
    python3 test_engine_cam.py
"""

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import tensorrt as trt
import pycuda.driver as cuda

# frame_hub(nvargus 캡처) 재사용을 위해 JETSON_ROBOT 루트를 path에 추가
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai.detector.frame_hub import SharedFrameCamera  # noqa: E402

ENGINE_PATH = str(Path(__file__).resolve().parent / "best.engine")
INPUT_W = INPUT_H = 640
CONF_THRES = 0.25
IOU_THRES = 0.45
NUM_CLASSES = 3
CLASS_NAMES = ["healthy_leaf", "old_leaf", "powdery_mildew"]
CAM_W, CAM_H = 1280, 720

COLORS = {0: (0, 220, 0), 1: (0, 140, 255), 2: (0, 0, 255)}  # healthy=초록, old=주황, powdery=빨강

# [2026-08-04] 나노에서 X 디스플레이 + TensorRT + nvargus 동시 사용 시 dmabuf HW 버퍼 경합으로
# NvArgusCameraSrc CANCELLED(7)가 난다. --save 로 imshow 없이 프레임을 파일로 저장하면 회피된다.
_ap = argparse.ArgumentParser(description="best.engine 카메라 테스트")
_ap.add_argument("--save", default=None, help="헤드리스: 이 폴더에 검출 프레임 jpg 저장(imshow 안 씀 - X 경합 회피)")
_ap.add_argument("--frames", type=int, default=0, help="이 장수만 처리 후 종료(0=무한, --save와 함께 권장 예: 60)")
ARGS = _ap.parse_args()


def letterbox(image, new=(640, 640)):
    h, w = image.shape[:2]
    r = min(new[0] / h, new[1] / w)
    nw, nh = int(round(w * r)), int(round(h * r))
    resized = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((new[0], new[1], 3), 114, dtype=np.uint8)
    left, top = (new[1] - nw) // 2, (new[0] - nh) // 2
    canvas[top:top + nh, left:left + nw] = resized
    return canvas, r, left, top


def nms(boxes, scores, classes, iou_thr):
    if len(boxes) == 0:
        return []
    boxes = np.asarray(boxes, np.float32)
    scores = np.asarray(scores, np.float32)
    classes = np.asarray(classes, np.int32)
    keep = []
    for cls in np.unique(classes):
        inds = np.where(classes == cls)[0]
        b, s = boxes[inds], scores[inds]
        x1, y1, x2, y2 = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
        areas = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
        order = s.argsort()[::-1]
        while len(order) > 0:
            i = order[0]
            keep.append(int(inds[i]))
            if len(order) == 1:
                break
            rest = order[1:]
            xx1 = np.maximum(x1[i], x1[rest]); yy1 = np.maximum(y1[i], y1[rest])
            xx2 = np.minimum(x2[i], x2[rest]); yy2 = np.minimum(y2[i], y2[rest])
            inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
            iou = inter / (areas[i] + areas[rest] - inter + 1e-6)
            order = rest[iou <= iou_thr]
    return keep


cuda.init()
ctx = cuda.Device(0).make_context()
cam = None
try:
    logger = trt.Logger(trt.Logger.WARNING)
    with open(ENGINE_PATH, "rb") as f:
        engine = trt.Runtime(logger).deserialize_cuda_engine(f.read())
    context = engine.create_execution_context()
    stream = cuda.Stream()

    bindings, host, dev = [None] * engine.num_bindings, [None] * engine.num_bindings, [None] * engine.num_bindings
    in_i, det_i, det_w = None, None, None
    for i in range(engine.num_bindings):
        shape = engine.get_binding_shape(i)
        host[i] = cuda.pagelocked_empty(trt.volume(shape), trt.nptype(engine.get_binding_dtype(i)))
        dev[i] = cuda.mem_alloc(host[i].nbytes)
        bindings[i] = int(dev[i])
        print(f"binding {i}: {engine.get_binding_name(i)} shape={tuple(shape)} input={engine.binding_is_input(i)}")
        if engine.binding_is_input(i):
            in_i = i
        elif int(shape[-1]) in (5 + NUM_CLASSES, 5 + NUM_CLASSES + 32):  # 검출 출력(=40 또는 8)
            det_i, det_w = i, int(shape[-1])
    if det_i is None:  # 폴백: 가장 큰 출력
        det_i = max((i for i in range(engine.num_bindings) if not engine.binding_is_input(i)),
                    key=lambda i: host[i].size)
        det_w = 5 + NUM_CLASSES + 32
    print(f"검출 출력 binding={det_i}, width={det_w}")

    save_dir = None
    if ARGS.save:
        save_dir = Path(ARGS.save)
        save_dir.mkdir(parents=True, exist_ok=True)

    cam = SharedFrameCamera(cv2, 0, CAM_W, CAM_H)
    print("카메라 시작(nvargus). {}. 첫 프레임 대기...".format(
        "저장모드: " + str(save_dir) if save_dir else "q 로 종료"))

    prev = time.time()
    n = 0
    while True:
        frame = cam.get_latest_frame()
        if frame is None:
            time.sleep(0.03); continue
        oh, ow = frame.shape[:2]
        img, r, pad_x, pad_y = letterbox(frame, (INPUT_H, INPUT_W))
        blob = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB).transpose(2, 0, 1)[None].astype(np.float32) / 255.0)

        t0 = time.time()
        np.copyto(host[in_i], blob.ravel())
        cuda.memcpy_htod_async(dev[in_i], host[in_i], stream)
        context.execute_async_v2(bindings=bindings, stream_handle=stream.handle)
        cuda.memcpy_dtoh_async(host[det_i], dev[det_i], stream)
        stream.synchronize()
        inf = time.time() - t0

        # ---- 벡터 디코드 (25200 x det_w) ----
        out = np.asarray(host[det_i]).reshape(-1, det_w)
        obj = out[:, 4]
        cls = out[:, 5:5 + NUM_CLASSES]
        cid = cls.argmax(1)
        conf = obj * cls[np.arange(len(out)), cid]
        m = conf >= CONF_THRES
        boxes = []
        if m.any():
            b = out[m]; cf = conf[m]; ci = cid[m]
            cx, cy, w, h = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
            x1 = (cx - w / 2 - pad_x) / r; y1 = (cy - h / 2 - pad_y) / r
            x2 = (cx + w / 2 - pad_x) / r; y2 = (cy + h / 2 - pad_y) / r
            x1 = np.clip(x1, 0, ow - 1); y1 = np.clip(y1, 0, oh - 1)
            x2 = np.clip(x2, 0, ow - 1); y2 = np.clip(y2, 0, oh - 1)
            xyxy = np.stack([x1, y1, x2, y2], 1)
            keep = nms(xyxy, cf, ci, IOU_THRES)
            for k in keep:
                boxes.append((xyxy[k], float(cf[k]), int(ci[k])))

        for (x1, y1, x2, y2), cf, ci in boxes:
            col = COLORS.get(ci, (200, 200, 200))
            name = CLASS_NAMES[ci] if ci < len(CLASS_NAMES) else str(ci)
            cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)), col, 2)
            cv2.putText(frame, f"{name} {cf:.2f}", (int(x1), max(20, int(y1) - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)

        now = time.time()
        disp = 1.0 / max(now - prev, 1e-6); prev = now
        cv2.putText(frame, f"TensorRT FPS: {1.0/max(inf,1e-6):.1f}", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.putText(frame, f"Display FPS: {disp:.1f}", (20, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.putText(frame, f"Objects: {len(boxes)}", (20, 86), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        n += 1
        if save_dir is not None:
            cv2.imwrite(str(save_dir / "det_{:05d}.jpg".format(n)), frame)
            if n % 10 == 0:
                print("  [{}] 저장 {}장  검출 {}개  TRT {:.1f}fps".format(n, n, len(boxes), 1.0 / max(inf, 1e-6)))
        else:
            cv2.imshow("STREW_VISION engine test", frame)
            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                break
        if ARGS.frames and n >= ARGS.frames:
            print("완료: {}장 처리".format(n))
            break

except Exception as e:
    print("ERROR:", e)
    raise
finally:
    print("정리 중...")
    if cam is not None:
        try:
            cam.close()
        except Exception:
            pass
    cv2.destroyAllWindows()
    try:
        ctx.pop()
    except Exception:
        pass
    try:
        ctx.detach()
    except Exception:
        pass
    print("완료.")
