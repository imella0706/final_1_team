# 이미지 보정 문제와 해결 과정 기록

## 1. 문서의 범위

이 문서는 `food-image-cleanup-pipeline`을 작업하면서 **실제로 발견하고 다루었던 문제와 그 해결 과정만** 기록한다.

기준 시점은 **2026년 7월 27일 오전 9시 35분까지**다.

이 문서에는 다음 내용을 넣지 않는다.

- 오전 9시 35분 이후에 진행한 데이터셋 준비와 모델 학습
- 오전 9시 35분 이후에 연결한 접시 전용 `YOLO11-seg`
- 실제로 시도하지 않은 일반적인 개선 아이디어
- 결과 파일로 확인하지 않은 내용을 완료된 결과처럼 표현하는 설명

이 문서에서 사용하는 상태 표현은 다음과 같다.

| 상태 | 뜻 |
| --- | --- |
| 적용 완료 | 코드 또는 설정에 기능이 반영되었다. |
| 구조 검증 완료 | 문법 검사, 설정 확인 또는 파이프라인 연결 확인을 통과했다. |
| 출력 검증 완료 | 실제 출력 이미지나 마스크로 동작을 확인했다. |
| 다음 실행 확인 필요 | 코드는 반영됐지만 변경 후 새 출력 이미지로 최종 효과를 확인해야 한다. |

### 먼저 확인할 현재 상태

문서 전체를 읽기 전에 결론만 확인하려면 아래 표를 보면 된다.

| 확인 질문 | 오전 9시 35분 기준 답 |
| --- | --- |
| 기본 합성 모드는 무엇인가 | `preserve_original_plate` |
| 기본 마스크 모델은 무엇인가 | SAM2 |
| 경계 보완 모델은 무엇인가 | HQ-SAM, `patch_missing` 방식 |
| HQ-SAM은 켜져 있는가 | 켜져 있다. `models/hq-sam` 로컬 경로를 사용한다. |
| BiRefNet은 사용하는가 | 사용하지 않는다. `matting.enabled: false`다. |
| 접시 전용 학습 segmentation 모델을 사용하는가 | 이 시점에는 사용하지 않는다. 관련 작업은 오전 9시 35분 이후다. |
| 원본 접시는 어떻게 보존하는가 | `plate_mask`에서 `plate_alpha`를 만들고 preserve 모드 마지막에 다시 합친다. |
| 수저는 어떻게 지우는가 | 일반 YOLO 제거 탐지, `safe_removal_mask`, Big-LaMA, alpha 동시 삭제 순서로 처리한다. |
| 탐지가 수저를 놓치면 어떻게 하는가 | 접시·음식과 연결되지 않은 외부 foreground 컴포넌트를 후처리로 제거한다. |
| 블러 마스크가 비었던 원인은 무엇인가 | 음식 보호 입력이 접시까지 포함해 블러할 영역을 모두 지웠기 때문이다. |
| 접시 끝이 끊긴 최종 원인은 무엇인가 | 마지막 단계에서는 마스크 부족보다 최종 RGB에 초록 림 색이 충분히 적용되지 않은 것이 핵심이었다. |
| 오전 9시 35분의 마지막 수정은 무엇인가 | 원본 고채도 림 색을 샘플링해 상단 결손부에 강한 `synthetic_rim_bridge`를 적용했다. |
| 마지막 수정은 완전히 검증됐는가 | 코드·설정·문법 검증은 끝났고, 변경 후 새 결과의 최종 시각 검증은 필요하다. |

### 현재 코드와 비교할 때 헷갈리기 쉬운 부분

이 문서는 오전 9시 35분까지 실제로 겪은 문제와 해결 과정을 기록한다. 이후 코드에는 실험용 스위치와 후속 기능이 더 들어가 있지만, 그것이 이 시점의 해결 과정에 포함됐다는 뜻은 아니다.

| 현재 코드에 보이는 항목 | 이 문서에서 다루는 방식 |
| --- | --- |
| `models.plate_segmenter` | 오전 9시 35분 이후에 연결된 접시 전용 `YOLO11-seg` 어댑터다. 현재 기본 설정은 `enabled: false`라서 이 문서의 문제 해결 흐름에는 넣지 않는다. |
| `synthetic_rim_bridge_top_ratio`, `synthetic_rim_bridge_dilation`, `synthetic_rim_bridge_horizontal_margin` | 오전 9시 35분의 핵심 해결책인 synthetic rim bridge를 더 강하고 좁게 제어하기 위한 보조 설정이다. 이 문서에서는 “상단 림 결손부에 강제 브리지를 얹었다”는 문제 해결 과정 안에 포함해서 이해하면 된다. |
| `synthetic_rim_bridge_connect_full_top`, `synthetic_rim_bridge_dilate` | 끊긴 상단 림이 여러 조각일 때 더 확실히 이어 보이도록 만든 보조 옵션이다. 핵심 아이디어는 새 모델이 아니라 원본 림 색 기반의 직접 보정이다. |
| `synthetic_rim_band_enabled` | 별도 림 밴드 실험용 옵션이다. 기본값이 `false`라서 이 문서의 최종 해결 상태에는 포함하지 않는다. |
| `plate_mask_rim_completion_enabled` | `plate_mask` 기준으로 림을 더 완성하는 실험용 옵션이다. 기본값이 `false`라서 이 문서의 최종 해결 상태에는 포함하지 않는다. |
| `models.plate_mask.minimum_shape_confidence`, `contour_completion_enabled` | 오전 9시 35분 이후 추가된 타원·사각형 계열·비정형 용기 일반화다. 당시 문제 해결 과정에는 포함하지 않는다. |
| `models.mask_quality`와 `step_2c_mask_quality` | 오전 9시 35분 이후 추가된 음식·접시 독립 품질 검사다. 현재 코드의 안전 게이트지만 당시 결론은 아니다. |
| `models.food_support_recovery`와 `step_2d_food_support_recovery` | 오전 9시 35분 이후 추가된 꼬치형 음식 지지 구조 보호 단계다. 기하학만으로는 복구하지 않는다. |
| `plate_edge_repair.adaptive_rim_observation` | 오전 9시 35분 이후에는 고정 초록색 규칙을 일반화해 원본 RGB 림 관찰 신뢰도를 사용한다. 현재 최소 기준은 `0.53`이다. |

