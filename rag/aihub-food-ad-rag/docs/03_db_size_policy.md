# DB Size Policy

## 최종 DB 크기

| 버전 | 목표 용량 |
|---|---:|
| 5gb | 5GB |
| 10gb | 10GB |
| 20gb | 20GB |

## 샘플링 기준

최종 DB는 아래 기준으로 구성합니다.

1. business_category 균형
2. product_group 다양성
3. 원본 세부 카테고리 다양성
4. 이미지 품질 점수
5. 중복도 낮은 이미지
6. 캡션 품질
7. 광고 프롬프트 활용 가능성

## business_category 균형 기준

최종 DB는 아래 5개 업종이 포함되도록 구성합니다.

```text
cafe
bakery
dessert
restaurant
pub
```
## product_group 다양성 기준

각 업종 내부에서 하나의 상품군에 데이터가 과도하게 몰리지 않도록 합니다.

예시:

cafe: coffee만 과도하게 많아지지 않도록 tea, ade_juice, smoothie도 포함
restaurant: korean_food만 과도하게 많아지지 않도록 chinese_food, japanese_food, western_food 등 포함
pub: alcohol만 포함하지 않고 fried_side, grilled_side, seafood_side, korean_pub_food도 포함

## 주의사항

목표 용량은 정확히 일치하지 않을 수 있습니다.

configs/db_size_policy.yaml의 size_tolerance_mb 기준으로 허용 오차를 둡니다.

## v2 diverse DB Policy

`5gb_v2_diverse` is not built with the baseline business_category balancing policy. The v2 DB prioritizes:

1. maximize unique food types
2. select one front and one side representative per food when possible
3. prefer Bounding Box ratio 40~70%
4. prefer high center score
5. prefer high Blur Score
6. prefer high resolution

Therefore, `category_balanced` is false for `5gb_v2_diverse`, and restaurant remains the largest category.
