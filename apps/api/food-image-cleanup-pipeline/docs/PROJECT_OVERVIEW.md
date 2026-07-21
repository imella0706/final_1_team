# 음식 이미지 배경 교체 프로젝트 개요

## 1. 왜 만들었는가

네이버 블로그용 음식 사진은 원본 배경, 부스러기, 식기, 조명 상태 때문에 광고 이미지로 바로 쓰기 어려울 수 있다. 이 프로젝트는 음식과 음식을 담은 용기는 원본 픽셀로 보존하고, 불필요한 배경을 제거한 뒤 업종과 음식 분위기에 맞는 새 배경을 생성·합성하기 위해 만들었다.

가장 중요한 원칙은 생성 모델이 음식 자체를 다시 그리지 않도록 하는 것이다. 음식의 모양, 색, 소스, 접시 무늬가 바뀌면 실제 메뉴와 광고 이미지가 달라질 수 있기 때문이다.

## 2. 무엇을 입력받는가

필수 입력은 다음 두 가지다.

- 음식 사진: JPG, JPEG, PNG, WEBP 형식의 원본 사진
- 배경 메타데이터 JSON: 업종, 음식 범주, 배치 위치, 광원 방향, 필요하면 고정 배경 프롬프트

예시 JSON:

```json
{
  "business_type": "cafe",
  "food_category": "dessert",
  "foreground_position": "center_lower",
  "light_direction": "left",
  "background_prompt": "Photorealistic premium modern Korean cafe interior, empty table surface, no food, no plate, no people, no text"
}
```

네이버 연동에서는 업로드 이미지와 사용자 JSON의 업종값을 받아 `pub`, `restaurant`, `cafe` 계열의 배경 프롬프트를 선택한다.

## 3. 무엇을 출력하는가

다음 파일을 생성한다.

- 최종 이미지: `data/output/<입력명>_background_replaced.jpg`
- 투명 전경 이미지: `data/intermediate/<입력명>_foreground.png`
- 알파 매트: `data/masks/<입력명>_foreground_alpha.png`
- 생성 배경: `data/intermediate/<입력명>_generated_background.jpg`
- 실행 보고서: `data/reports/<입력명>_background_replacement_report.json`

최종 이미지는 새 배경 위에 원본 음식·용기 전경을 합성하고 그림자와 경계 보정을 적용한 결과다.

## 4. 전체 파이프라인은 어떻게 되는가

```text
입력 음식 사진
  → 음식·용기 후보 탐지
  → SAM 구조 마스크
  → BiRefNet 알파 매트
  → 음식 보호 영역 생성
  → 전경 주변 이물질만 LaMa로 제거
  → 원본 음식·용기 RGBA 추출
  → 업종별 FLUX 빈 배경 생성
  → 원래 위치·크기에 맞춘 전경 배치
  → 접지 그림자 생성
  → 경계 색 번짐·밝기 조화
  → 알파 합성
  → OpenCLIP 전경 보존 검증
```

FLUX는 음식이 없는 배경만 만들고, 음식·용기 전경은 원본 이미지에서 가져온다.

## 5. 각 모델은 왜 사용했는가

| 모델 | 역할 | 선택 이유 |
|---|---|---|
| YOLO11n | 음식·용기·포크·나이프·스푼 탐지 | 가볍고 빠르며 SAM에 사각형 프롬프트를 제공할 수 있다. |
| SAM 2.1 Tiny | 음식·용기 구조 마스크 | 전경 범위를 구조적으로 분리한다. |
| BiRefNet HR | 연속 알파 매트 | 접시 곡선, 유리, 얇은 장식물 등 경계를 더 자연스럽게 만든다. |
| Big-LaMa | 전경 주변 이물질 제거 | 음식 경계 근처의 부스러기·식기·작은 소품을 제한적으로 제거한다. |
| FLUX.1 Schnell | 빈 광고 배경 생성 | 빠른 단계 수로 업종별 음식 광고 배경 후보를 생성한다. |
| OpenCLIP ViT-B-32 | 전경 의미 보존 검증 | 배경이 아니라 음식·용기 영역이 원본과 지나치게 달라지지 않았는지 확인한다. |

## 6. 실제로 어떻게 실행하는가

로컬 실행:

```powershell
cd C:\dev\final_1_team\apps\api\food-image-cleanup-pipeline
python -m pip install -r requirements-local.txt
python -m scripts.download_models --all
python -m scripts.run_background_replacement --input data/input/example.jpg --metadata data/input/example_metadata.json --enable-matting --enable-background-generator
```

코랩 실행은 `notebooks/01_colab_background_replacement.ipynb`를 GPU 런타임에서 위에서 아래로 실행한다. 자세한 내용은 `LOCAL_SETUP.md`, `COLAB_SETUP.md`를 참고한다.

## 7. 현재 어디까지 완성되었는가

- 네이버 블로그 업로드 이미지에서 내부 파이프라인을 호출하는 연동 어댑터를 추가했다.
- 업종별 배경 프롬프트 선택을 구현했다.
- 음식·용기 분리, 알파 매트, 배경 생성, 그림자, 합성, 전경 OpenCLIP 검증 코드를 구현했다.
- 로컬·코랩 요구사항 파일과 코랩 검증 노트북을 정리했다.
- 코드 문법과 YAML 설정 로딩은 확인했다.

## 8. 어떤 문제가 남아 있는가

- 실제 코랩 GPU에서 전체 모델을 내려받아 끝까지 실행한 실측 검증은 아직 필요하다.
- YOLO11n의 기본 COCO 클래스에는 많은 한식과 복합 음식이 없어 음식 탐지가 실패할 수 있다.
- FLUX.1 Schnell과 BiRefNet은 GPU 메모리와 다운로드 시간이 많이 필요하다.
- Big-LaMa, BiRefNet, FLUX를 한 실행에 함께 올리면 코랩 GPU 메모리 부족이 발생할 수 있다.
- IC-Light 직접 추론은 음식 디테일 변경 위험 때문에 아직 연결하지 않았다.

## 9. 앞으로 무엇을 개선해야 하는가

1. 한식·디저트·배달 음식 중심의 단일 `food` 탐지 모델을 학습하거나 파인튜닝한다.
2. 실제 네이버 업로드 사진으로 전경 분리·배경 생성·합성 품질을 평가하는 테스트셋을 만든다.
3. 모델을 단계별로 메모리에서 해제하거나 CPU 오프로딩해 코랩 메모리 사용량을 줄인다.
4. 여러 FLUX 시드 후보를 생성하고 OpenCLIP·사람 평가로 가장 자연스러운 배경을 선택한다.
5. IC-Light V1을 연결할 경우 결과 전체를 쓰지 않고 저주파 조명 성분만 원본 전경에 반영한다.
6. 네이버 API 응답에 단계별 상태, 실패 원인, 결과 보고서 경로를 함께 기록한다.