---

현재 운영 상태는 `README.md`, `docs/ARCHITECTURE.md`, `configs/pipeline.yaml`을 우선한다. 후속으로 시도한 음식 지지 구조 최상단 RGB 재합성은 사용자 요청으로 취소됐으며 현재 코드에는 `step_5e_food_support_layer`가 남아 있지 않다.

## 2. 전체 문제 해결 순서

실제 작업은 다음 순서로 진행되었다.

```text
Colab 입력 범위 확장
-> 접시 보존 모드와 음식 전용 모드 구분
-> 컨테이너 블러를 설정으로 켜고 끄는 구조 추가
-> 짧은 배경 프롬프트 실험 후 원상 복구
-> 접시 알파 내부 구멍 문제 수정
-> 수저와 주변 물체 제거 처리 추가
-> generated_plate에서 원본 접시와 외부 물체 제거 강화
-> 빈 컨테이너 블러 마스크 원인 수정
-> 분리된 외부 전경 조각 제거 추가
-> 접시 끝부분 절단 원인 분석
-> HQ-SAM을 선택형 경계 보완 모델로 추가
-> 마스크 보완과 RGB 림 복원을 분리
-> 오전 9시 35분 기준 synthetic rim bridge 강화
```

---

## 3. Colab에서 사진 한 장과 업종·분위기를 직접 선택할 수 없었던 문제

### 3.1 실제 증상

Colab 테스트가 특정 카페 사진과 고정된 설정을 중심으로 실행되고 있었다.

이 구조에서는 다음 테스트가 불편했다.

- 카페가 아닌 식당 사진
- 베이커리나 주점 사진
- 같은 사진에 서로 다른 분위기를 적용하는 비교
- 접시 보존과 음식 전용 합성 방식 비교

### 3.2 원인

테스트 노트북에서 파이프라인 메타데이터를 사용자가 직접 선택할 수 있는 입력 UI가 충분히 노출되지 않았다.

파이프라인은 원래 다음 정보를 사용할 수 있었지만, Colab 실행 단계에서 쉽게 바꾸기 어려웠다.

```text
business_type
desired_mood
composition_mode
```

### 3.3 적용한 해결

CLI와 Colab 실행 흐름에서 다음 값을 받을 수 있게 했다.

```text
--business-type
--desired-mood
--composition-mode
--allow-sam-food-mask-for-generated-plate
```

CLI 값이 들어오면 메타데이터 JSON의 같은 항목을 덮어쓰게 했다.

예:

```bash
python scripts/run_background_replacement.py \
  --input data/input/example.jpg \
  --business-type restaurant \
  --desired-mood "warm and casual" \
  --composition-mode preserve_original_plate
```

Colab에서는 사용자가 다음 순서로 테스트할 수 있게 구성했다.

1. 사진 한 장을 업로드한다.
2. `business_type`을 선택한다.
3. `desired_mood`를 선택한다.
4. `composition_mode`를 선택한다.
5. 선택한 값을 CLI 인수 또는 메타데이터로 전달한다.

### 3.4 기존 파이프라인에 미치는 영향

새 CLI 옵션을 주지 않으면 기존 메타데이터와 config 값이 그대로 사용된다.

따라서 이 변경은 기존 실행 경로를 교체한 것이 아니라 **테스트할 때 값을 선택적으로 덮어쓸 수 있는 입력 통로를 추가한 것**이다.

### 3.5 검증 상태

- CLI 옵션 추가: 적용 완료
- 기존 메타데이터 fallback 유지: 구조 검증 완료
- 카페 외 업종 선택 가능: 적용 완료

---

## 4. 원본 접시를 보존할지 음식만 사용할지 구분되지 않았던 문제

### 4.1 실제 증상

초기 처리에서는 음식과 접시가 하나의 전경처럼 함께 가져와졌다.

하지만 필요한 결과는 두 종류였다.

```text
원본 음식 + 원본 접시를 함께 보존
원본 음식만 가져와 새 접시 또는 새 배경에 배치
```

### 4.2 원인

하나의 마스크와 하나의 알파만으로 두 목적을 처리하려 했다.

접시를 보존할 때 필요한 마스크와 음식만 분리할 때 필요한 마스크는 역할이 다르다.

### 4.3 적용한 해결

`composition_mode`를 두 종류로 분리했다.

#### `preserve_original_plate`

```text
원본 음식 보존
+ 원본 접시/용기 보존
+ 주변 배경 교체
```

#### `generated_plate`

```text
원본 음식만 보존
+ 원본 접시/용기 제거
+ 새로 생성된 접시 또는 배경에 음식 배치
```

