# 프로젝트 구조와 설계 의도

이 프로젝트는 네이버 블로그 음식 사진에서 음식·용기 픽셀을 보존하고, 음식이 없는 새 배경을 생성해 합성하는 전용 모듈이다.

```text
입력 → YOLO → SAM 2.1 Tiny → BiRefNet → LaMa → 원본 전경 RGBA
→ FLUX.1 Schnell 빈 배경 → 그림자·경계·밝기 조화 → 합성 → OpenCLIP 검증
```

## 폴더

`app/pipelines`는 전체 흐름, `app/services`는 모델별 기능, `configs`는 설정, `scripts`는 모델 다운로드·실행, `notebooks`는 코랩 검증을 담당한다.

## 모델

- YOLO11n: 음식·용기·제거 대상 탐지
- SAM 2.1 Tiny: 구조 마스크
- BiRefNet HR: 알파 매트
- Big-LaMa: 전경 인접 이물질 제거
- FLUX.1 Schnell: 음식 없는 광고 배경 생성
- OpenCLIP ViT-B-32: 음식·용기 보존 검증


