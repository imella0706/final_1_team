# 이미지 보정 모델과 데이터 흐름 설명서

## 문서 기준

이 문서는 `food-image-cleanup-pipeline`의 상태를 **2026년 7월 27일 오전 9시 35분까지의 대화와 작업 내용**을 기준으로 설명한다.

이 기준 시점에서 가장 중요한 상태는 다음과 같다.

- 네이버 채널을 선택했을 때 실행되는 이미지 보정 기능을 설명한다.
- 기본 합성 방식은 `preserve_original_plate`이다.
- SAM2가 기본 마스크를 만들고 HQ-SAM이 빠진 경계를 보완한다.
- 원본 음식과 원본 접시는 최대한 그대로 남긴다.
- 배경은 SANA가 새로 만든다.
- 수저, 컵 등 불필요한 물체는 탐지한 뒤 Big-LaMA로 지운다.
- 접시 위쪽의 끊어진 초록색 테두리는 `synthetic_rim_bridge`로 보완한다.
- BiRefNet은 이 시점에 꺼져 있다.

> 중요: 접시 전체와 보이는 음식을 학습한 `YOLO11-seg` 모델은 오전 9시 35분 이후에 학습하고 연결한 기술이다. 따라서 이 문서의 모델 목록, 처리 흐름, 현재 사용 여부에는 포함하지 않는다.

### 현재 코드와 함께 읽을 때 주의할 점

이 문서는 오전 9시 35분 기준의 사람이 읽는 설명서다. 이후 코드에는 실험과 전환을 쉽게 하기 위한 설정 항목이 더 들어가 있지만, 기본 파이프라인이 모두 그 기능을 실행한다는 뜻은 아니다.

현재 코드에서 특히 헷갈릴 수 있는 부분은 다음과 같다.

| 현재 코드에 보이는 항목 | 사람이 이해해야 하는 의미 |
| --- | --- |
| `models.plate_segmenter` | 접시 전용 `YOLO11-seg` 어댑터다. 오전 9시 35분 이후 작업이므로 이 문서의 기준 흐름에는 포함하지 않는다. 현재 기본 설정은 `enabled: false`이므로 실행되지 않는다. |
| `plate_edge_repair.synthetic_rim_bridge_top_ratio` | 강제 림 브리지를 이미지의 위쪽 어느 범위에서만 찾을지 정하는 보조 설정이다. 접시 상단 림 끊김 문제를 좁혀 처리하기 위한 값이다. |
| `plate_edge_repair.synthetic_rim_bridge_dilation` | 끊긴 림 주변을 얼마나 넓게 보면서 연결 후보를 만들지 정한다. 값이 커질수록 더 강하게 이어 보려 한다. |
| `plate_edge_repair.synthetic_rim_bridge_horizontal_margin` | 상단 림의 좌우 연결 범위를 조금 더 넓게 잡기 위한 여유 값이다. |
| `plate_edge_repair.synthetic_rim_bridge_connect_full_top` | 상단 림이 여러 조각으로 끊겨 있을 때 한 줄처럼 이어 보려는 옵션이다. |
| `plate_edge_repair.synthetic_rim_bridge_dilate` | 만든 브리지 마스크를 조금 두껍게 만들어 실제 초록 림이 충분히 보이게 하는 옵션이다. |
| `plate_edge_repair.synthetic_rim_band_enabled` | 별도의 림 밴드를 그리는 실험 옵션이다. 현재 기본값은 `false`이므로 사용하지 않는다. |
| `plate_edge_repair.plate_mask_rim_completion_enabled` | `plate_mask` 기준으로 림을 완성하는 실험 옵션이다. 현재 기본값은 `false`이므로 최종 결과에 영향을 주지 않는다. |
| `models.plate_mask.minimum_shape_confidence`와 `contour_completion_enabled` | 오전 9시 35분 이후 추가된 용기 일반화 설정이다. 현재 코드는 타원·사각형 계열·비정형을 나누고, 저신뢰 형태는 임의 완성하지 않는다. |
| `models.mask_quality` | 오전 9시 35분 이후 추가된 음식·접시 독립 품질 검사다. 이 문서의 당시 흐름에는 없지만 현재 보고서의 `step_2c_mask_quality`에 기록된다. |
| `models.food_support_recovery` | 오전 9시 35분 이후 추가된 꼬치형 지지 구조 보호 단계다. preserve 모드에서만 실행하며 기하학만으로는 채택하지 않는다. |
| `plate_edge_repair.adaptive_rim_observation` | 현재는 고정 초록색 범위보다 원본 RGB의 실제 림 관찰을 우선한다. 신뢰도가 `0.53` 미만이면 합성 림과 알파 확장을 차단한다. |

즉, 오전 9시 35분 기준 핵심 해결책은 여전히 **HQ-SAM 보조 마스크 + 원본 접시 보존 + Big-LaMA 제거 + synthetic rim bridge**다. 이후에 보이는 비활성 옵션들은 다음 실험을 빠르게 켜기 위한 스위치로 보면 된다.