### 4.4 왜 모드별로 최종 알파를 다르게 처리했는가

`preserve_original_plate`에서는 접시 알파가 마지막까지 살아 있어야 한다.

```text
final_alpha = max(food_or_structural_alpha, plate_alpha)
```

`generated_plate`에서는 접시가 최종 알파에 남으면 안 된다.

```text
final_alpha = current_alpha AND food_active_mask
```

즉 generated 모드에서는 마지막에 음식 마스크와 강제로 교집합을 만들어 접시와 외부 물체가 다시 살아나는 것을 막는 방향으로 처리했다.

### 4.5 검증 상태

- 모드 구분: 적용 완료
- preserve 모드 접시 재보존: 적용 완료
- generated 모드 음식 마스크 교집합: 적용 완료
- 오전 9시 35분 기준 주 운영 모드: `preserve_original_plate`

---

## 5. 접시·용기 블러를 설정으로 끌 수 없었던 문제

### 5.1 실제 요구

`preserve_original_plate` 모드에서 음식이 아닌 접시나 음식을 담는 용기 부분만 블러하고 있었다.

이 기능을 사진에 따라 켜거나 끌 수 있어야 했다.

### 5.2 기존 처리 구조

블러의 기본 흐름은 다음과 같았다.

```text
탐지 박스
-> SAM2 마스크
-> 접시/용기 마스크 정리
-> OpenCV 블러
```

사용자 클릭으로 SAM2를 실행하는 대화형 편집기가 아니라, 파이프라인이 탐지 결과를 SAM2에 전달해 자동으로 마스크를 만드는 구조다.

### 5.3 적용한 해결

컨테이너 블러 로직을 별도 서비스로 분리하고 config의 `enabled`로 제어하게 했다.

예:

```yaml
preserved_container_blur:
  enabled: true
  blur_kernel: 9
  opacity: 1.0
  food_protection_dilation: 11
```

동작:

- `enabled: true`: preserve 모드에서 접시/용기 블러 실행
- `enabled: false`: 블러 단계를 건너뜀

### 5.4 블러 대상

블러 대상은 접시 전체가 아니다.

```text
접시 또는 용기 마스크
- 음식 보호 마스크
= 실제 블러 마스크
```

음식 영역은 보호하고 음식이 아닌 접시·용기 픽셀만 블러한다.

### 5.5 검증 상태

- 서비스 모듈 분리: 적용 완료
- config on/off: 적용 완료
- preserve 모드 한정 실행: 적용 완료

---

## 6. 배경 프롬프트를 짧게 줄였더니 결과가 더 이상해진 문제

### 6.1 실제 시도

SANA가 긴 프롬프트를 제대로 처리하지 못할 수 있다고 판단하여 다음 원칙으로 프롬프트를 줄이는 실험을 했다.

```text
120토큰 이하
핵심 정보만 사용
단순한 문장
Geometry 표현 1회
Mood 표현 1회
```

실험 프롬프트의 형태:

```text
Photorealistic cafe interior,
natural wooden table,
soft daylight,
warm atmosphere,
camera at 45 degrees,
empty center-lower area for food,
subtle props near the frame edges,
no people,
no text,
no logo
```

### 6.2 실제 결과

프롬프트를 줄인 뒤 다음 문제가 더 눈에 띄었다.

- 의미를 알 수 없는 글자 생성
- 이상한 모양의 물체 생성
- 배치 공간과 주변 소품 구조 불안정

### 6.3 원인 판단

이 프로젝트에서는 프롬프트 길이 자체보다 다음 조건을 빠뜨리지 않는 것이 더 중요했다.

- 음식이 놓일 빈 공간
- 촬영 각도
- 테이블 구조
- 업종별 공간 정보
- 만들면 안 되는 물체
- 로고와 글자 금지
- 중앙 또는 지정 배치 구역의 물체 금지

짧게 줄이면서 일부 구조적 조건이 약해져 SANA가 비어 있는 내용을 임의로 채운 것으로 판단했다.

### 6.4 적용한 해결

`app/services/background_prompt.py`와 관련 config의 프롬프트를 **짧게 줄이기 전의 원래 상세한 상태로 복구**했다.

이후 작업에서도 오전 9시 35분 기준 프롬프트는 원래 긴 구조를 기준으로 사용했다.

### 6.5 검증 상태

- 짧은 프롬프트 실험: 실제 출력으로 문제 확인
- 원래 프롬프트 복구: 적용 완료
- 기준 시점의 선택: 상세 프롬프트 사용

---

## 7. 접시 마스크와 알파 내부에 구멍이 생긴 문제

### 7.1 확인한 실제 출력물

다음 파일을 함께 비교했다.

```text
example_sam_stabilized_mask.png
example_plate_mask.png
example_sam_structural_mask.png
example_sam_alpha.png
example_plate_alpha.png
example_semantic_sam_candidate.png
example_semantic_sam_reference.png
```

### 7.2 실제 증상

- `example_plate_mask.png`와 `example_plate_alpha.png`는 접시 전체가 채워져 있었다.
- SAM 구조 마스크에는 음식과 접시 내부에 작은 검은 구멍이 있었다.
- 합성 후보에서는 이 구멍이 배경색으로 보일 수 있었다.
- 접시 옆 수저도 전경에 포함되어 있었다.

### 7.3 원인

SAM 계열 마스크는 픽셀의 색과 경계를 기준으로 물체를 분리한다.

접시 내부에는 다음 요소가 있어 같은 접시라도 서로 다른 영역처럼 보일 수 있다.

