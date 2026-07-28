# 프로젝트 구조와 최신 실행 흐름

이 문서는 `BackgroundReplacementPipeline.run()`과 `configs/pipeline.yaml`의 현재 상태를 기준으로 한다. 파이프라인은 원본 음식과 접시를 가능한 한 보존하고, 불필요한 주변 물체를 제거한 뒤 생성한 빈 광고 배경과 합성한다.

## 전체 흐름

```text
입력 이미지·품질 검사
→ GroundingDINO 음식·접시 후보 탐지
→ 음식 전용 YOLO11n으로 비어 있는 탐지 결과만 보완
→ SAM 2.1 Small 기본 음식·접시 마스크
→ HQ-SAM patch_missing 경계 보완
→ 선택적 YOLO11-seg plate_full·food_visible 분할
→ PlateMaskService 접시 전체 마스크 완성
→ food_active_mask·plate_alpha·최종 sam_alpha 생성 및 검증
→ 수저·컵·그릇 탐지와 safe_removal_mask 생성
→ Big-LaMA 안전 영역 인페인팅
→ 분리된 외부 전경 컴포넌트 제거
→ preserve 모드의 용기 블러와 접시 림 복원
→ RGBA 전경 추출
→ EfficientNet-B0 top·45도 판별
→ 업종·분위기·각도 기반 빈 배경 프롬프트 생성
→ SANA 1.6B 또는 FLUX.1 Schnell 배경 후보 생성
→ 배경 음식·중앙 여백·기하 조건으로 후보 선택
→ 전경 배치·알파 합성·접지 그림자·색 번짐 제거·제한적 조화
→ OpenCLIP·규칙·화질 검증
→ 통과한 결과만 광고 JPG 저장
```

## 현재 기본 설정

| 항목 | 현재 값 | 의미 |
| --- | --- | --- |
| 합성 모드 | `preserve_original_plate` | 원본 음식과 접시를 함께 보존한다. |
| GroundingDINO | `enabled: true` | 개방형 텍스트 프롬프트로 음식·접시 후보를 먼저 찾는다. |
| 음식 전용 YOLO11n | `food_specialized` | GroundingDINO가 놓친 음식 또는 용기 쪽만 보완한다. |
| SAM2 | `enabled: true` | 기본 구조 마스크를 만든다. |
| HQ-SAM | `enabled: true`, `patch_missing` | SAM2를 교체하지 않고 작은 경계 결손만 추가한다. |
| YOLO11-seg 접시 모델 | `enabled: false` | 코드 어댑터는 있지만 기본 실행에는 참여하지 않는다. |
| BiRefNet | `enabled: false` | 현재 알파 생성에는 사용하지 않는다. CLI의 `--enable-matting`도 강제로 켜지 않는다. |
| Big-LaMA | `enabled: true` | 보호 마스크 밖의 탐지된 물체를 제거한다. |
| 용기 블러 | `enabled: true` | `preserve_original_plate`에서만 접시·용기의 보이는 부분에 적용한다. |
| 접시 림 복원 | `enabled: true` | `preserve_original_plate`에서만 원본 RGB와 림 색을 사용해 결손을 보완한다. |
| 배경 생성 | `sana-1.6b` | 기본 배경 생성기다. FLUX는 선택 대안이다. |
| OpenCLIP | `enabled: true`, 최소 `0.8` | 최종 전경 의미 보존 여부를 검사한다. |

## 모드별 알파 정책

### `preserve_original_plate`

`PlateMaskService`가 완성한 `plate_mask`에서 `plate_alpha`를 만들고, 음식 SAM 알파와 `maximum` 연산으로 합친다. 안전 제거와 분리 컴포넌트 제거 후에도 `plate_alpha`를 마지막에 다시 합쳐 접시 내부가 배경처럼 뚫리지 않게 한다.

### `generated_plate`

최종 알파는 `food_active_mask`와 강제로 교집합을 취한다. 기본 설정의 `require_food_visible_mask: true`에서는 활성화된 YOLO11-seg가 유효한 `food_visible` 마스크를 만들지 못하면 안전하게 중단한다. CLI의 `--allow-sam-food-mask-for-generated-plate` 또는 동일한 메타데이터 설정은 실험 목적으로만 이 제한을 완화한다.

## 안전 경계

- 중앙 사각형 대체는 `--diagnostic-center-fallback` 연결 진단에서만 허용한다.
- 제거 마스크는 음식 또는 접시 보호 영역을 뺀 `safe_removal_mask`로 제한한다.
- Big-LaMA로 제거한 영역은 알파에서도 제거한다. preserve 모드는 그 뒤 접시 알파를 다시 보존한다.
- 생성 배경에서 음식·식기 후보가 검출되거나 전경 배치가 각도별 기하 조건을 벗어나면 결과를 저장하지 않는다.
- OpenCLIP 유사도가 기준보다 낮으면 현재 코드는 재합성하지 않고 `semantic_validation_failed`로 거부한다.
- 실패해도 보고서와 디버그 산출물은 남긴다. 네이버 API 연결에서는 파이프라인 실패를 원본 이미지 fallback으로 변환한다.

## 폴더

- `app/pipelines`: 전체 실행 순서와 실패 보고서
- `app/services`: 탐지·분할·마스크·인페인팅·배경 생성·합성·검증
- `configs`: 모델과 처리 정책
- `scripts`: CLI 실행, 모델 다운로드, 학습·평가 도구
- `notebooks`: Colab·로컬 실행 및 모델 학습
- `docs`: 운영, 설치, 학습, 개발 이력 문서

## 주요 산출물

- 최종 결과: `data/output/<입력명>_background_replaced.jpg`
- RGBA 전경: `data/intermediate/<입력명>_foreground_rgba.png`
- 실행 보고서: `data/reports/<입력명>_background_replacement_report.json`
- 마스크: `data/masks/`
- Colab 실험 묶음: `data/experiments/background_replacement/<실행시각>/`

보고서의 `debug_artifacts`에는 SAM/HQ-SAM 마스크, `plate_mask`, `plate_alpha`, `food_active_mask`, `safe_removal_mask`, 분리 전경 제거 마스크, 컨테이너 블러 마스크, 접시 림 복원 마스크, 의미 비교 이미지와 최종 또는 거부 합성 이미지 경로가 기록된다.