현재 운영 코드를 설명할 때는 이 시점 문서만 사용하지 말고 `README.md`와 `docs/ARCHITECTURE.md`를 우선한다. 음식 지지 구조를 모든 후처리 뒤 최상단 RGB 레이어로 다시 합성하는 후속 실험은 취소됐으며 현재 코드에는 `step_5e_food_support_layer`가 없다.

---

## 1. 이 기능을 한 문장으로 설명하면

이 기능은 **음식과 접시는 원래 사진에서 가져오고, 지저분한 주변 물체는 지우고, 더 보기 좋은 새 배경을 만든 다음 자연스럽게 합치는 기능**이다.

예를 들어 양꼬치 접시 사진을 넣으면 다음과 같이 일한다.

1. 사진에서 음식과 접시가 어디에 있는지 찾는다.
2. 음식과 접시의 정확한 모양을 색칠하듯 표시한다.
3. 수저나 컵처럼 남기지 않을 물체를 찾고 지운다.
4. 접시 테두리가 끊겼다면 보완한다.
5. 카페, 음식점 등 사용자가 고른 업종과 분위기에 맞는 배경을 만든다.
6. 원래 음식과 접시를 새 배경 위에 올린다.
7. 결과가 이상하지 않은지 검사한 뒤 저장한다.

여기서 가장 중요한 원칙은 **음식을 새로 그리지 않는 것**이다. 생성 모델이 음식을 다시 만들면 음식의 모양, 양, 재료가 달라질 수 있기 때문이다.

---

## 2. 먼저 알아야 하는 쉬운 용어

### 박스

사진에서 물체가 있는 위치를 네모로 표시한 것이다.

```text
사진 전체
┌─────────────────────┐
│                     │
│      ┌───────┐      │
│      │ 음식  │      │
│      └───────┘      │
│                     │
└─────────────────────┘
```

박스는 빠르게 위치를 찾는 데 좋지만, 접시의 둥근 모양이나 음식의 울퉁불퉁한 가장자리까지 표현하지는 못한다.

### 마스크

사진에서 남길 부분을 흰색, 버릴 부분을 검은색으로 표시한 흑백 그림이다.

```text
흰색 = 남길 음식이나 접시
검은색 = 지우거나 새 배경으로 바꿀 부분
```

### 알파

마스크보다 조금 더 부드러운 투명도 지도다.

- `255`: 완전히 보인다.
- `0`: 완전히 투명하다.
- 중간값: 가장자리를 부드럽게 섞는다.

알파가 너무 딱딱하면 오려 붙인 스티커처럼 보인다. 반대로 너무 흐리면 접시 테두리나 음식 끝이 사라질 수 있다.

### 인페인팅

지운 물체 자리를 주변 무늬와 색으로 메우는 작업이다. 이 프로젝트에서는 Big-LaMA가 이 일을 한다.

### 전경과 배경

- 전경: 최종 이미지에 남길 음식과 접시
- 배경: 새로 만들거나 교체할 테이블과 공간

---

## 3. 전체 흐름을 쉬운 그림으로 보기

```text
원본 사진 + 업종 + 원하는 분위기
                |
                v
      음식과 접시 위치 찾기
      GroundingDINO + 일반 YOLO 탐지
                |
                v
      정확한 모양의 마스크 만들기
             SAM2
                |
                v
      빠진 경계만 더 자세히 보완
             HQ-SAM
                |
                v
      접시 전체 모양과 알파 보존
        PlateMaskService
                |
                v
      수저와 컵 같은 물체 제거
        제거 탐지 + Big-LaMA
                |
                v
      접시 블러와 테두리 보정
      ContainerBlur + PlateEdgeRepair
                |
                v
      새 배경 후보 여러 장 생성
              SANA
                |
                v
      음식과 접시를 새 배경에 합성
                |
                v
      의미, 위치, 품질 검사
        OpenCLIP + 규칙 검사
                |
                v
             최종 이미지
```

---

## 4. 모델 역할표

이 표에는 **학습된 인공지능 모델**만 적었다. 일반 Python 처리 코드와 서비스는 다음 장에서 따로 설명한다.