- 음식 그림자
- 반사광
- 접시 무늬
- 음식 사이의 어두운 빈 공간
- 꼬치 막대와 접시가 겹치는 부분

SAM 마스크만 최종 알파로 사용하면 이 작은 결손이 그대로 투명 영역이 된다.

### 7.4 처음 시도한 방법

- 형태학적 closing
- 작은 구멍 채우기
- 가장 큰 연결 영역 유지
- SAM 마스크 안정화

### 7.5 처음 방법만으로 부족했던 이유

형태학적 연산을 강하게 하면 구멍은 줄지만 다음 부작용이 생길 수 있었다.

- 접시 옆 수저까지 접시에 붙음
- 음식 사이의 실제 빈 공간도 모두 채워짐
- 접시 외곽이 필요 이상으로 커짐

### 7.6 적용한 해결

접시 전체를 보존하는 마스크와 음식/구조 마스크를 분리했다.

```text
SAM 구조 마스크
-> PlateMaskService.complete()
-> plate_mask
-> plate_alpha
```

그 다음 preserve 모드의 최종 알파에서 접시 알파를 다시 합쳤다.

```text
alpha = max(alpha, plate_alpha)
```

제거 작업 뒤에도 같은 원칙을 다시 적용했다.

```text
safe removal 적용
-> 제거 영역을 alpha에서 삭제
-> preserve 모드에서는 plate_alpha 재보존
```

### 7.7 얻은 결과

- `example_plate_alpha.png`의 완전히 채워진 접시 영역을 최종 알파에 유지할 수 있게 되었다.
- SAM 내부 구멍이 최종 접시 투명 구멍으로 남는 문제를 줄였다.
- 접시 전체 보존과 음식 경계 보완을 서로 다른 단계에서 처리할 수 있게 되었다.

### 7.8 검증 상태

- `plate_alpha` 별도 생성: 적용 완료
- preserve 모드 마지막 재보존: 적용 완료
- 출력 마스크 비교: 완료

---

## 8. 수저와 접시 주변 물체가 최종 결과에 남은 문제

### 8.1 실제 증상

양꼬치 접시 오른쪽의 수저가 다음 데이터에 포함되어 있었다.

- SAM 안정화 마스크
- SAM 알파
- semantic candidate/reference 이미지
- 최종 합성 이미지

### 8.2 원인

수저가 접시와 가까이 있었고 색 대비가 분명했기 때문에 탐지와 SAM 결과에서 별도 전경으로 유지되었다.

또한 물체 제거에는 두 종류의 데이터 수정이 필요했다.

```text
RGB 이미지에서 수저 픽셀 제거
알파 마스크에서 수저 영역 제거
```

RGB만 지우거나 알파만 지우면 최종 합성에 흔적이 남는다.

### 8.3 적용한 해결 1: 제거 대상 탐지

일반 YOLO 탐지 모델을 사용해 다음 COCO 계열 대상을 찾도록 했다.

```text
fork
knife
spoon
cup
bowl
```

탐지 박스를 제거 마스크로 변환했다.

### 8.4 적용한 해결 2: 음식과 접시 보호

제거 마스크에서 보호 영역을 제외해 `safe_removal_mask`를 만들었다.

```text
removal_mask
- dilated foreground protection mask
= safe_removal_mask
```

이 단계가 필요한 이유는 수저가 접시나 음식과 가까울 때 제거 박스가 필요한 전경까지 덮을 수 있기 때문이다.

### 8.5 적용한 해결 3: Big-LaMA 인페인팅

`safe_removal_mask`가 비어 있지 않을 때만 Big-LaMA를 실행했다.

```text
원본 RGB + safe_removal_mask
-> 수저 자리를 주변 픽셀로 메운 RGB
```

### 8.6 적용한 해결 4: 알파에서 같은 영역 제거

RGB에서 지운 영역을 알파에서도 제거했다.

```text
alpha[safe_removal_mask > 0] = 0
```

### 8.7 남은 문제

제거 탐지가 수저를 놓치면 `safe_removal_mask`가 비어 있고, Big-LaMA도 실행되지 않는다.

그런데 SAM/HQ-SAM 알파에는 수저가 계속 남을 수 있다.

### 8.8 적용한 해결 5: 분리된 외부 전경 컴포넌트 제거

접시 또는 음식 기준 마스크와 연결되지 않은 외부 전경 조각을 연결 요소 단위로 검사했다.

```text
현재 전경 alpha
-> 연결 요소 분리
-> 접시/음식 anchor와 연결되는지 확인
-> 연결되지 않은 작은 외부 요소 제거
```

디버그 출력:

```text
example_detached_foreground_mask.png
```

### 8.9 얻은 결과

수저 제거가 다음 두 경로를 가지게 되었다.

```text
1차: YOLO 제거 탐지 + Big-LaMA + alpha 삭제
2차: 분리된 외부 foreground 컴포넌트 후처리
```

### 8.10 검증 상태

- 제거 탐지 연결: 적용 완료
- Big-LaMA 안전 제거: 적용 완료
- RGB와 alpha 동시 제거: 적용 완료
- 분리 컴포넌트 후처리: 적용 완료
- 사진별 탐지 성공 여부: 각 실행의 `removal_mask`, `safe_removal_mask`, `detached_foreground_mask` 확인 필요

---

## 9. `generated_plate` 모드에서 원본 접시와 수저가 남는 문제

### 9.1 실제 요구

