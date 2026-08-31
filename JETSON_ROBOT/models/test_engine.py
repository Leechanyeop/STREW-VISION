import cv2
import time
import numpy as np
import tensorrt as trt
import pycuda.driver as cuda


# ============================================================
# 설정
# ============================================================

ENGINE_PATH = "best.engine"

INPUT_W = 640
INPUT_H = 640

CONF_THRES = 0.25
IOU_THRES = 0.45

NUM_CLASSES = 3
NUM_MASK = 32

CLASS_NAMES = [
    "healthy_leaf",
    "old_leaf",
    "powdery_mildew",
]


# ============================================================
# CUDA / TensorRT 초기화
# ============================================================

cuda.init()

device = cuda.Device(0)
ctx = device.make_context()

TRT_LOGGER = trt.Logger(trt.Logger.WARNING)

runtime = None
engine = None
context = None
stream = None
cap = None


# ============================================================
# Letterbox
# ============================================================

def letterbox(image, new_shape=(640, 640)):

    h, w = image.shape[:2]

    r = min(
        new_shape[0] / h,
        new_shape[1] / w
    )

    new_w = int(round(w * r))
    new_h = int(round(h * r))

    resized = cv2.resize(
        image,
        (new_w, new_h),
        interpolation=cv2.INTER_LINEAR
    )

    canvas = np.full(
        (new_shape[0], new_shape[1], 3),
        114,
        dtype=np.uint8
    )

    dw = (new_shape[1] - new_w) / 2
    dh = (new_shape[0] - new_h) / 2

    left = int(round(dw - 0.1))
    top = int(round(dh - 0.1))

    canvas[
        top:top + new_h,
        left:left + new_w
    ] = resized

    return canvas, r, left, top


# ============================================================
# Class-aware NMS
# ============================================================

def nms(boxes, scores, classes, iou_threshold):

    if len(boxes) == 0:
        return []

    boxes = np.asarray(boxes, dtype=np.float32)
    scores = np.asarray(scores, dtype=np.float32)
    classes = np.asarray(classes, dtype=np.int32)

    keep = []

    # 클래스별로 NMS
    for cls in np.unique(classes):

        inds = np.where(classes == cls)[0]

        cls_boxes = boxes[inds]
        cls_scores = scores[inds]

        x1 = cls_boxes[:, 0]
        y1 = cls_boxes[:, 1]
        x2 = cls_boxes[:, 2]
        y2 = cls_boxes[:, 3]

        areas = np.maximum(
            0,
            x2 - x1
        ) * np.maximum(
            0,
            y2 - y1
        )

        order = cls_scores.argsort()[::-1]

        while len(order) > 0:

            current = order[0]

            keep.append(
                int(inds[current])
            )

            if len(order) == 1:
                break

            rest = order[1:]

            xx1 = np.maximum(
                x1[current],
                x1[rest]
            )

            yy1 = np.maximum(
                y1[current],
                y1[rest]
            )

            xx2 = np.minimum(
                x2[current],
                x2[rest]
            )

            yy2 = np.minimum(
                y2[current],
                y2[rest]
            )

            w = np.maximum(
                0,
                xx2 - xx1
            )

            h = np.maximum(
                0,
                yy2 - yy1
            )

            inter = w * h

            union = (
                areas[current]
                + areas[rest]
                - inter
                + 1e-6
            )

            iou = inter / union

            order = rest[
                iou <= iou_threshold
            ]

    return keep


# ============================================================
# TensorRT 실행
# ============================================================