| 모델 | 오전 9시 35분 사용 여부 | 왜 사용했는가 | 주요 특징 | 현재 사용하지 않는 경우와 이유 |
| --- | --- | --- | --- | --- |
| GroundingDINO | 사용 | 사진마다 접시, 음식, 그릇의 종류가 달라도 글자로 물체를 설명해 찾기 위해 사용했다. | `plate`, `bowl`, `food`처럼 이름을 프롬프트로 주면 관련 물체의 박스를 찾는다. 처음 보는 종류도 비교적 유연하게 찾는다. | 사용 중이다. 다만 정확한 테두리를 만드는 모델은 아니므로 SAM2가 뒤에서 마스크를 만든다. |
| 일반 YOLO 탐지 모델 | 사용 | GroundingDINO가 음식을 놓쳤을 때 보완하고, 수저·컵·그릇처럼 지울 물체를 빠르게 찾기 위해 사용했다. | 속도가 빠르고 정해진 종류의 물체를 찾는 데 강하다. 이 기준 시점에서는 물체의 위치 박스를 반환하는 탐지 역할로 사용한다. | 사용 중이다. 음식과 제거 대상의 위치를 찾는 역할만 담당한다. |
| SAM2 | 사용 | 탐지 박스 안에서 음식과 접시의 실제 모양을 픽셀 단위로 따기 위해 사용했다. | 박스를 힌트로 받아 물체 마스크를 만든다. 다양한 물체에 사용할 수 있다. | 기본 마스크 모델이므로 계속 사용한다. 하지만 가려진 접시 테두리를 상상해서 완성하는 모델은 아니다. |
| HQ-SAM | 사용 | SAM2가 놓친 얇은 경계나 작은 구멍을 더 정밀하게 보완하기 위해 추가했다. | SAM 계열 중 경계 품질을 높이는 데 초점을 둔다. 이 프로젝트에서는 전체 마스크를 무조건 바꾸지 않고 `patch_missing` 방식으로 빠진 곳만 보완한다. | 사용 중이다. GPU와 RAM을 더 사용하지만 이 기준 시점에는 경계 보완을 위해 켜 두었다. |
| Big-LaMA | 사용 | 수저, 컵, 불필요한 그릇을 지운 자리를 자연스럽게 메우기 위해 사용했다. | 제거 마스크 안을 주변의 색과 무늬를 참고해 채운다. 물체를 찾는 모델은 아니며, 지울 위치를 따로 받아야 한다. | 사용 중이다. 음식이나 접시 보호 마스크가 잘못되면 필요한 부분까지 지울 수 있으므로 보호 로직이 중요하다. |
| SANA 1.6B | 사용 | 업종과 분위기에 맞는 새 배경을 만들기 위해 사용했다. | 텍스트 프롬프트로 테이블, 조명, 공간을 생성한다. 여러 후보를 만든 뒤 가장 적합한 것을 선택한다. | 사용 중이다. 음식 자체를 만들게 하지 않고, 음식이 놓일 빈 공간이 있는 배경을 만들도록 제한한다. |
| OpenCLIP | 사용 | 합성 뒤 음식과 접시의 의미와 모습이 원본에서 너무 달라지지 않았는지 비교하기 위해 사용했다. | 원본 전경과 합성 전경을 숫자 벡터로 바꿔 유사도를 계산한다. | 사용 중이다. 경계가 한두 픽셀 끊긴 것을 직접 고치는 모델은 아니며, 결과 검사용이다. |
| EfficientNet-B0 | 사용 | 원본 사진이 위에서 찍힌 사진인지 45도 방향에서 찍힌 사진인지 구분하기 위해 사용했다. | 비교적 가벼운 이미지 분류 모델이다. 분류 결과는 배경 프롬프트와 배치 크기에 사용된다. | 사용 중이다. 사용자가 수동 각도를 주면 모델 판단 대신 사용자의 값을 쓸 수 있다. |
| BiRefNet | 사용하지 않음 | 처음에는 더 부드러운 알파 경계를 만들 수 있는 후보로 준비했다. | 머리카락처럼 복잡한 전경을 세밀하게 분리하는 매팅 모델이다. | `matting.enabled: false`다. 이 프로젝트에서는 접시 림과 음식 가장자리가 흐려질 위험이 있었고, Colab 메모리 부담도 늘어나므로 이 시점에는 로드하지 않는다. |

### 모델을 여러 개 쓰는 이유

한 모델이 모든 일을 잘하지 못하기 때문이다.

- GroundingDINO와 YOLO는 **어디에 있는지** 잘 찾는다.
- SAM2와 HQ-SAM은 **어떤 모양인지** 잘 자른다.
- Big-LaMA는 **지운 자리를 메운다**.
- SANA는 **새 배경을 그린다**.
- OpenCLIP은 **결과가 원본과 비슷한지 검사한다**.

학교 행사로 비유하면, 한 명이 장소를 찾고, 한 명이 가위로 오리고, 한 명이 빈 곳을 칠하고, 다른 한 명이 마지막 검사를 하는 것과 같다.

---

## 5. 서비스 역할표

서비스는 모델 자체가 아니라 **모델을 불러서 실제 작업 순서를 만드는 Python 코드**다.