`generated_plate` 모드에서는 다음 요소가 최종 전경에 남으면 안 되었다.

- 원본 접시
- 원본 그릇과 용기
- 수저
- 컵
- 음식과 관계없는 주변 물체

음식만 남아 새 접시 또는 새 배경에 배치되어야 했다.

### 9.2 원인

SAM 구조 마스크 또는 안정화 알파에는 음식과 접시가 함께 포함될 수 있다.

generated 모드에서 preserve 모드와 같은 최종 알파 합성 규칙을 사용하면 접시가 다시 살아난다.

### 9.3 적용한 해결

generated 모드 최종 알파를 음식 활성 마스크와 강제로 교집합했다.

```text
generated_final_alpha
= current_alpha AND food_active_mask
```

제거한 수저·컵·그릇 영역도 같은 최종 알파에서 다시 삭제했다.

```text
generated_final_alpha[removal_area > 0] = 0
```

분리 컴포넌트 후처리의 기준도 generated 모드에서는 음식 마스크로 사용했다.

```text
preserve 모드 anchor = plate_alpha
generated 모드 anchor = food_active_mask
```

### 9.4 안전장치

음식만 나타내는 신뢰할 수 있는 마스크가 없으면 SAM 구조 마스크를 무조건 음식 마스크로 사용하는 것은 위험하다.

그래서 다음 옵션을 별도로 두었다.

```text
allow_sam_food_mask_for_generated_plate
```

이 옵션이 꺼져 있고 신뢰할 음식 마스크가 없으면 잘못된 합성을 만들기보다 중단하는 방향을 사용했다.

### 9.5 검증 상태

- generated 최종 알파 교집합: 적용 완료
- 제거 영역 alpha 동시 삭제: 적용 완료
- 음식 마스크 부족 시 안전 중단: 적용 완료
- 오전 9시 35분 기준 중심 테스트 경로: preserve 모드

---

## 10. 컨테이너 블러 마스크가 완전히 검게 나온 문제

### 10.1 확인한 실제 출력물

```text
example_container_blur_mask.png
example_background_replaced.jpg
example_generated_background_candidate_6.jpg
```

`example_container_blur_mask.png`는 전체가 검은색이었다.

### 10.2 처음 의심한 부분

처음에는 다음 가능성을 확인했다.

- OpenCV blur 함수가 실행되지 않음
- blur 기능이 config에서 꺼짐
- 접시 마스크가 비어 있음
- 마스크 크기가 이미지와 맞지 않음

### 10.3 실제 원인

블러 대상 계산식은 다음과 같았다.

```text
container_blur_mask
= plate_or_container_mask
- food_protection_mask
```

그런데 `food_protection_mask`로 `food_sam_alpha`처럼 접시까지 넓게 포함한 입력이 사용되었다.

결과:

```text
접시 영역 - 접시까지 포함한 보호 영역 = 빈 마스크
```

즉 블러 기능이 고장 난 것이 아니라 **음식 보호 마스크가 너무 넓어 블러할 접시 픽셀이 모두 보호된 것**이었다.

### 10.4 적용한 해결

컨테이너 블러의 보호 입력을 접시까지 포함한 넓은 알파가 아니라 음식 전용 마스크로 교체했다.

개념:

```text
이전 입력: food_sam_alpha
수정 입력: food_only_mask 계열
```

파이프라인에서는 실제 음식 활성 마스크에서 접시 보호 영역을 분리해 블러 보호 게이트로 전달하도록 정리했다.

### 10.5 얻은 결과

- 음식 픽셀은 블러에서 보호된다.
- 음식이 아닌 접시·용기 영역은 블러 후보로 남는다.
- 빈 블러 마스크의 원인이 기능 on/off가 아니라 입력 마스크였음을 구분할 수 있게 되었다.

### 10.6 확인 방법

다음 실행에서 아래 두 파일을 함께 비교해야 한다.

```text
food_active_mask.png
container_blur_mask.png
```

정상 조건:

- 음식 영역은 `container_blur_mask`에서 검은색
- 음식 바깥 접시/용기 영역 일부는 흰색
- 전체 마스크가 검은색이면 보호 마스크 입력을 다시 확인

### 10.7 검증 상태

- 보호 마스크 입력 교체: 적용 완료
- 디버그 마스크 저장: 적용 완료
- 사진별 실제 블러 면적: 출력 마스크로 확인 필요

---

## 11. 접시 끝부분이 잘리고 내부가 빈 것처럼 보인 문제

### 11.1 확인한 실제 출력물

여러 실행 폴더에서 다음 파일을 반복해서 비교했다.

```text
example_background_replaced.jpg
example_sam_alpha.png
example_sam_stabilized_mask.png
example_sam_structural_mask.png
example_container_blur_mask.png
example_food_active_mask.png
example_food_sam_mask.png
example_detached_foreground_mask.png
example_plate_mask.png
example_plate_alpha.png
```

### 11.2 실제 증상

- 최종 합성에서 접시 위쪽 초록색 림이 끊겨 보였다.
- 접시 마스크는 둥근 접시 영역을 대부분 포함하고 있었다.
- 접시 알파도 큰 원형 영역을 보존하고 있었다.
- 그런데 최종 RGB에서 초록색 테두리가 이어지지 않았다.
- 일부 실행에서는 회색선 또는 잘못된 위치의 선이 생겼다.

### 11.3 처음 세운 원인 후보

다음 단계를 각각 확인했다.

