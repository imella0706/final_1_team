# EDA Policy

## 목적

이미지 처리 전에 JSON 메타데이터를 분석하여 사용할 수 있는 데이터 구조와 카테고리 분포를 확인합니다.

## 확인 항목

- 이미지 수
- JSON 수
- 이미지와 JSON 매칭 여부
- 원본 대분류 분포
- 원본 중분류 분포
- 원본 소분류 분포
- 음식명 분포
- 누락값
- 이미지 확장자
- 이미지 크기
- 파일 경로 오류

## 카테고리 EDA

서비스 카테고리 설계를 위해 다음 항목을 확인합니다.

```text
original_food_name별 이미지 수
business_category 매핑 가능 여부
product_group 매핑 가능 여부
미매핑 음식명 목록
중복 메뉴명 목록
카테고리별 데이터 불균형
```

## 산출물
outputs/reports/eda_raw/
outputs/reports/category_mapping/
기준

##
이미지를 먼저 학습하지 않고, 메타데이터 분석을 통해 카테고리 매핑 가능성과 데이터 사용 범위를 먼저 결정합니다.