| 서비스 또는 코드 | 역할 | 받는 데이터 | 내보내는 데이터 |
| --- | --- | --- | --- |
| `BackgroundReplacementPipeline` | 전체 작업의 반장이다. 모든 단계를 순서대로 호출하고 실패 여부를 기록한다. | 원본 이미지, 메타데이터, 설정 | 최종 이미지, 리포트, 디버그 파일 |
| `GroundingDINODetector` | GroundingDINO를 실행하고 음식·접시·그릇 박스를 정리한다. | 이미지, 텍스트 대상 이름 | 탐지 박스와 이름 |
| `UltralyticsDetector` | 일반 YOLO 탐지를 실행하고 GroundingDINO가 놓친 결과를 보완한다. | 이미지, 탐지 프로필 | 음식 또는 용기 박스 |
| `SAM2Segmenter` | 박스를 이용해 기본 음식·접시 마스크를 만든다. | 이미지, 박스 | 기본 마스크 |
| `HQSAMSegmenter` | SAM2 경계 근처의 빠진 부분을 후보 마스크로 보완한다. | 이미지, 박스, SAM2 마스크 | 보완 마스크와 선택 정보 |
| `PlateMaskService` | 조각난 접시 마스크를 하나의 안정된 접시 모양으로 완성한다. | 구조 마스크, 접시 후보 | 완성된 접시 마스크 |
| `build_plate_preservation_alpha`, `validate_plate_preservation_alpha` | 접시 마스크를 부드러운 알파로 만들고 마지막까지 접시가 사라지지 않도록 보호한다. | 접시 마스크 | `plate_alpha`와 검증 결과 |
| `RemovalTargetDetector` | 수저, 포크, 칼, 컵, 그릇처럼 지울 물체를 찾는다. | 이미지 | 제거 박스 |
| `BigLaMaInpainter` | Big-LaMA를 실행해 제거 마스크 자리를 주변 픽셀처럼 메운다. | 이미지, 안전 제거 마스크 | 물체가 제거된 이미지 |
| `BackgroundReplacementPipeline` 내부 foreground cleanup | 접시나 음식과 떨어져 홀로 남은 작은 전경 조각을 알파에서 제거한다. | 알파, 기준 마스크 | 정리된 알파, 제거 조각 마스크 |
| `apply_container_blur` | 음식은 보호하고 음식이 아닌 접시·용기 부분에만 설정된 블러를 적용한다. | 이미지, 접시 마스크, 음식 보호 마스크 | 블러된 이미지와 블러 마스크 |
| `repair_plate_edge` | 접시 테두리의 결손을 찾고 상단 림을 보완한다. | 이미지, 접시 마스크, 음식 마스크, 설정 | 보정된 이미지와 보정 리포트 |
| `CameraAngleClassifier` | 사진 촬영 각도를 `top` 또는 `45`로 분류한다. | 원본 이미지 | 각도 이름과 신뢰도 |
| `build_background_prompt` | 업종, 분위기, 각도를 SANA가 이해할 배경 설명으로 만든다. | `business_type`, `desired_mood`, 각도 | 배경 프롬프트 |
| `FluxBackgroundGenerator` | SANA 또는 설정된 생성 모델을 실행해 배경 후보를 만든다. | 프롬프트, 이미지 크기, 시드 | 여러 배경 후보 |
| `score_background_candidate` | 음식이 놓일 자리가 비어 있고 구도가 맞는 후보를 고른다. | 배경 후보, 탐지 결과, 점수 | 후보 점수 |
| `place_foreground` | 음식과 접시의 RGBA 이미지를 새 배경의 알맞은 위치에 놓는다. | 전경 RGBA, 배경, 각도 | 합성 이미지와 배치 정보 |
| `add_contact_shadow` | 접시가 테이블 위에 떠 보이지 않도록 접촉 그림자를 만든다. | 배치된 알파, 배경 | 그림자가 추가된 이미지 |
| `harmonize_foreground` | 원본 전경의 밝기와 색을 새 배경에 조금 맞춘다. | 합성 이미지, 알파 | 색이 조화된 이미지 |
| `OpenCLIPSemanticValidator` | OpenCLIP으로 원본 전경과 합성 전경의 유사도를 검사한다. | 원본 전경, 합성 전경 | 유사도와 통과 여부 |
| `validate_result` | 밝기, 대비, 흐림 등 품질 규칙을 검사한다. | 최종 합성 및 중간 지표 | 최종 통과 또는 거절 |

### 각 서비스의 간단한 작동 로직

아래 설명은 코드를 처음 보는 사람이 “이 서비스가 안에서 대략 무엇을 하는지” 이해하기 위한 요약이다.

