# Dataset

## 사용 데이터

AI Hub `비전영역, 음식이미지 및 정보소개 텍스트 데이터`의 Validation 데이터를 사용한다.

입력 데이터:

```text
Validation/01.원천데이터/VS.zip
Validation/02.라벨링데이터/VL.zip
```

프로젝트 내 배치 위치:

```text
data/raw/images/
data/raw/annotations/
```

## 파싱 결과

| 항목 | 값 |
|---|---:|
| JSON 파일 수 | 11,582 |
| 이미지 파일 수 | 11,582 |
| 파싱 레코드 수 | 11,582 |
| 유효 JSON 수 | 11,582 |
| 이미지 매칭 성공 | 11,582 |
| 누락 이미지 | 0 |
| 음식명 추출 성공 | 11,582 |
| 고유 음식명 수 | 643 |
| 고유 Food Code 수 | 69 |
| 전체 이미지 용량 | 약 43.74GB |
| 평균 이미지 용량 | 약 3.87MB |
| 평균 이미지 너비 | 약 3002px |
| 평균 이미지 높이 | 약 2955px |

## 카테고리 매핑 결과

| business_category | 개수 |
|---|---:|
| restaurant | 7,234 |
| cafe | 1,306 |
| pub | 1,150 |
| bakery | 1,090 |
| dessert | 802 |

매핑 상태:

| 상태 | 개수 |
|---|---:|
| matched_by_manual_rule | 10,968 |
| fallback_default | 604 |
| matched_by_keyword | 10 |

Fallback 비율은 약 5.21%다.

## 품질 필터링 결과

| 항목 | 값 |
|---|---:|
| 입력 이미지 | 11,582 |
| 품질 통과 | 7,733 |
| 품질 제외 | 3,849 |
| 품질 통과율 | 약 66.77% |
| 평균 Blur Score | 약 234.52 |
| 중앙 Quality Score | 100 |

## 중복 제거 결과

| 항목 | 값 |
|---|---:|
| 입력 이미지 | 7,733 |
| 중복 제거 후 | 7,351 |
| 제거 이미지 | 382 |
| 제거율 | 약 4.94% |

## 캡션 태깅 결과

| 항목 | 값 |
|---|---:|
| 입력 이미지 | 7,351 |
| 캡션 성공 | 7,351 |
| 캡션 실패 | 0 |
| 성공률 | 100% |

## 임베딩 결과

| 항목 | 값 |
|---|---:|
| 임베딩 입력 | 7,351 |
| 임베딩 성공 | 7,351 |
| 임베딩 shape | 7,351 x 512 |
| 모델 | ViT-B-32 / openai |
| device | cpu |

## 최종 DB 결과

### processed\aihub_food_image_text\v1\food_description_data DB

```text
data/final_db/processed\aihub_food_image_text\v1\food_description_data/
```

| 항목 | 값 |
|---|---:|
| 이미지 수 | 952 |
| 실제 이미지 용량 | 약 4.998GB |
| 고유 음식 수 | 88 |
| 임베딩 shape | 952 x 512 |

### processed\aihub_food_image_text\v1\food_description_data v2 Diverse DB

```text
data/final_db/processed\aihub_food_image_text\v2\food_description_data/
```

| 항목 | 값 |
|---|---:|
| 이미지 수 | 1,036 |
| 실제 이미지 용량 | 약 4.441GB |
| 고유 음식 수 | 541 |
| 정위 이미지 | 522 |
| 측면 이미지 | 514 |
| 정위/측면 모두 확보된 음식 | 495 |
| Bounding Box 40~70% 선택 비율 | 약 72.3% |
| 임베딩 shape | 1,036 x 512 |

## 최종 관리 산출물

`src/15_export_final_db_assets.py` 실행 후 각 완성 DB 폴더에는 다음 파일이 추가된다.

```text
db_management_inventory.csv
llm_prompt_payloads.json
```

| 파일 | 목적 |
|---|---|
| `db_management_inventory.csv` | 전체 DB 이미지, 음식명, 업종, 상품군, 품질/대표성 Feature를 사람이 검수하기 위한 관리 파일 |
| `llm_prompt_payloads.json` | 광고 프롬프트 생성/RAG context에 전달하기 위한 JSON payload |

전체 DB 버전 정보는 루트 summary에서 관리한다.

```text
data/final_db/final_db_summary.json
```

## 데이터셋 한계

- AI Hub 데이터는 광고 카피 데이터가 아니다.
- 이미지 중심 데이터라 실제 매장 프로모션 문구, 고객 반응 데이터는 없다.
- BLIP 캡션은 보조 정보이므로 오류 가능성이 있다.
- 기존 processed\aihub_food_image_text\v1\food_description_data DB는 음식 다양성이 낮아, 다양성 기반 v2 DB가 추가되었다.

## Reproducibility

The v2 generation path scripts `01`~`08` and `10`~`15` call the shared seed utility.

```text
src/utils/reproducibility.py
DEFAULT_RANDOM_SEED = 42
```

`processed\aihub_food_image_text\v2\food_description_data` does not directly reuse the final baseline `processed\aihub_food_image_text\v1\food_description_data` DB. It uses the base/v1 processed candidate pool and embedding/FAISS artifacts produced by `01`~`08`.