1. SAM2가 접시 경계를 놓쳤는가
2. 접시 마스크의 내부 구멍 때문에 잘렸는가
3. alpha feather가 림을 투명하게 만들었는가
4. 컨테이너 블러가 림을 흐리게 했는가
5. 음식 보호 마스크가 보정 영역을 막았는가
6. 접시와 떨어진 외부 물체 정리가 접시 일부를 지웠는가
7. 합성 배치 과정에서 foreground가 잘렸는가

### 11.4 확인 결과

접시 마스크와 접시 알파를 확대해 비교했을 때 접시 전체 영역은 상당 부분 존재했다.

따라서 문제를 두 종류로 나눴다.

```text
문제 A: 마스크/알파에서 접시 영역이 빠짐
문제 B: 마스크/알파는 있지만 RGB의 실제 림 색이 없음
```

초기에는 문제 A를 중심으로 수정했지만, 마지막에는 문제 B가 주요 원인으로 남았다.

---

## 12. 접시 끝부분을 연결하기 위해 실제로 시도한 방법

### 12.1 시도 1: 접시 마스크 내부 완전 보존

적용:

- `PlateMaskService`로 접시 전체 마스크 완성
- 내부 구멍 채우기
- `plate_alpha` 생성
- preserve 모드 마지막에 `plate_alpha` 재보존

효과:

- 접시 안쪽이 배경으로 뚫리는 문제를 줄였다.
- 중간 제거 단계 뒤 접시 알파가 사라지는 문제를 막았다.

한계:

- 알파가 존재해도 원본 RGB에 초록 림 픽셀이 없으면 초록 선은 나타나지 않는다.

### 12.2 시도 2: 음식과 접시 보호 마스크 분리

적용:

- 접시 보존에는 `plate_alpha`
- 음식 보호에는 음식 전용 마스크
- 제거에는 `safe_removal_mask`
- 블러에는 별도의 `container_blur_mask`

효과:

- 한 마스크가 모든 영역을 보호해 후처리가 멈추는 문제를 줄였다.
- 접시와 음식에 서로 다른 보호 규칙을 적용할 수 있게 되었다.

한계:

- 보호 규칙을 바로잡아도 이미 가려진 초록 림 RGB는 새로 생기지 않는다.

### 12.3 시도 3: 컨테이너 블러 약화 또는 비활성화

확인 목적:

- 블러가 접시 림 절단의 직접 원인인지 확인

효과:

- 블러에 의한 추가 흐림을 줄일 수 있었다.

확인 결과:

- 블러만 꺼도 끊어진 초록 림이 완전히 이어지지는 않았다.
- 따라서 블러는 보조 원인이 될 수 있지만 핵심 원인은 아니었다.

### 12.4 시도 4: 기하학적 접시 타원과 림 위치 계산

적용:

- `plate_mask` 외곽을 기준으로 접시 타원 추정
- 접시 안쪽 림 위치 추정
- 상단에서 끊어진 구간 계산

효과:

- 보정해야 할 위치를 마스크로 만들 수 있었다.
- 접시 전체를 칠하지 않고 상단 결손 구간만 선택할 수 있었다.

한계:

- 타원 위치가 실제 진한 초록 림과 다르면 회색선이나 가짜 선이 생길 수 있었다.
- 기하학은 위치를 알려 주지만 실제 색과 질감을 만들지는 않는다.

### 12.5 시도 5: 주변 픽셀 기반 인페인팅과 블렌딩

적용:

- 결손 구간만 작은 마스크로 제한
- 주변 접시 표면 픽셀을 사용한 inpaint
- feather와 alpha blend 적용

효과:

- 흰 접시 표면의 작은 결손은 완화할 수 있었다.

한계:

- 얇고 진한 초록 림은 방향성이 강한 선이다.
- 일반 inpaint는 주변의 넓은 흰 접시 색으로 채우는 경향이 있어 초록 선을 충분히 이어 주지 못했다.

### 12.6 시도 6: HQ-SAM 경계 보완

적용 이유:

- SAM2가 놓친 작은 경계 후보를 더 정밀하게 찾기 위해 추가했다.

설정 방향:

```yaml
hq_sam:
  enabled: true
  model_id: models/hq-sam
  selection_mode: patch_missing
```

`patch_missing`의 제한:

- 탐지 박스 안쪽만 사용
- SAM2 경계 근처만 사용
- 지나치게 큰 패치는 거절
- SAM2 전체 마스크를 무조건 교체하지 않음

효과:

- SAM2 경계의 작은 결손을 보완할 후보가 생겼다.
- config로 HQ-SAM을 켜고 끌 수 있게 되었다.
- Colab에서는 처음 한 번 모델을 받아 `models/hq-sam`에 저장하고 이후 로컬 모델 경로를 사용하도록 구성했다.

한계:

- HQ-SAM은 보이는 경계를 더 잘 나누는 모델이다.
- 음식과 꼬치에 가려져 원본에 보이지 않는 초록 림 RGB를 그대로 복원하는 모델은 아니다.
- HQ-SAM 후보가 있어도 최종 RGB에 초록 림 색을 그리는 별도 처리가 필요했다.

### 12.7 시도 7: HQ-SAM을 빈 영역에만 적용

전체 마스크를 HQ-SAM으로 바꾸면 접시 밖 물체까지 포함할 수 있어, SAM2 결과의 빈 부분을 보완하는 방식으로 제한했다.

개념:

```text
SAM2 기본 마스크 유지
+ 허용된 결손 영역의 HQ-SAM 후보
= 보완 마스크
```