| 서비스 또는 코드 | 간단한 로직 |
| --- | --- |
| `BackgroundReplacementPipeline` | 입력 이미지를 읽고 품질을 기록한다. 그 다음 탐지, 분할, 제거, 보정, 배경 생성, 합성, 검증을 정해진 순서대로 실행한다. 중간 결과는 `debug_artifacts`에, 단계별 상태는 리포트의 `stages`에 저장한다. |
| `GroundingDINODetector` | 설정의 텍스트 프롬프트를 모델에 넣어 `plate`, `dish`, `food` 같은 대상의 박스를 찾는다. 결과는 접시/용기 박스와 음식 박스로 나누어 다음 SAM 단계의 힌트로 넘긴다. |
| `UltralyticsDetector` | YOLO 가중치를 로드하고 이미지에서 설정된 클래스만 찾는다. GroundingDINO가 음식이나 용기를 못 찾은 경우 빈 쪽만 보완하며, 이미 찾은 GroundingDINO 결과를 무조건 덮어쓰지 않는다. |
| `SAM2Segmenter` | 탐지 박스를 SAM2의 프롬프트로 넣는다. SAM2가 만든 여러 마스크를 한 장의 흰색/검은색 마스크로 합쳐 음식·접시의 기본 형태를 만든다. |
| `HQSAMSegmenter` | SAM2와 같은 박스를 보고 더 정밀한 후보 마스크를 만든다. `patch_missing` 모드에서는 SAM2 경계 근처, 박스 안쪽, 작은 면적 조건을 만족하는 빠진 부분만 추가한다. |
| `select_segmentation_result` | SAM2 결과와 HQ-SAM 결과를 비교한다. 설정이 `patch_missing`이면 SAM2 마스크를 기본으로 두고 허용된 작은 결손만 HQ-SAM에서 가져온다. |
| `PlateMaskService` | 구조 마스크에서 접시처럼 보이는 큰 영역을 고른다. 내부 구멍을 메우고 타원 형태와 면적 조건을 검사해 접시 전체 마스크를 안정화한다. |
| `build_plate_preservation_alpha` | 접시 마스크 가장자리를 약하게 부드럽게 만들어 `plate_alpha`를 만든다. preserve 모드에서는 마지막 alpha에 이 값을 다시 합쳐 접시가 중간 처리에서 사라지지 않게 한다. |
| `validate_plate_preservation_alpha` | `plate_alpha`가 접시 마스크를 충분히 덮는지 검사한다. 내부 구멍이 너무 많거나 접시 커버리지가 낮으면 리포트에 경고성 지표를 남긴다. |
| `RemovalTargetDetector` | YOLO로 `fork`, `knife`, `spoon`, `cup`, `bowl` 같은 제거 대상 박스를 찾는다. 실제로 지워도 되는지는 뒤에서 음식·접시 보호 마스크를 빼면서 다시 제한한다. |
| `removal_mask_from_boxes` | 제거 대상 박스를 흰색 마스크로 칠하고 조금 팽창시킨다. 물체 가장자리까지 Big-LaMA가 메울 수 있게 여유를 주는 단계다. |
| `BigLaMaInpainter` | 안전 제거 마스크가 비어 있으면 원본을 그대로 반환한다. 마스크가 있으면 Big-LaMA에 이미지와 마스크를 넣고, 지운 영역을 주변 색과 무늬로 채운 이미지를 만든다. |
| foreground cleanup | 최종 alpha 후보에서 접시·음식 기준 영역과 연결되지 않은 별도 전경 조각을 찾는다. 작은 수저 조각처럼 떨어진 컴포넌트만 제거하고, 접시 위 음식과 연결된 부분은 유지한다. |
| `apply_container_blur` | 접시/용기 마스크에서 음식 보호 마스크를 뺀다. 남은 영역에만 OpenCV blur를 적용하고, feather를 사용해 블러 경계가 딱딱하게 보이지 않게 섞는다. |
| `repair_plate_edge` | 접시 마스크의 림 주변과 음식 마스크를 비교해 끊긴 상단 림 후보를 찾는다. 원본 이미지에서 실제 초록 림 색을 샘플링하고, 결손 위치에만 `synthetic_rim_bridge`를 얹어 최종 RGB에서 림이 이어져 보이게 한다. |
| `CameraAngleClassifier` | EfficientNet-B0로 이미지를 `top` 또는 `45`로 분류한다. 신뢰도가 낮으면 설정에 따라 실패로 남기거나 fallback 각도를 사용한다. |
| `build_background_prompt` | 업종, 분위기, 카메라 각도, 합성 모드를 묶어 배경 생성 프롬프트를 만든다. 음식과 로고, 글자, 사람은 만들지 말라는 제한도 함께 넣는다. |
| `FluxBackgroundGenerator` | 설정된 provider를 보고 SANA 또는 다른 생성 모델을 로드한다. 같은 프롬프트로 여러 후보를 만들고 후보 파일을 중간 산출물로 저장한다. |
| `score_background_candidate` | 생성 배경 후보 안에 음식이 생겼는지, 중앙 배치 공간이 비어 있는지, 원본과 색감이 너무 어긋나지 않는지 점수화한다. 점수가 좋은 후보가 최종 배경으로 선택된다. |
| `place_foreground` | 전경 RGBA를 배경 크기에 맞게 조절한다. 카메라 각도와 설정 비율을 참고해 중앙 또는 접시 위치에 배치하고 합성 좌표를 기록한다. |
| `add_contact_shadow` | 전경 alpha를 흐리게 만들어 테이블 위 그림자처럼 배경에 어둡게 섞는다. 접시가 공중에 떠 보이는 느낌을 줄이는 후처리다. |
| `remove_color_spill` | 전경 가장자리의 이전 배경색 번짐을 줄인다. 알파 경계 부근에서 색 오염을 약하게 제거해 새 배경과 더 자연스럽게 붙게 한다. |
| `harmonize_foreground` | 전경의 밝기와 채도를 새 배경에 조금 맞춘다. 원본 음식 색이 과하게 바뀌지 않도록 강하게 보정하지 않고 제한적으로 적용한다. |
| `OpenCLIPSemanticValidator` | 원본 전경과 합성 전경을 OpenCLIP 임베딩으로 바꾼 뒤 유사도를 계산한다. 유사도가 너무 낮으면 음식·접시 의미가 바뀐 것으로 보고 결과 저장을 막는다. |
| `validate_result` | 보정 전후의 밝기, 대비, 흐림 정도를 비교한다. 품질 저하가 설정 한계를 넘으면 결과를 통과시키지 않고 리포트에 실패 이유를 남긴다. |

---

## 6. 입력 데이터

### 원본 이미지

CLI에서는 `--input`으로 사진 한 장을 받는다.

```bash
python -m scripts.run_background_replacement \
  --input data/input/example.jpg \
  --metadata data/input/example_metadata.json \
  --enable-background-generator \
  --detector-profile food_specialized \
  --enable-hq-sam
```

