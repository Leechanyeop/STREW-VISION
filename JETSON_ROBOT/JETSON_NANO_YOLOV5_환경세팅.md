# Jetson Nano 4GB — YOLOv5n 환경 세팅 가이드

## 확인된 하드웨어/OS 정보

| 항목 | 값 |
|---|---|
| 보드 | Jetson Nano 4GB Developer Kit (Maxwell GPU) |
| L4T | R32.7.6 |
| JetPack | 4.6.6 |
| OS | Ubuntu 18.04.6 LTS (bionic) |
| CUDA | 10.2 |
| TensorRT | 8.2.1.8 (이미 설치됨) |
| Python | 3.6.9 (시스템 기본, 절대 3.8로 올리지 않는다 — 이유는 아래 참고) |

**왜 Python 3.6 + torch 1.10 + YOLOv5n인가**: NVIDIA는 Jetson Nano(L4T R32.x/JetPack 4.x) 계열용 CUDA 가속 PyTorch wheel을 Python 3.6까지만 배포한다(1.10.0이 마지막 3.6 지원 버전). Python 3.8용 wheel은 JetPack 5 이상(다른 세대 보드)부터 나온다. 3.8을 쓰려면 PyTorch를 CUDA 10.2에 맞춰 직접 소스빌드해야 하는데, NVIDIA 포럼에도 관련 미해결 질문이 여러 건 있을 만큼 검증된 경로가 아니다. `ultralytics`(YOLOv8+) 패키지는 Python 3.8+를 요구해서 이 보드에서 정식 경로로 못 쓴다 — 그래서 YOLOv5(구 `ultralytics/yolov5` 레포, pip 패키지 아님) + Python 3.6 조합으로 간다.

## 0. 사전 준비 — Swap + 성능 모드

빌드 중간에 메모리 부족으로 죽는 걸 막기 위해 먼저 처리한다.

```bash
# 4GB RAM으로는 torchvision 소스빌드 시 부족할 수 있음 — swap 추가
sudo systemctl disable nvzramconfig
sudo fallocate -l 8G /mnt/8GB.swap
sudo chmod 600 /mnt/8GB.swap
sudo mkswap /mnt/8GB.swap
sudo swapon /mnt/8GB.swap
# 재부팅 후에도 유지하려면 /etc/fstab 에 추가:
# /mnt/8GB.swap none swap sw 0 0

# 최대 성능 모드 (빌드/학습/추론 전부 이걸로)
sudo nvpmodel -m 0
sudo jetson_clocks
```

## 1. 시스템 라이브러리

```bash
sudo apt-get update
sudo apt-get install -y liblapack-dev libblas-dev gfortran libfreetype6-dev \
    libopenblas-base libopenmpi-dev libjpeg-dev zlib1g-dev python3-pip \
    libopenblas-dev libavcodec-dev libavformat-dev libswscale-dev libpython3-dev
```

## 2. Python 패키지 (버전 고정 — Python 3.6 호환 한계선)

```bash
# JetPack 기본 numpy 제거 후 재설치
pip3 uninstall -y numpy
pip3 install numpy==1.19.5     # Python 3.6을 지원하는 마지막 numpy 계열
pip3 install pandas==0.22.0 Pillow==8.4.0 PyYAML==3.12 scipy==1.5.4 \
    psutil tqdm==4.64.1 imutils
sudo apt install -y python3-seaborn
```

## 3. PyTorch 1.10.0 + torchvision 0.11.1

```bash
wget https://nvidia.box.com/shared/static/fjtbno0vpo676a25cgvuqc1wty0fkkg6.whl \
    -O torch-1.10.0-cp36-cp36m-linux_aarch64.whl
pip3 install 'Cython<3'
pip3 install torch-1.10.0-cp36-cp36m-linux_aarch64.whl

git clone --branch v0.11.1 https://github.com/pytorch/vision torchvision
cd torchvision
sudo python3 setup.py install
cd ..

# 확인
python3 -c "import torch, torchvision; print(torch.__version__, torch.cuda.is_available(), torchvision.__version__)"
```

## 4. PyCUDA (TensorRT 엔진을 파이썬에서 실행하려면 필요)

```bash
export PATH=/usr/local/cuda-10.2/bin${PATH:+:${PATH}}
export LD_LIBRARY_PATH=/usr/local/cuda-10.2/lib64:$LD_LIBRARY_PATH
python3 -m pip install pycuda --user
```

## 5. YOLOv5 레포 (pip install ultralytics 아님!)

```bash
git clone --branch v6.2 https://github.com/ultralytics/yolov5
cd yolov5
# requirements.txt에서 torch/torchvision 줄은 지운다 (이미 위에서 설치했으므로 pip이 덮어쓰지 않게)
pip3 install -r requirements.txt
```

## 6. 학습 → TensorRT 엔진 변환 (참고 레포: mailrocketsystems/JetsonYolov5)

중요: 이 참고 레포의 `yolov5n.pt`/`yolov5s.pt`는 COCO 예시 가중치일 뿐이다. 우리 프로젝트는 식물 상태(healthy/powdery_mildew/missing_plant/nutrition_needed/empty_cell) 클래스로 **직접 학습한 커스텀 YOLOv5n 가중치**가 필요하다. 아래는 학습이 끝난 `.pt` 파일을 TensorRT 엔진으로 바꾸는 절차.

```bash
# .pt -> .wts 변환
python3 gen_wts.py -w best.pt -o best.wts

# TensorRT 엔진 빌드 (yolov5 C++ 추론 레포 기준)
mkdir build && cd build
cp ../../best.wts .
cmake ..
make
./yolov5_det -s best.wts best.engine n   # n = nano 모델 타입

# 테스트
./yolov5_det -d best.engine ../images
```

## 참고 자료

- [PyTorch for Jetson - NVIDIA Developer Forums](https://forums.developer.nvidia.com/t/pytorch-for-jetson/72048)
- [mailrocketsystems/JetsonYolov5 (Jetson Nano + JetPack 4.6 실제 검증됨)](https://github.com/mailrocketsystems/JetsonYolov5)
- [Faster YOLOv5 inference with TensorRT — Run YOLOv5 at 27 FPS on Jetson Nano (Seeed Studio)](https://www.seeedstudio.com/blog/2022/08/23/faster-inference-with-tensorrt-on-nvidia-jetson-run-yolov5-at-27-fps-on-jetson-nano/)
- [Install PyTorch on Jetson Nano — Q-engineering (swap 관련)](https://qengineering.eu/install-pytorch-on-jetson-nano.html)