효과:

- 기존 SAM2 전경을 유지하면서 작은 결손만 보완할 수 있었다.

한계:

- 이 단계도 마스크 보완이며 RGB 림 색 생성은 아니다.

---

## 13. 오전 9시 35분에 확정한 핵심 원인

### 13.1 확인한 실제 수치

최신 실행 리포트에서 다음 값이 기록되었다.

```text
inner_rim_line_pixels: 17196
missing_pixels: 5237
missing_rim_core_pixels: 5237
```

### 13.2 수치의 의미

- `inner_rim_line_pixels`: 계산된 안쪽 림 선의 전체 픽셀 수
- `missing_pixels`: 현재 RGB/마스크에서 보완 대상으로 판단한 픽셀 수
- `missing_rim_core_pixels`: 림 중심부에서 반드시 보완해야 한다고 판단한 픽셀 수

세 값이 0이 아니므로 다음 작업은 이미 수행되고 있었다.

- 접시 림 위치 계산
- 결손 위치 계산
- 보정 마스크 생성

### 13.3 최종 원인 판단

보정 위치는 충분히 잡혔지만 최종 이미지에서는 초록 림이 이어지지 않았다.

따라서 오전 9시 35분의 판단은 다음과 같다.

```text
남은 핵심 문제는 접시 마스크의 면적 부족이 아니다.
남은 핵심 문제는 최종 RGB에 림 색이 충분한 강도로 적용되지 않은 것이다.
```

이 판단 이후에는 마스크를 계속 팽창시키는 작업보다, 림 색을 어떻게 적용할지를 우선 수정했다.

---

## 14. 오전 9시 35분에 적용한 최종 수정

### 14.1 수정 목적

끊어진 상단 림 구간에 실제 접시 림과 비슷한 색을 충분한 강도로 적용한다.

### 14.2 수정 파일

```text
app/services/plate_edge_repair.py
configs/pipeline.yaml
```

### 14.3 색 샘플링 변경

접시 주변의 모든 색을 평균내면 흰 접시 표면과 회색 그림자가 섞여 초록색이 약해진다.

그래서 원본 RGB에서 **채도가 높은 림 후보 픽셀만** 샘플링하게 했다.

```text
원본 접시 림 주변 픽셀
-> 채도 기준 적용
-> 고채도 림 색 후보
-> synthetic bridge 색
```

기준 설정:

```yaml
synthetic_rim_color_saturation_min: 45
```

### 14.4 브리지 적용 변경

기존의 약한 inpaint/blur 보정만으로는 초록색이 충분히 나타나지 않았다.

그래서 계산된 상단 결손 구간에 거의 불투명한 브리지를 적용하도록 강화했다.

```yaml
synthetic_rim_bridge_enabled: true
synthetic_rim_bridge_opacity: 0.98
synthetic_rim_bridge_extra_width: 3
synthetic_rim_bridge_feather_kernel: 3
synthetic_rim_color_saturation_min: 45
```

각 값의 의미:

| 설정 | 의미 |
| --- | --- |
| `synthetic_rim_bridge_enabled` | 상단 림 강제 연결 기능을 실행한다. |
| `synthetic_rim_bridge_opacity` | 브리지 색을 얼마나 강하게 보일지 정한다. `0.98`은 거의 불투명하다. |
| `synthetic_rim_bridge_extra_width` | 계산된 림보다 몇 픽셀 더 넓게 연결할지 정한다. |
| `synthetic_rim_bridge_feather_kernel` | 브리지 가장자리만 주변과 부드럽게 섞는다. |
| `synthetic_rim_color_saturation_min` | 회색과 흰색을 제외하고 실제 림 계열 색을 고르는 최소 채도다. |

### 14.5 이전 방식과 차이

이전:

```text
결손 위치를 찾음
-> 주변 색으로 약하게 inpaint 또는 blur
```

오전 9시 35분 수정:

```text
결손 위치를 찾음
-> 원본 고채도 림 색을 샘플링
-> 해당 위치에 거의 불투명한 림 bridge 적용
-> 가장자리만 작게 feather
```

### 14.6 코드가 실제로 실행됐는지 확인하는 지표

다음 실행 리포트에서 아래 값을 확인해야 한다.

```json
{
  "step_5d_plate_edge_repair": {
    "synthetic_rim_bridge_pixels": 1000,
    "synthetic_rim_color_sample_count": 100,
    "missing_rim_core_pixels": 5237
  }
}
```

판단:

- `synthetic_rim_bridge_pixels > 0`: 브리지 픽셀이 최종 보정에 사용됨
- `synthetic_rim_color_sample_count > 0`: 원본에서 림 색 샘플을 얻음
- `missing_rim_core_pixels > 0`: 보정 대상으로 판단한 림 결손이 존재함

### 14.7 검증 상태

- 고채도 림 색 샘플링 코드: 적용 완료
- 강한 synthetic bridge 코드: 적용 완료
- config 값 반영: 적용 완료
- `plate_edge_repair.py` 문법 검사: 통과
- `git diff --check`: 통과
- 변경 후 모든 사진에서 자연스럽게 연결되는지: 다음 실행 확인 필요

### 14.8 아직 완료라고 말할 수 없는 부분

다음 실행에서 지표가 0보다 크더라도 시각적으로 확인해야 한다.