### 메타데이터

메타데이터는 사진과 함께 들어오는 설명이다.

```json
{
  "business_type": "restaurant",
  "desired_mood": "premium and elegant",
  "composition_mode": "preserve_original_plate"
}
```

- `business_type`: 어떤 업종의 배경을 만들지 알려준다.
- `desired_mood`: 따뜻함, 고급스러움, 밝음 등 원하는 분위기를 알려준다.
- `composition_mode`: 접시를 보존할지, 음식만 분리할지 결정한다.

Colab에서는 사용자가 사진 한 장을 올리고 `business_type`과 `desired_mood`를 직접 고를 수 있게 만든 이유가 여기에 있다. 카페 사진만 시험하는 것이 아니라 식당, 베이커리, 주점 등 다른 업종도 같은 파이프라인으로 시험하기 위해서다.

---

## 7. 단계별 데이터 흐름

### 1단계: 사진 읽기와 기본 검사

사진을 읽고 처리하기 좋은 크기로 줄인다. 너무 어둡거나 흐린지, 밝은 부분이 하얗게 날아갔는지도 기록한다.

출력 예:

```text
resized_image
input_quality_metrics
```

### 2단계: 음식과 접시 위치 찾기

GroundingDINO가 먼저 음식, 접시, 그릇 후보 박스를 찾는다. 부족한 경우 일반 YOLO 탐지가 보완한다.

출력 예:

```text
food_boxes
container_boxes
detection_report
```

### 3단계: SAM2 기본 마스크 만들기

SAM2가 박스를 보고 음식과 접시의 실제 모양을 마스크로 만든다.

```text
박스: "이 근처를 살펴봐"
SAM2: "이 픽셀들이 실제 물체야"
```

주요 디버그 파일:

```text
data/masks/{이름}_sam_structural_mask.png
data/masks/{이름}_food_sam_mask.png
```

### 4단계: HQ-SAM으로 빠진 곳만 보완하기

HQ-SAM을 전체 마스크 교체용으로 사용하지 않는다. SAM2 경계 근처이면서 탐지 박스 안에 있는 작은 결손만 후보로 추가한다.

이 방식을 `patch_missing`이라고 부른다.

```text
SAM2 마스크
  + 경계 근처에서 HQ-SAM이 찾은 작은 결손
  = 보완된 마스크
```

이렇게 제한한 이유는 HQ-SAM이 접시 밖의 수저나 배경까지 전경으로 넓혀 잡는 일을 줄이기 위해서다.

### 5단계: 접시 모양 완성하기

`PlateMaskService`가 조각난 구조 마스크에서 접시의 큰 윤곽을 찾고 내부 구멍을 메운다.

중요한 점은 **모델이 접시의 가려진 색과 무늬를 새로 그리는 것이 아니라, 접시가 존재해야 하는 영역을 마스크로 정리한다는 것**이다.

출력:

```text
data/masks/{이름}_plate_mask.png
```

### 6단계: 접시 알파를 별도로 보존하기

완성된 접시 마스크를 `plate_alpha`로 만든다.

```text
food_sam_alpha = 음식과 구조를 위한 알파
plate_alpha = 접시 전체를 지키기 위한 알파
final_alpha = 두 알파 중 더 큰 값
```

접시 알파를 마지막에 다시 합치는 이유는 중간 제거와 블러 과정에서 접시 일부가 투명해지는 것을 막기 위해서다.

출력:

```text
data/masks/{이름}_plate_alpha.png
data/masks/{이름}_sam_alpha.png
```

### 7단계: 수저, 컵, 불필요한 물체 지우기

일반 YOLO 제거 탐지가 포크, 칼, 수저, 컵, 그릇을 찾는다.

그 다음 접시와 음식 보호 마스크를 빼서 `safe_removal_mask`를 만든다.

```text
removal_mask
  - 보호해야 하는 음식과 접시
  = safe_removal_mask
```

Big-LaMA는 `safe_removal_mask` 안쪽만 메운다. 같은 영역은 알파에서도 제거해, 사진에서는 지웠지만 알파에 흔적이 남는 문제를 막는다.

### 8단계: 떨어진 전경 조각 제거하기

수저 탐지가 실패하더라도 접시와 멀리 떨어진 작은 전경 조각이 있으면 연결 요소 분석으로 찾는다.

접시 또는 음식과 연결되지 않은 조각만 제거하기 때문에, 접시 위 음식이 잘못 지워지는 위험을 줄인다.

출력:

```text
data/masks/{이름}_detached_foreground_mask.png
```

### 9단계: 접시와 용기 블러

블러 기능은 설정으로 켜고 끌 수 있다.

```yaml
preserved_container_blur:
  enabled: true
```

처리 순서는 다음과 같다.

```text
접시 마스크
  - 음식 전용 보호 마스크
  = 블러를 적용할 접시 부분
```

음식 보호 마스크로 접시까지 포함한 넓은 마스크를 사용하면 블러 마스크가 전부 사라질 수 있다. 그래서 음식만 나타내는 마스크를 보호 입력으로 사용해야 한다.

출력:

```text
data/masks/{이름}_container_blur_mask.png
```

