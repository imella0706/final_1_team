# 코랩 실행 안내

`notebooks/01_colab_background_replacement.ipynb`를 GPU 런타임에서 위에서 아래 순서로 실행한다. 이 노트북은 `venv`를 만들지 않고 `/content/food-image-cleanup-packages` 전용 폴더에만 파이프라인 의존성을 설치한다. 이후 모델 다운로드와 추론 subprocess에만 이 폴더를 `PYTHONPATH`로 우선 적용하므로, `huggingface_hub` 버전이 다른 Gradio 등의 전역 패키지를 변경하지 않는다.

처음 실행할 때는 다음 작업이 수행된다.

- Google Drive의 프로젝트 폴더를 연결한다.
- 가상환경에 YOLO, SAM 실행용 라이브러리, BiRefNet, FLUX, OpenCLIP 의존성을 설치한다.
- YOLO11n, SAM 2.1 Tiny, Big-LaMa, BiRefNet HR, FLUX.1 Schnell, OpenCLIP 모델을 내려받는다.
- 음식 사진 한 장을 업로드하고 카페·음식점·주점 등의 메타데이터를 작성한다.
- 전경 분리, 빈 배경 생성, 합성, 보고서 확인을 실행한다.

FLUX와 BiRefNet은 용량이 크므로 GPU 런타임과 넉넉한 Drive 저장 공간이 필요하다. 모델은 `models/`에 보존되므로 다음 실행부터는 이미 받은 모델을 건너뛴다.

FLUX.1 Schnell은 Hugging Face의 gated 모델이다. [FLUX.1 Schnell 모델 페이지](https://huggingface.co/black-forest-labs/FLUX.1-schnell)에서 접근 조건에 동의하고 읽기 권한 토큰을 만든 뒤, 노트북의 FLUX 토큰 입력 셀에 입력해야 한다. 전체 체크포인트에는 약 23.8GB의 변환기 파일이 포함되므로 Drive의 여유 공간도 확인한다.

기본 배경 생성기는 `sana-1.6b`이다. `Efficient-Large-Model/Sana_1600M_1024px_BF16_diffusers`를 사용하며 FLUX 인증 토큰 없이 실행할 수 있다. 노트북의 `BACKGROUND_PROVIDER`를 `flux-schnell`로 바꾸면 FLUX를, `sana-1.6b`로 두면 Sana를 사용한다. Sana 1.6B는 20단계·guidance 5.0, FLUX는 4단계·guidance 0.0으로 각각 모델 특성에 맞는 기본값을 사용한다.

YOLO11n은 기본 COCO 클래스만 가지므로 일부 한식·디저트·접시 조합을 음식으로 탐지하지 못할 수 있다. 노트북은 전체 단계 검증이 중단되지 않도록 이 경우 중앙 전경 상자로 대체 실행하고, 보고서에 `step_2_detection_fallback`을 남긴다. 이는 연결·실행 검증용 대책이며 실제 서비스 결과에서는 이 표시가 없는 입력을 우선 사용하거나 음식·용기 특화 탐지 모델을 추가해야 한다.