- 실제 초록 림 위치와 같은 위치에 그려졌는가
- 선이 너무 굵지 않은가
- 꼬치 막대 위를 부자연스럽게 덮지 않는가
- 회색선 또는 별도의 가짜 선처럼 보이지 않는가
- 좌우의 기존 림과 색이 자연스럽게 연결되는가

오전 9시 35분 기준의 정확한 상태는 **수정과 구조 검증은 완료됐고, 강화된 설정으로 만든 새 결과의 최종 시각 검증은 다음 실행에서 해야 하는 상태**다.

---

## 15. 실제로 사용한 디버그 파일과 확인 목적

| 파일 | 확인한 내용 |
| --- | --- |
| `example_background_replaced.jpg` | 최종 접시 림 절단, 수저 잔존, 합성 위치 |
| `example_sam_structural_mask.png` | SAM이 음식·접시·수저를 어떤 구조로 포함했는지 |
| `example_sam_stabilized_mask.png` | 형태 안정화 뒤 내부 구멍과 외부 물체 상태 |
| `example_sam_alpha.png` | 최종 투명도 후보에 구멍이나 수저가 남았는지 |
| `example_plate_mask.png` | 접시 전체 형태가 완전히 채워졌는지 |
| `example_plate_alpha.png` | preserve 모드에서 재보존할 접시 알파가 완전한지 |
| `example_food_sam_mask.png` | SAM 기반 음식 후보 범위 |
| `example_food_active_mask.png` | 블러와 generated 모드에서 사용할 실제 음식 보호 범위 |
| `example_container_blur_mask.png` | 음식 바깥 접시/용기만 블러 대상으로 남았는지 |
| `example_safe_removal_mask.png` | Big-LaMA가 안전하게 지울 영역이 존재하는지 |
| `example_detached_foreground_mask.png` | 접시·음식과 떨어진 수저 조각이 후처리에서 잡혔는지 |
| `example_semantic_sam_reference.png` | 원본 전경 비교 영역 |
| `example_semantic_sam_candidate.png` | 합성 전경 비교 영역과 알파 구멍 |
| `example_plate_edge_repair_mask.png` | 실제 림 보정 대상 위치 |
| `background_replacement_report.json` | 각 단계 실행 여부와 픽셀 수치 |

---

## 16. 문제별 최종 상태 요약

| 실제 문제 | 오전 9시 35분까지 적용한 해결 | 상태 |
| --- | --- | --- |
| Colab에서 카페 외 사진과 분위기 테스트가 어려움 | 사진 한 장, `business_type`, `desired_mood`, `composition_mode` 선택 지원 | 적용 완료 |
| 접시와 음식이 항상 함께 가져와짐 | preserve/generated 모드와 최종 알파 규칙 분리 | 적용 완료 |
| 접시·용기 블러를 끌 수 없음 | `preserved_container_blur.enabled` 설정 추가 | 적용 완료 |
| 짧은 SANA 프롬프트에서 이상한 글자와 모양 증가 | 짧게 줄이기 전의 상세 프롬프트로 복구 | 출력 확인 후 복구 완료 |
| 접시 알파 내부 구멍 | `plate_mask` 완성, `plate_alpha` 별도 생성, preserve 마지막 재보존 | 적용 및 출력 확인 완료 |
| 수저와 컵이 전경에 남음 | 제거 탐지, Big-LaMA, alpha 동시 삭제, 분리 컴포넌트 정리 | 적용 완료, 사진별 탐지 확인 필요 |
| generated 모드에 원본 접시가 남음 | 최종 alpha와 `food_active_mask` 강제 교집합 | 적용 완료 |
| 컨테이너 블러 마스크가 전부 검음 | 보호 입력을 음식 전용 마스크로 교체 | 적용 완료, 다음 출력 확인 필요 |
| 접시 끝 마스크가 불안정함 | SAM2 안정화, PlateMaskService, HQ-SAM `patch_missing` | 적용 완료 |
| 마스크는 있는데 초록 림 RGB가 이어지지 않음 | 고채도 림 색 샘플링과 강한 synthetic rim bridge | 코드·설정 검증 완료, 다음 시각 검증 필요 |

---

## 17. 이 기록의 결론

오전 9시 35분까지의 작업에서 가장 중요한 변화는 문제를 하나의 마스크 문제로 보지 않게 된 것이다.

실제 파이프라인에서는 다음 데이터를 분리해서 처리해야 했다.

```text
탐지 박스
SAM2/HQ-SAM 구조 마스크
음식 전용 보호 마스크
접시 전체 마스크
접시 보존 알파
안전 제거 마스크
컨테이너 블러 마스크
분리된 외부 전경 마스크
접시 림 보정 마스크
최종 RGB
최종 알파
```

각 문제의 핵심은 다음과 같았다.

```text
접시 구멍
-> plate_alpha를 별도로 보존

수저 잔존
-> RGB와 alpha에서 같은 영역 제거

빈 블러 마스크
-> 접시까지 포함한 보호 입력을 음식 전용 입력으로 교체

접시 끝 절단
-> 마스크 보완과 실제 RGB 림 색 복원을 분리

초록 림이 안 이어짐
-> 결손 위치 계산만 하지 않고 원본 고채도 림 색을 강하게 적용
```

이 문서의 마지막 기준점은 다음과 같다.

```text
HQ-SAM 사용
preserve_original_plate 중심
BiRefNet 비활성화
접시 전용 학습 segmentation 모델은 아직 범위 밖
synthetic rim bridge 강화 적용
강화 후 새 출력의 최종 시각 검증은 다음 실행에서 수행
```