try:

    # --------------------------------------------------------
    # Engine 로드
    # --------------------------------------------------------

    print("Loading TensorRT engine...")

    with open(ENGINE_PATH, "rb") as f:

        runtime = trt.Runtime(TRT_LOGGER)

        engine = runtime.deserialize_cuda_engine(
            f.read()
        )

    if engine is None:
        raise RuntimeError(
            "TensorRT engine load failed"
        )

    print("TensorRT engine loaded.")

    # --------------------------------------------------------
    # Execution Context
    # 중요: 여기서 딱 한 번만 생성
    # --------------------------------------------------------

    context = engine.create_execution_context()

    if context is None:
        raise RuntimeError(
            "TensorRT execution context creation failed"
        )

    print("TensorRT execution context created.")

    # --------------------------------------------------------
    # Binding
    # --------------------------------------------------------

    print(
        f"Bindings: {engine.num_bindings}"
    )

    bindings = [
        None
    ] * engine.num_bindings

    host_buffers = [
        None
    ] * engine.num_bindings

    device_buffers = [
        None
    ] * engine.num_bindings

    input_index = None
    output0_index = None
    output1_index = None

    for i in range(engine.num_bindings):

        name = engine.get_binding_name(i)
        shape = engine.get_binding_shape(i)
        dtype = engine.get_binding_dtype(i)
        is_input = engine.binding_is_input(i)

        print(
            f"Binding: {i} "
            f"name: {name} "
            f"shape: {shape} "
            f"dtype: {dtype} "
            f"input: {is_input}"
        )

        size = trt.volume(shape)

        np_dtype = trt.nptype(dtype)

        host_mem = cuda.pagelocked_empty(
            size,
            np_dtype
        )

        device_mem = cuda.mem_alloc(
            host_mem.nbytes
        )

        bindings[i] = int(device_mem)

        host_buffers[i] = host_mem
        device_buffers[i] = device_mem

        if is_input:

            input_index = i

        else:

            if name == "output0":
                output0_index = i

            elif name == "output1":
                output1_index = i

    if input_index is None:
        raise RuntimeError(
            "Input binding not found"
        )

    if output0_index is None:
        raise RuntimeError(
            "output0 binding not found"
        )

    print(
        f"Input binding  : {input_index}"
    )

    print(
        f"output0 binding: {output0_index}"
    )

    print(
        f"output1 binding: {output1_index}"
    )

    # --------------------------------------------------------
    # CUDA Stream
    # --------------------------------------------------------

    stream = cuda.Stream()

    # ========================================================
    # Camera
    # ========================================================

    cap = cv2.VideoCapture(0)

    if not cap.isOpened():

        raise RuntimeError(
            "Camera cannot be opened"
        )

    print("Camera started.")
    print("Press Q to quit.")

    # ========================================================
    # Warm-up
    # ========================================================

    dummy = np.zeros(
        (1, 3, INPUT_H, INPUT_W),
        dtype=np.float32
    )

    np.copyto(
        host_buffers[input_index],
        dummy.ravel()
    )

    cuda.memcpy_htod_async(
        device_buffers[input_index],
        host_buffers[input_index],
        stream
    )

    context.execute_async_v2(
        bindings=bindings,
        stream_handle=stream.handle
    )

    stream.synchronize()

    print("TensorRT warm-up complete.")

    # ========================================================
    # Main Loop
    # ========================================================

    prev_time = time.time()

    while True:

        ret, frame = cap.read()

        if not ret:

            print(
                "Camera frame read failed"
            )

            break

        original_h, original_w = frame.shape[:2]

        # ----------------------------------------------------
        # Preprocess
        # ----------------------------------------------------

        img, ratio, pad_x, pad_y = letterbox(
            frame,
            (INPUT_H, INPUT_W)
        )

        img = cv2.cvtColor(
            img,
            cv2.COLOR_BGR2RGB
        )

        img = img.astype(
            np.float32
        ) / 255.0

        img = np.transpose(
            img,
            (2, 0, 1)
        )

        img = np.expand_dims(
            img,
            axis=0
        )

        img = np.ascontiguousarray(
            img
        )

        # ----------------------------------------------------
        # Copy input
        # ----------------------------------------------------

        np.copyto(
            host_buffers[input_index],
            img.ravel()
        )

        # ----------------------------------------------------
        # TensorRT inference
        # ----------------------------------------------------

        inference_start = time.time()

        cuda.memcpy_htod_async(
            device_buffers[input_index],
            host_buffers[input_index],
            stream
        )

        context.execute_async_v2(
            bindings=bindings,
            stream_handle=stream.handle
        )

        # output0 / output1 복사

        for i in range(
            engine.num_bindings
        ):

            if engine.binding_is_input(i):
                continue

            cuda.memcpy_dtoh_async(
                host_buffers[i],
                device_buffers[i],
                stream
            )

        stream.synchronize()

        inference_time = (
            time.time()
            - inference_start
        )

        # ----------------------------------------------------
        # output0
        #
        # 현재 엔진:
        #
        # (1, 25200, 40)
        #
        # 0~3   : x y w h
        # 4     : objectness
        # 5~7   : 3 class
        # 8~39  : 32 mask coefficient
        # ----------------------------------------------------

        output = host_buffers[
            output0_index
        ]

        output = output.reshape(
            25200,
            40
        )

        predictions = output

        boxes = []
        scores = []
        classes = []

        # ----------------------------------------------------
        # Detection decode
        # ----------------------------------------------------

        for detection in predictions:

            cx = float(
                detection[0]
            )

            cy = float(
                detection[1]
            )

            w = float(
                detection[2]
            )

            h = float(
                detection[3]
            )

            objectness = float(
                detection[4]
            )

            class_scores = detection[
                5:5 + NUM_CLASSES
            ]

            class_id = int(
                np.argmax(
                    class_scores
                )
            )

            class_conf = float(
                class_scores[class_id]
            )

            confidence = (
                objectness
                * class_conf
            )

            if confidence < CONF_THRES:
                continue

            # ------------------------------------------------
            # xywh -> xyxy
            # ------------------------------------------------

            x1 = cx - w / 2
            y1 = cy - h / 2
            x2 = cx + w / 2
            y2 = cy + h / 2

            # ------------------------------------------------
            # Remove letterbox
            # ------------------------------------------------

            x1 = (
                x1 - pad_x
            ) / ratio

            y1 = (
                y1 - pad_y
            ) / ratio

            x2 = (
                x2 - pad_x
            ) / ratio

            y2 = (
                y2 - pad_y
            ) / ratio

            # ------------------------------------------------
            # Clamp
            # ------------------------------------------------

            x1 = max(
                0,
                min(
                    original_w - 1,
                    x1
                )
            )

            y1 = max(
                0,
                min(
                    original_h - 1,
                    y1
                )
            )

            x2 = max(
                0,
                min(
                    original_w - 1,
                    x2
                )
            )

            y2 = max(
                0,
                min(
                    original_h - 1,
                    y2
                )
            )

            boxes.append(
                [
                    x1,
                    y1,
                    x2,
                    y2
                ]
            )

            scores.append(
                confidence
            )

            classes.append(
                class_id
            )

        # ----------------------------------------------------
        # NMS
        # ----------------------------------------------------

        keep = nms(
            boxes,
            scores,
            classes,
            IOU_THRES
        )

        # ----------------------------------------------------
        # Draw detections
        # ----------------------------------------------------

        for idx in keep:

            x1, y1, x2, y2 = map(
                int,
                boxes[idx]
            )

            cls = classes[idx]

            conf = scores[idx]

            if cls < len(CLASS_NAMES):

                name = CLASS_NAMES[cls]

            else:

                name = str(cls)

            # Box

            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                (0, 255, 0),
                2
            )

            # Label

            label = (
                f"{name} {conf:.2f}"
            )

            cv2.putText(
                frame,
                label,
                (
                    x1,
                    max(
                        20,
                        y1 - 5
                    )
                ),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2
            )

        # ----------------------------------------------------
        # FPS
        # ----------------------------------------------------

        current_time = time.time()

        total_fps = 1.0 / max(
            current_time - prev_time,
            1e-6
        )

        prev_time = current_time

        inference_fps = 1.0 / max(
            inference_time,
            1e-6
        )

        # ----------------------------------------------------
        # Information
        # ----------------------------------------------------

        cv2.putText(
            frame,
            f"TensorRT FPS: {inference_fps:.2f}",
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.75,
            (0, 255, 255),
            2
        )

        cv2.putText(
            frame,
            f"Display FPS: {total_fps:.2f}",
            (20, 65),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 255),
            2
        )

        cv2.putText(
            frame,
            f"Objects: {len(keep)}",
            (20, 95),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 255),
            2
        )

        # ----------------------------------------------------
        # Display
        # ----------------------------------------------------

        cv2.imshow(
            "STREW_VISION YOLOv5n TensorRT",
            frame
        )

        key = cv2.waitKey(1) & 0xFF

        if key == ord("q"):

            break


# ============================================================
# Cleanup
# ============================================================

except KeyboardInterrupt:

    print("\nInterrupted.")


except Exception as e:

    print(
        f"\nERROR: {e}"
    )

    raise


finally:

    print(
        "Cleaning up..."
    )

    if cap is not None:

        cap.release()

    cv2.destroyAllWindows()

    if stream is not None:

        stream.synchronize()

    # CUDA context 종료

    try:

        ctx.pop()

    except Exception:

        pass

    try:

        ctx.detach()

    except Exception:

        pass

    print(
        "Cleanup complete."
    )