### 10단계: 접시 테두리 보정

오전 9시 35분 기준에서 가장 최근에 강화된 부분이다.

문제는 접시 마스크 면적이 부족한 것만이 아니었다. 접시 위쪽의 초록색 림이 최종 RGB 이미지에 충분히 그려지지 않아 끊겨 보였다.

그래서 다음 방법을 사용한다.

1. 원본 접시 림에서 채도가 높은 실제 색을 찾는다.
2. 접시 마스크와 타원 모양을 이용해 끊긴 상단 림 위치를 계산한다.
3. 그 결손 위치에만 원본 림 색을 사용한 브리지를 그린다.
4. 경계를 작은 커널로 부드럽게 섞는다.

핵심 설정:

```yaml
plate_edge_repair:
  enabled: true
  synthetic_rim_bridge_enabled: true
  synthetic_rim_bridge_extra_width: 3
  synthetic_rim_bridge_opacity: 0.98
  synthetic_rim_bridge_feather_kernel: 3
  synthetic_rim_color_saturation_min: 45
```

이 기능은 HQ-SAM과 역할이 다르다.

- HQ-SAM: 어디까지가 물체인지 마스크를 보완한다.
- 림 브리지: 최종 사진에서 끊긴 림 색을 실제로 보완한다.

### 11단계: 전경 RGBA 만들기

정리된 RGB 이미지와 최종 알파를 합쳐 투명 배경 전경을 만든다.

```text
RGB + alpha = foreground_rgba.png
```

### 12단계: 촬영 각도와 배경 프롬프트 만들기

EfficientNet-B0가 위에서 찍은 사진인지 45도 사진인지 분류한다.

`build_background_prompt`는 다음 정보를 합친다.

```text
business_type
+ desired_mood
+ camera_angle
+ composition_mode
= SANA용 배경 프롬프트
```

프롬프트를 지나치게 짧게 줄였을 때 이상한 글자와 물체가 늘어난 실험이 있었으므로, 오전 9시 35분 기준에서는 원래의 상세 프롬프트 구조를 유지한다.

### 13단계: SANA로 배경 후보 만들기

SANA는 한 장만 만들지 않고 여러 후보를 만든다.

좋은 후보는 다음 조건을 만족해야 한다.

- 음식이 놓일 중앙 또는 지정 영역이 비어 있다.
- 배경 안에 가짜 음식이나 접시가 생기지 않았다.
- 촬영 각도가 원본과 어울린다.
- 업종과 분위기가 메타데이터와 맞는다.

### 14단계: 전경 배치와 자연스러운 합성

음식과 접시 RGBA를 새 배경에 놓는다. 촬영 각도에 따라 크기와 위치가 달라진다.

그 뒤 다음 작업을 한다.

- 접촉 그림자 추가
- 가장자리의 이전 배경색 제거
- 밝기와 채도 조화
- 접시가 화면 밖으로 잘리지 않는지 검사

### 15단계: 최종 검사

OpenCLIP은 원본 전경과 합성 전경의 의미 유사도를 검사한다.

규칙 기반 검사는 다음을 확인한다.

- 음식과 접시가 너무 크거나 작지 않은가
- 배치할 자리에 다른 물체가 없는가
- 배경이 너무 밝거나 어둡지 않은가
- 접시와 음식이 캔버스 밖으로 잘리지 않았는가

검사에 실패하면 정상 결과로 저장하지 않고 거절 이미지와 이유를 남긴다.

---

## 8. 현재 모드 설명

### `preserve_original_plate`

오전 9시 35분의 기본 모드다.

```text
원본 음식 보존
+ 원본 접시 보존
+ 불필요한 주변 물체 제거
+ 새 배경 생성
```

이 모드에서는 `plate_alpha`를 마지막에 다시 합쳐 접시가 사라지지 않도록 한다.

### `generated_plate`

음식만 남기고 원본 접시를 제거한 뒤, 생성 배경에 있는 새 접시 위에 음식을 놓는 모드다.

이 모드는 오전 9시 35분 기준의 중심 운영 경로가 아니다. 음식만 정확히 분리하는 마스크가 부족하면 원본 접시나 수저가 함께 남을 수 있으므로 더 엄격한 보호와 검사가 필요하다.

---

## 9. 현재 사용하는 모델과 사용하지 않는 모델

### 사용하는 모델

```text
GroundingDINO
일반 YOLO 탐지
SAM2
HQ-SAM
Big-LaMA
EfficientNet-B0
SANA 1.6B
OpenCLIP
```

### 준비되어 있지만 사용하지 않는 모델

```text
BiRefNet
```

사용하지 않는 이유:

- `matting.enabled: false`
- 접시 림과 음식 가장자리가 너무 부드러워질 위험
- Colab RAM과 GPU 메모리 부담
- 현재는 SAM2, HQ-SAM, 별도 접시 알파 보존으로 필요한 역할을 수행

---

## 10. 결과 파일 읽는 법

먼저 저장 위치를 두 가지로 나눠서 봐야 한다.

