# RAG Usage

## 목적

음식 이미지 Retrieval 결과를 광고 프롬프트 생성에 활용합니다.

## 사용 흐름

```text
사용자 업종 선택
→ 사용자 메뉴 입력
→ business_category 확인
→ product_group 추론
→ FAISS 검색
→ 유사 음식 이미지 Top-K 반환
→ 이미지 태그/캡션/카테고리 조회
→ 광고 이미지 생성 프롬프트 보강
```

## Prompt RAG Examples

### Example 1. Cafe

#### User Input

```text
Business Category : cafe
Product Name      : 카페라떼
```

#### Retrieval Condition

```text
business_category = cafe
product_group     = coffee
product_name      = 카페라떼
```

#### Prompt Enhancement

```text
latte art
warm cafe table
soft natural light
cream foam
commercial cafe photography
```

---

### Example 2. Dessert

#### User Input

```text
Business Category : dessert
Product Name      : 수제 딸기 티라미수
```

#### Retrieval Condition

```text
business_category = dessert
product_group     = cake
product_name      = 수제 딸기 티라미수
```

#### Prompt Enhancement

```text
fresh strawberry
cream texture
dessert plate
soft natural light
premium dessert photography
```

---

### Example 3. Restaurant

#### User Input

```text
Business Category : restaurant
Product Name      : 매운 닭갈비
```

#### Retrieval Condition

```text
business_category = restaurant
product_group     = meat_grill
product_name      = 닭갈비
```

#### Prompt Enhancement

```text
spicy Korean chicken stir-fry
hot plate
steam
red sauce
restaurant table
appetizing commercial food photography
```

---

### Example 4. Pub

#### User Input

```text
Business Category : pub
Product Name      : 하이볼과 감자튀김
```

#### Retrieval Condition

```text
business_category = pub
product_group     = alcohol + fried_side
product_name      = 하이볼, 감자튀김
```

#### Prompt Enhancement

```text
highball glass
crispy french fries
evening pub mood
warm ambient light
casual drinking table
commercial pub food photography
```

---

## Prompt RAG Workflow

```text
User Input
      │
      ▼
Business Category Selection
      │
      ▼
Product Name Input
      │
      ▼
Business Category / Product Group Mapping
      │
      ▼
FAISS Similarity Search
      │
      ▼
Retrieve Similar Images
+
Prompt Metadata
      │
      ▼
Prompt Enhancement
      │
      ▼
LLM Advertisement Copy Generation
      │
      ▼
Image Generation Prompt
```