| 구분 | 위치 | 의미 |
| --- | --- | --- |
| 파이프라인 원본 산출물 | `data/output`, `data/intermediate`, `data/masks`, `data/reports` | `BackgroundReplacementPipeline`이 직접 저장하는 기본 위치다. `configs/pipeline.yaml`의 `paths` 값과 일치한다. |
| Colab 실험 보관본 | `data/experiments/background_replacement/{실행시각}` | `01_colab_background_replacement.ipynb`가 실행 후 중요한 산출물을 한 폴더에 복사해 모아두는 위치다. 다운로드해서 보는 결과는 보통 이쪽이다. |

즉, 아래의 `data/output/...`, `data/masks/...` 경로는 **원본 저장 위치**다. Colab에서 실행했다면 같은 파일들이 `data/experiments/background_replacement/{실행시각}/` 아래에 파일명만 유지된 채 복사되어 있을 수 있다.

### 최종 결과

```text
data/output/{이름}_background_replaced.jpg
```

### 중간 전경

```text
data/intermediate/{이름}_foreground_rgba.png
```

### 중요한 마스크

```text
data/masks/{이름}_sam_structural_mask.png
data/masks/{이름}_food_sam_mask.png
data/masks/{이름}_food_active_mask.png
data/masks/{이름}_plate_mask.png
data/masks/{이름}_plate_alpha.png
data/masks/{이름}_sam_alpha.png
data/masks/{이름}_safe_removal_mask.png
data/masks/{이름}_detached_foreground_mask.png
data/masks/{이름}_container_blur_mask.png
data/masks/{이름}_plate_edge_repair_mask.png
```

### 실행 리포트

```text
data/reports/{이름}_background_replacement_report.json
```

Colab 실험 보관 폴더에서는 보통 다음처럼 복사본을 확인한다.

```text
data/experiments/background_replacement/{실행시각}/{이름}_background_replaced.jpg
data/experiments/background_replacement/{실행시각}/{이름}_foreground_rgba.png
data/experiments/background_replacement/{실행시각}/{이름}_background_replacement_report.json
data/experiments/background_replacement/{실행시각}/{이름}_plate_edge_repair_mask.png
data/experiments/background_replacement/{실행시각}/experiment_manifest.json
```

`experiment_manifest.json`에는 어떤 원본 산출물을 어떤 이름으로 복사했는지 `saved_files`로 기록된다. Colab에서 결과를 확인할 때는 이 manifest를 먼저 보면 빠르다.

중요한 확인 항목:

```json
{
  "stages": {
    "step_2b_hq_sam_segmentation": {
      "status": "completed",
      "selection_mode": "patch_missing"
    },
    "step_3_plate_preservation": {
      "used_in_final_alpha": true
    },
    "step_5_safe_lama_removal": {
      "status": "completed"
    },
    "step_5d_plate_edge_repair": {
      "synthetic_rim_bridge_pixels": 1,
      "synthetic_rim_color_sample_count": 1
    }
  }
}
```

- 실제 리포트에서 단계별 값은 최상위가 아니라 `stages` 안에 들어 있다.
- `synthetic_rim_bridge_pixels`가 0보다 커야 실제 브리지가 적용된 것이다.
- `synthetic_rim_color_sample_count`가 충분해야 원본 접시 림 색을 제대로 읽은 것이다.
- 값이 있다고 해서 눈으로 완벽하다는 뜻은 아니다. 최종 이미지와 보정 마스크를 함께 봐야 한다.

---

## 11. 네이버 채널에서의 연결

사용자가 네이버 채널을 선택하면 상위 백엔드 서비스가 다음 정보를 이미지 보정 파이프라인에 전달해야 한다.

```text
입력 이미지 경로
business_type
desired_mood
composition_mode
선택적 camera_angle
```

그 뒤 `run_background_replacement.py` 또는 같은 파이프라인 호출 코드가 설정을 읽고 `BackgroundReplacementPipeline.run()`을 실행한다.

쉽게 말하면 네이버 채널 선택은 **이미지 보정 반장에게 일을 시작하라는 신호**이고, `pipeline.yaml`은 **각 작업자를 켜거나 끄는 스위치판**이다.

---

## 12. 핵심 요약

오전 9시 35분 기준 파이프라인은 다음 생각으로 만들어져 있다.

1. 탐지 모델이 음식과 접시의 대략적인 위치를 찾는다.
2. SAM2가 기본 마스크를 만든다.
3. HQ-SAM은 빠진 경계만 조심스럽게 보완한다.
4. `PlateMaskService`와 `plate_alpha`가 원본 접시 전체를 보호한다.
5. 수저와 컵은 탐지한 뒤 Big-LaMA로 지운다.
6. 접시와 떨어진 작은 전경 조각도 별도로 제거한다.
7. 접시 블러는 음식 전용 보호 마스크를 사용한다.
8. 끊어진 상단 림은 원본 고채도 림 색으로 강제 브리지한다.
9. SANA가 업종과 분위기에 맞는 빈 배경 후보를 만든다.
10. OpenCLIP과 규칙 검사가 최종 결과를 확인한다.

이 문서에서 가장 중요한 구분은 다음과 같다.

```text
모델 = 보고, 찾고, 자르고, 채우고, 생성하고, 비교하는 인공지능
서비스 = 여러 모델과 마스크를 올바른 순서로 움직이는 프로그램
```
