# AIHub Food Image Text v1 Description

> Current dataset name: `aihub_food_image_text`
> Current artifact name: `food_description_data`
> Previous working name: `aihub_reference_db_v1`
> This Markdown file was generated from the PDF for team onboarding and dataset documentation.

## Page 1

DB
다운로드 : https://drive.google.com/drive/folders/15HpRANZnnwoNpET6zd75pVGBLAVThdjF?usp=drive_link
validation데이터로 했음.
최종 final_db/5gb 는 검색 API와 광고 프롬프트 RAG에서 바로 사용할 수 있도록 패키징한 완성형 Retrieval DB입니다.
구조는 보통 아래와 같습니다.
data/final_db/5gb/
├── images/
├── metadata.parquet
├── prompt_metadata.parquet
├── embeddings.npy
├── faiss.index
├── mapping.csv
└── summary.json
1.
images/
?
무엇인가
최종 DB에 포함된 실제 음식 이미지 파일들이 들어 있는 폴더입니다.
예시:
data/final_db/5gb/images/
├── img_00000000.jpg
├── img_00000001.jpg
├── img_00000002.jpg
└── ...
만든 의도
원본 data/raw/images/ 에는 전체 이미지가 들어 있습니다.
하지만 최종 DB에서는 5GB 버전에 포함된 이미지들만 따로 복사해서 관리합니다.
즉, images/ 는 최종 검색 DB에 실제로 포함된 이미지 원본 저장소입니다.
?
왜 필요한가
검색 결과에서 final_image_path 가 반환되었을 때, 실제 이미지를 보여주려면 이 폴더가 필요합니다.
예를 들어 API 검색 결과가 다음처럼 나온다고 하면:
{
"final_image_path": "data/final_db/5gb/images/img_00000123.jpg",
"original_food_name": "딸기케이크"
}
프론트엔드나 노트북에서는 이 경로의 이미지를 열어서 사용자에게 보여줄 수 있습니다.
활용 방식
검색 결과 이미지 미리보기
광고 이미지 생성 모델의 reference image 후보
노트북에서 검색 품질 시각화
프론트엔드에서 유사 음식 이미지 표시
DB 1

## Page 2

2.
metadata.parquet
?
무엇인가
최종 DB에 포함된 이미지들의 전체 메타데이터입니다.
여기에는 원천 데이터에서 파싱한 정보, 카테고리 매핑 정보, 품질 점수, 중복 제거 결과, 캡션 정보 등이 포함됩니다.
예상 컬럼 예시:
final_image_id
final_image_path
final_image_file_name
image_path
annotation_path
original_food_name
product_name
food_code
business_category
product_group
quality_score
blur_score
duplicate_status
phash
caption
caption_status
prompt_keywords
caption_lighting
caption_composition
caption_camera_angle
ad_use_case
embedding_id
embedding_array_index
만든 의도
metadata.parquet 는 최종 DB의 마스터 테이블입니다.
즉, 최종 DB에 들어간 각 이미지가 다음 정보를 갖도록 만든 것입니다.
이 이미지는 어떤 음식인가?
어떤 업종에 속하는가?
어떤 상품군인가?
품질은 괜찮은가?
중복 제거 후 살아남은 대표 이미지인가?
캡션은 무엇인가?
어떤 임베딩 번호와 연결되는가?
실제 이미지 파일은 어디 있는가?
Parquet ?
왜 인가
CSV보다 Parquet을 사용한 이유는 다음과 같습니다.
대용량 메타데이터 처리에 효율적
컬럼 타입 유지
읽기/쓰기 속도 우수
pandas에서 바로 사용 가능
활용 방식
Python에서 읽기:
import pandas as pd
df = pd.read_parquet("data/final_db/5gb/metadata.parquet")
print(df.head())
DB 2

## Page 3

활용 예:
최종 DB 전체 품질 점검
카테고리별 이미지 수 확인
음식명별 검색 가능 데이터 확인
품질 점수 기준 추가 필터링
데이터 분석 및 보고서 작성
예를 들어 업종별 개수를 확인할 수 있습니다.
df["business_category"].value_counts()
3.
prompt_metadata.parquet
?
무엇인가
광고 프롬프트 생성에 바로 쓰기 좋도록 만든 경량 메타데이터 테이블입니다.
metadata.parquet 가 전체 정보를 담는 마스터 테이블이라면, prompt_metadata.parquet 는 광고 생성에 필요한 핵심 정보만 모은 테이블입니
다.
예상 컬럼 예시:
final_image_id
final_image_path
business_category
product_group
product_name
original_food_name
food_code
caption
prompt_keywords
text_for_embedding
retrieval_text
ad_prompt_hint
만든 의도
광고 문구 생성이나 이미지 생성 프롬프트에 전체 메타데이터가 다 필요한 것은 아닙니다.
프롬프트 생성에는 보통 아래 정보만 필요합니다.
업종
상품군
상품명
유사 음식명
이미지 설명
시각 키워드
참고 이미지 경로
검색용 텍스트
그래서 prompt_metadata.parquet 는 LLM 또는 이미지 생성 모델에 넘길 context 구성용 데이터로 만든 것입니다.
metadata.parquet 와 차이
파일 목적 특징
metadata.parquet 전체 메타데이터 보관 컬럼이 많고 분석/검증용
prompt_metadata.parquet 프롬프트 생성용 광고 생성에 필요한 핵심 컬럼 중심
활용 방식
import pandas as pd
DB 3

### Extracted Tables

#### Table 3.1

| 파일 | 목적 | 특징 |
| --- | --- | --- |
| metadata.parquet | 전체 메타데이터 보관 | 컬럼이 많고 분석/검증용 |
| prompt_metadata.parquet | 프롬프트 생성용 | 광고 생성에 필요한 핵심 컬럼 중심 |

## Page 4

prompt_df = pd.read_parquet("data/final_db/5gb/prompt_metadata.parquet")
print(prompt_df[["product_name", "retrieval_text", "ad_prompt_hint"]].head())
광고 생성 프롬프트에 넣는 예:
[Reference]
- 업종: dessert
- 상품군: cake
- 유사 메뉴명: 딸기케이크
- 이미지 설명: a slice of cake on a plate
- 시각 키워드: food photography, dessert, close-up
실제 활용 위치
app/prompt_rag.py 에서 검색 결과를 받아 다음 형태로 변환할 때 사용됩니다.
reference_context
ad_copy_prompt
image_prompt
즉, 이 파일은 RAG 프롬프트 품질을 높이기 위한 파일입니다.
4.
embeddings.npy
?
무엇인가
최종 DB에 포함된 이미지들의 CLIP 이미지 임베딩 배열입니다.
형태는 보통 다음과 같습니다.
(이미지 개수, 임베딩 차원)
예를 들어 현재 로그 기준 최종 DB가 952개 이미지라면:
(952, 512)
일 가능성이 높습니다.
만든 의도
이미지 검색은 파일명이나 음식명만으로는 한계가 있습니다.
예를 들어 “딸기 케이크”라는 텍스트가 없더라도 시각적으로 비슷한 케이크 이미지를 찾고 싶을 수 있습니다.
그래서 각 이미지를 CLIP 모델에 넣어 벡터로 변환했습니다.
음식 이미지
→ CLIP image encoder
→ 512차원 벡터
→ embeddings.npy
?
왜 필요한가
FAISS 검색 인덱스는 내부적으로 벡터를 검색합니다.
embeddings.npy 는 그 검색의 원본 벡터 데이터입니다.
활용 방식
import numpy as np
DB 4

## Page 5

emb = np.load("data/final_db/5gb/embeddings.npy")
print(emb.shape)
활용 예:
FAISS 인덱스 재생성
검색 결과 검증
임베딩 분포 분석
유사 이미지 직접 검색
시각화 차원축소 분석
예를 들어 첫 번째 이미지와 유사한 이미지를 검색할 때 이 벡터를 query로 사용할 수 있습니다.
query = emb[0:1]
5.
faiss.index
?
무엇인가
FAISS로 만든 최종 유사 이미지 검색 인덱스입니다.
embeddings.npy 에 저장된 벡터를 빠르게 검색할 수 있도록 인덱싱한 파일입니다.
만든 의도
이미지 임베딩을 단순히 NumPy 배열로만 가지고 있으면 검색할 때 매번 전체 벡터와 비교해야 합니다.
query vector
→ 전체 embeddings와 비교
→ 유사도 계산
→ top-k 선택
데이터가 많아질수록 비효율적입니다.
FAISS 인덱스는 이 과정을 빠르고 일관되게 수행하기 위해 만든 검색 전용 구조입니다.
활용 방식
import faiss
import numpy as np
index = faiss.read_index("data/final_db/5gb/faiss.index")
emb = np.load("data/final_db/5gb/embeddings.npy").astype("float32")
D, I = index.search(emb[:1], 5)
print(D) # 유사도 점수
print(I) # 검색된 faiss index id
API
에서의 활용
app/retrieval_api.py 가 실행될 때 이 파일을 로드합니다.
faiss.index 로드
→ 사용자의 검색 조건 처리
→ query vector 생성
→ index.search()
→ top-k 결과 반환
즉, faiss.index 는 검색 엔진의 핵심 파일입니다.
DB 5

## Page 6

6.
mapping.csv
?
무엇인가
FAISS 검색 결과의 index id를 실제 이미지와 메타데이터에 연결하는 매핑 파일입니다.
FAISS는 검색 결과로 숫자 ID를 반환합니다.
예:
indices: [[0, 12, 51, 130, 221]]
하지만 숫자만으로는 이게 어떤 이미지인지 알 수 없습니다.
그래서 mapping.csv 가 필요합니다.
예상 컬럼:
faiss_index_id
final_image_id
embedding_id
embedding_array_index
final_image_path
final_image_file_name
image_path
original_food_name
product_name
food_code
business_category
product_group
caption
prompt_keywords
text_for_embedding
만든 의도
mapping.csv 는 다음 연결을 담당합니다.
FAISS 검색 결과 ID
→ 이미지 파일 경로
→ 음식명
→ 업종
→ 상품군
→ 캡션
→ 프롬프트 키워드
활용 예
FAISS 검색 결과가 아래처럼 나왔다고 하면:
I = [[0, 12, 51]]
mapping에서 해당 row를 찾습니다.
import pandas as pd
mapping = pd.read_csv("data/final_db/5gb/mapping.csv")
print(mapping.iloc[[0, 12, 51]])
그러면 실제 결과를 볼 수 있습니다.
0번 → 딸기케이크 이미지
12번 → 초코케이크 이미지
DB 6

## Page 7

51번 → 티라미수 이미지
API
에서의 활용
retrieval_api.py 는 검색 후 mapping.csv 를 조회해서 사용자에게 아래 정보를 반환합니다.
{
"rank": 1,
"score": 0.91,
"faiss_index_id": 12,
"final_image_path": "data/final_db/5gb/images/img_00000012.jpg",
"original_food_name": "딸기케이크",
"business_category": "dessert",
"product_group": "cake",
"caption": "a slice of cake on a plate"
}
즉, mapping.csv 는 검색 결과를 사람이 이해할 수 있는 결과로 바꾸는 연결 테이블입니다.
7.
summary.json
?
무엇인가
최종 DB 생성 결과를 요약한 JSON 파일입니다.
예상 내용:
{
"version_name": "5gb",
"target_size_gb": 5.0,
"actual_image_size_gb": 4.98,
"record_count": 952,
"embedding_shape": [952, 512],
"business_category_count": {
"restaurant": 300,
"dessert": 180,
"cafe": 170,
"bakery": 160,
"pub": 142
},
"product_group_count": {
"korean_food": 120,
"cake": 80,
"seafood_side": 70
}
}
만든 의도
최종 DB가 정상적으로 생성되었는지 빠르게 확인하기 위해 만든 파일입니다.
summary.json 은 일종의 DB 생성 완료 보고서입니다.
확인할 수 있는 것
목표 용량
실제 이미지 용량
최종 포함 이미지 수
임베딩 shape
DB 7


## Page 8

업종별 데이터 분포
상품군별 데이터 분포
생성 파일 경로
활용 방식
CMD에서 확인:
type data\final_db\5gb\summary.json
Python에서 확인:
import json
with open("data/final_db/5gb/summary.json", "r", encoding="utf-8") as f:
summary = json.load(f)
print(summary)
실무적 활용
최종 DB 생성 검수
보고서에 통계 수치 반영
5GB/10GB/20GB 버전 비교
카테고리 편향 여부 확인
API 로드 전 sanity check
전체 파일 간 관계
최종 DB는 각 파일이 따로 존재하지만, 실제로는 아래처럼 연결됩니다.
images/
↑
│ final_image_path
│
mapping.csv
↑
│ faiss_index_id
│
faiss.index
↑
│ vectors
│
embeddings.npy
metadata.parquet
↑
│ final_image_id / embedding_id
│
prompt_metadata.parquet
summary.json
→ 전체 생성 결과 요약
조금 더 서비스 흐름 중심으로 보면 다음과 같습니다.
사용자 검색 요청
↓
retrieval_api.py
↓
faiss.index에서 유사 벡터 검색
↓
mapping.csv로 이미지/음식명/카테고리 조회
↓
metadata.parquet 또는 prompt_metadata.parquet 정보 활용
↓
DB 8

## Page 9

final_image_path로 images/ 이미지 표시
↓
prompt_rag.py에서 광고 프롬프트 context 생성
DB
최종 파일별 요약표
파일/폴더 정체 만든 의도 주요 활용
images/ 최종 포함 이미지 파일 검색 결과 이미지 표시 프론트엔드, 노트북, reference image
metadata.parquet 전체 메타데이터 최종 DB 마스터 테이블 분석, 검증, 품질 확인
prompt_metadata.parquet 프롬프트용 경량 메타데이터 RAG 프롬프트 생성 광고 문구/이미지 프롬프트 구성
embeddings.npy CLIP 이미지 벡터 이미지 유사도 검색 기반 FAISS 검색, 임베딩 분석
faiss.index FAISS 검색 인덱스 빠른 top-k 검색 Retrieval API 핵심
mapping.csv FAISS ID 연결표 검색 결과를 실제 데이터로 변환 API 응답 생성
summary.json 생성 요약 리포트 최종 DB 검수 보고서, 품질 체크, 버전 비교
실무적으로 가장 중요한 파일
운영 관점에서 가장 중요한 파일은 아래 4개입니다.
faiss.index
embeddings.npy
mapping.csv
images/
검색 API가 동작하려면 이 4개가 핵심입니다.
광고 프롬프트 RAG까지 제대로 활용하려면 아래도 중요합니다.
prompt_metadata.parquet
metadata.parquet
검증과 보고서 작성에는 아래가 중요합니다.
summary.json
최종 의미
final_db/5gb 는 단순히 이미지와 메타데이터를 모아둔 폴더가 아닙니다.
이 폴더는 광고 콘텐츠 생성을 위한 검색 가능한 지식 베이스입니다.
즉, 최종 역할은 다음입니다.
음식 이미지 데이터
→ 정제/필터링/중복제거
→ 캡션/키워드 생성
→ CLIP 임베딩
→ FAISS 검색
→ 광고 생성 프롬프트 참고자료 제공
따라서 final_db 는 이후 서비스에서 다음 기능의 기반이 됩니다.
유사 음식 이미지 추천
업종/상품군 기반 이미지 검색
광고 문구 생성용 reference context 제공
이미지 생성 모델용 visual reference 제공
소상공인 광고 콘텐츠 자동 생성 보조
DB 9

### Extracted Tables

#### Table 9.1

| 파일/폴더 | 정체 | 만든 의도 | 주요 활용 |
| --- | --- | --- | --- |
| images/ | 최종 포함 이미지 파일 | 검색 결과 이미지 표시 | 프론트엔드, 노트북, reference image |
| metadata.parquet | 전체 메타데이터 | 최종 DB 마스터 테이블 | 분석, 검증, 품질 확인 |
| prompt_metadata.parquet | 프롬프트용 경량 메타데이터 | RAG 프롬프트 생성 | 광고 문구/이미지 프롬프트 구성 |
| embeddings.npy | CLIP 이미지 벡터 | 이미지 유사도 검색 기반 | FAISS 검색, 임베딩 분석 |
| faiss.index | FAISS 검색 인덱스 | 빠른 top-k 검색 | Retrieval API 핵심 |
| mapping.csv | FAISS ID 연결표 | 검색 결과를 실제 데이터로 변환 | API 응답 생성 |
| summary.json | 생성 요약 리포트 | 최종 DB 검수 | 보고서, 품질 체크, 버전 비교 |

## Page 10

metadata.csv 파일 간소화 표
제외한 컬럼 : image_path, embedding_id, source_row_index
50개의 목록 표로 전환
중복 구간에 다각도로 촬영된 데이터가 포함되어 있습니다
final_image_id original_food_name product_name food_code business_category product_group
0 추어튀김 추어튀김 FC22S02 pub fried_side
1 추어튀김 추어튀김 FC22S02 pub fried_side
2 추어튀김 추어튀김 FC22S02 pub fried_side
3 추어튀김 추어튀김 FC22S02 pub fried_side
4 추어튀김 추어튀김 FC22S02 pub fried_side
5 추어튀김 추어튀김 FC22S02 pub fried_side
6 추어튀김 추어튀김 FC22S02 pub fried_side
7 추어튀김 추어튀김 FC22S02 pub fried_side
8 추어튀김 추어튀김 FC22S02 pub fried_side
9 추어튀김 추어튀김 FC22S02 pub fried_side
10 추어튀김 추어튀김 FC22S02 pub fried_side
11 추어튀김 추어튀김 FC22S02 pub fried_side
12 추어튀김 추어튀김 FC22S02 pub fried_side
13 추어튀김 추어튀김 FC22S02 pub fried_side
14 추어튀김 추어튀김 FC22S02 pub fried_side
15 추어튀김 추어튀김 FC22S02 pub fried_side
16 추어튀김 추어튀김 FC22S02 pub fried_side
17 추어튀김 추어튀김 FC22S02 pub fried_side
18 추어튀김 추어튀김 FC22S02 pub fried_side
19 꽃빵 꽃빵 FC10S01 bakery bread
20 꽃빵 꽃빵 FC10S01 bakery bread
21 꽃빵 꽃빵 FC10S01 bakery bread
22 꽃빵 꽃빵 FC10S01 bakery bread
23 꽃빵 꽃빵 FC10S01 bakery bread
24 꽃빵 꽃빵 FC10S01 bakery bread
25 꽃빵 꽃빵 FC10S01 bakery bread
26 꽃빵 꽃빵 FC10S01 bakery bread
27 꽃빵 꽃빵 FC10S01 bakery bread
28 꽃빵 꽃빵 FC10S01 bakery bread
29 꽃빵 꽃빵 FC10S01 bakery bread
30 꽃빵 꽃빵 FC10S01 bakery bread
31 꽃빵 꽃빵 FC10S01 bakery bread
32 꽃빵 꽃빵 FC10S01 bakery bread
33 꽃빵 꽃빵 FC10S01 bakery bread
34 꽃빵 꽃빵 FC10S01 bakery bread
35 꽃빵 꽃빵 FC10S01 bakery bread
36 꽃빵 꽃빵 FC10S01 bakery bread
37 꽃빵 꽃빵 FC10S01 bakery bread
38 꽃빵 꽃빵 FC10S01 bakery bread
DB 10

### Extracted Tables

#### Table 10.1

| final_image_id | original_food_name | product_name | food_code | business_category | product_group |
| --- | --- | --- | --- | --- | --- |
| 0 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 1 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 2 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 3 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 4 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 5 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 6 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 7 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 8 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 9 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 10 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 11 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 12 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 13 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 14 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 15 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 16 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 17 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 18 | 추어튀김 | 추어튀김 | FC22S02 | pub | fried_side |
| 19 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 20 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 21 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 22 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 23 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 24 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 25 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 26 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 27 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 28 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 29 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 30 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 31 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 32 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 33 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 34 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 35 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 36 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 37 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |
| 38 | 꽃빵 | 꽃빵 | FC10S01 | bakery | bread |

## Page 11

final_image_id original_food_name product_name food_code business_category product_group
39 마라살꼬치 마라살꼬치 FC03S03 pub grilled_side
40 마라살꼬치 마라살꼬치 FC03S03 pub grilled_side
41 마라살꼬치 마라살꼬치 FC03S03 pub grilled_side
42 마라살꼬치 마라살꼬치 FC03S03 pub grilled_side
43 마라살꼬치 마라살꼬치 FC03S03 pub grilled_side
44 마라살꼬치 마라살꼬치 FC03S03 pub grilled_side
45 마라살꼬치 마라살꼬치 FC03S03 pub grilled_side
46 마라살꼬치 마라살꼬치 FC03S03 pub grilled_side
47 마라살꼬치 마라살꼬치 FC03S03 pub grilled_side
48 마라살꼬치 마라살꼬치 FC03S03 pub grilled_side
49 마라살꼬치 마라살꼬치 FC03S03 pub grilled_side
mapping.csv 파일 간소화 표
제외한 컬럼 : image_path, prompt_keywords, text_for_embedding
faiss_index_id final_image_id embedding_id embedding_array_index final_image_path final_im
0 0 404 404 data\final_db\5gb\images\img_00000000.jpg img_000
1 1 405 405 data\final_db\5gb\images\img_00000001.jpg img_000
2 2 406 406 data\final_db\5gb\images\img_00000002.jpg img_000
3 3 407 407 data\final_db\5gb\images\img_00000003.jpg img_000
4 4 408 408 data\final_db\5gb\images\img_00000004.jpg img_000
5 5 409 409 data\final_db\5gb\images\img_00000005.jpg img_000
6 6 410 410 data\final_db\5gb\images\img_00000006.jpg img_000
7 7 411 411 data\final_db\5gb\images\img_00000007.jpg img_000
8 8 412 412 data\final_db\5gb\images\img_00000008.jpg img_000
9 9 413 413 data\final_db\5gb\images\img_00000009.jpg img_000
10 10 414 414 data\final_db\5gb\images\img_00000010.jpg img_000
11 11 415 415 data\final_db\5gb\images\img_00000011.jpg img_000
DB 11

### Extracted Tables

#### Table 11.1

| final_image_id | original_food_name | product_name | food_code | business_category | product_group |
| --- | --- | --- | --- | --- | --- |
| 39 | 마라살꼬치 | 마라살꼬치 | FC03S03 | pub | grilled_side |
| 40 | 마라살꼬치 | 마라살꼬치 | FC03S03 | pub | grilled_side |
| 41 | 마라살꼬치 | 마라살꼬치 | FC03S03 | pub | grilled_side |
| 42 | 마라살꼬치 | 마라살꼬치 | FC03S03 | pub | grilled_side |
| 43 | 마라살꼬치 | 마라살꼬치 | FC03S03 | pub | grilled_side |
| 44 | 마라살꼬치 | 마라살꼬치 | FC03S03 | pub | grilled_side |
| 45 | 마라살꼬치 | 마라살꼬치 | FC03S03 | pub | grilled_side |
| 46 | 마라살꼬치 | 마라살꼬치 | FC03S03 | pub | grilled_side |
| 47 | 마라살꼬치 | 마라살꼬치 | FC03S03 | pub | grilled_side |
| 48 | 마라살꼬치 | 마라살꼬치 | FC03S03 | pub | grilled_side |
| 49 | 마라살꼬치 | 마라살꼬치 | FC03S03 | pub | grilled_side |

#### Table 11.2

| faiss_index_id | final_image_id | embedding_id | embedding_array_index | final_image_path | final_im |
| --- | --- | --- | --- | --- | --- |
| 0 | 0 | 404 | 404 | data\final_db\5gb\images\img_00000000.jpg |  |
| 1 | 1 | 405 | 405 | data\final_db\5gb\images\img_00000001.jpg |  |
| 2 | 2 | 406 | 406 | data\final_db\5gb\images\img_00000002.jpg |  |
| 3 | 3 | 407 | 407 | data\final_db\5gb\images\img_00000003.jpg |  |
| 4 | 4 | 408 | 408 | data\final_db\5gb\images\img_00000004.jpg |  |
| 5 | 5 | 409 | 409 | data\final_db\5gb\images\img_00000005.jpg |  |
| 6 | 6 | 410 | 410 | data\final_db\5gb\images\img_00000006.jpg |  |
| 7 | 7 | 411 | 411 | data\final_db\5gb\images\img_00000007.jpg |  |
| 8 | 8 | 412 | 412 | data\final_db\5gb\images\img_00000008.jpg |  |
| 9 | 9 | 413 | 413 | data\final_db\5gb\images\img_00000009.jpg |  |
| 10 | 10 | 414 | 414 | data\final_db\5gb\images\img_00000010.jpg |  |
| 11 | 11 | 415 | 415 | data\final_db\5gb\images\img_00000011.jpg |  |

## Page 12

faiss_index_id final_image_id embedding_id embedding_array_index final_image_path final_im
12 12 416 416 data\final_db\5gb\images\img_00000012.jpg img_000
13 13 417 417 data\final_db\5gb\images\img_00000013.jpg img_000
14 14 418 418 data\final_db\5gb\images\img_00000014.jpg img_000
15 15 419 419 data\final_db\5gb\images\img_00000015.jpg img_000
16 16 420 420 data\final_db\5gb\images\img_00000016.jpg img_000
17 17 421 421 data\final_db\5gb\images\img_00000017.jpg img_000
18 18 422 422 data\final_db\5gb\images\img_00000018.jpg img_000
19 19 767 767 data\final_db\5gb\images\img_00000019.jpg img_000
20 20 768 768 data\final_db\5gb\images\img_00000020.jpg img_000
21 21 769 769 data\final_db\5gb\images\img_00000021.jpg img_000
22 22 770 770 data\final_db\5gb\images\img_00000022.jpg img_000
23 23 771 771 data\final_db\5gb\images\img_00000023.jpg img_000
24 24 772 772 data\final_db\5gb\images\img_00000024.jpg img_000
25 25 773 773 data\final_db\5gb\images\img_00000025.jpg img_000
26 26 774 774 data\final_db\5gb\images\img_00000026.jpg img_000
27 27 775 775 data\final_db\5gb\images\img_00000027.jpg img_000
28 28 776 776 data\final_db\5gb\images\img_00000028.jpg img_000
29 29 777 777 data\final_db\5gb\images\img_00000029.jpg img_000
30 30 778 778 data\final_db\5gb\images\img_00000030.jpg img_000
31 31 779 779 data\final_db\5gb\images\img_00000031.jpg img_000
DB 12

### Extracted Tables

#### Table 12.1

| faiss_index_id | final_image_id | embedding_id | embedding_array_index | final_image_path | final_im |
| --- | --- | --- | --- | --- | --- |
| 12 | 12 | 416 | 416 | data\final_db\5gb\images\img_00000012.jpg |  |
| 13 | 13 | 417 | 417 | data\final_db\5gb\images\img_00000013.jpg |  |
| 14 | 14 | 418 | 418 | data\final_db\5gb\images\img_00000014.jpg |  |
| 15 | 15 | 419 | 419 | data\final_db\5gb\images\img_00000015.jpg |  |
| 16 | 16 | 420 | 420 | data\final_db\5gb\images\img_00000016.jpg |  |
| 17 | 17 | 421 | 421 | data\final_db\5gb\images\img_00000017.jpg |  |
| 18 | 18 | 422 | 422 | data\final_db\5gb\images\img_00000018.jpg |  |
| 19 | 19 | 767 | 767 | data\final_db\5gb\images\img_00000019.jpg |  |
| 20 | 20 | 768 | 768 | data\final_db\5gb\images\img_00000020.jpg |  |
| 21 | 21 | 769 | 769 | data\final_db\5gb\images\img_00000021.jpg |  |
| 22 | 22 | 770 | 770 | data\final_db\5gb\images\img_00000022.jpg |  |
| 23 | 23 | 771 | 771 | data\final_db\5gb\images\img_00000023.jpg |  |
| 24 | 24 | 772 | 772 | data\final_db\5gb\images\img_00000024.jpg |  |
| 25 | 25 | 773 | 773 | data\final_db\5gb\images\img_00000025.jpg |  |
| 26 | 26 | 774 | 774 | data\final_db\5gb\images\img_00000026.jpg |  |
| 27 | 27 | 775 | 775 | data\final_db\5gb\images\img_00000027.jpg |  |
| 28 | 28 | 776 | 776 | data\final_db\5gb\images\img_00000028.jpg |  |
| 29 | 29 | 777 | 777 | data\final_db\5gb\images\img_00000029.jpg |  |
| 30 | 30 | 778 | 778 | data\final_db\5gb\images\img_00000030.jpg |  |
| 31 | 31 | 779 | 779 | data\final_db\5gb\images\img_00000031.jpg |  |

## Page 13

faiss_index_id final_image_id embedding_id embedding_array_index final_image_path final_im
32 32 780 780 data\final_db\5gb\images\img_00000032.jpg img_000
33 33 781 781 data\final_db\5gb\images\img_00000033.jpg img_000
34 34 782 782 data\final_db\5gb\images\img_00000034.jpg img_000
35 35 783 783 data\final_db\5gb\images\img_00000035.jpg img_000
36 36 784 784 data\final_db\5gb\images\img_00000036.jpg img_000
37 37 785 785 data\final_db\5gb\images\img_00000037.jpg img_000
38 38 786 786 data\final_db\5gb\images\img_00000038.jpg img_000
39 39 1131 1131 data\final_db\5gb\images\img_00000039.jpg img_000
40 40 1132 1132 data\final_db\5gb\images\img_00000040.jpg img_000
41 41 1133 1133 data\final_db\5gb\images\img_00000041.jpg img_000
42 42 1134 1134 data\final_db\5gb\images\img_00000042.jpg img_000
43 43 1135 1135 data\final_db\5gb\images\img_00000043.jpg img_000
44 44 1136 1136 data\final_db\5gb\images\img_00000044.jpg img_000
45 45 1137 1137 data\final_db\5gb\images\img_00000045.jpg img_000
46 46 1139 1139 data\final_db\5gb\images\img_00000046.jpg img_000
47 47 1140 1140 data\final_db\5gb\images\img_00000047.jpg img_000
48 48 1141 1141 data\final_db\5gb\images\img_00000048.jpg img_000
49 49 1142 1142 data\final_db\5gb\images\img_00000049.jpg img_000
DB 13

### Extracted Tables

#### Table 13.1

| faiss_index_id | final_image_id | embedding_id | embedding_array_index | final_image_path | final_im |
| --- | --- | --- | --- | --- | --- |
| 32 | 32 | 780 | 780 | data\final_db\5gb\images\img_00000032.jpg |  |
| 33 | 33 | 781 | 781 | data\final_db\5gb\images\img_00000033.jpg |  |
| 34 | 34 | 782 | 782 | data\final_db\5gb\images\img_00000034.jpg |  |
| 35 | 35 | 783 | 783 | data\final_db\5gb\images\img_00000035.jpg |  |
| 36 | 36 | 784 | 784 | data\final_db\5gb\images\img_00000036.jpg |  |
| 37 | 37 | 785 | 785 | data\final_db\5gb\images\img_00000037.jpg |  |
| 38 | 38 | 786 | 786 | data\final_db\5gb\images\img_00000038.jpg |  |
| 39 | 39 | 1131 | 1131 | data\final_db\5gb\images\img_00000039.jpg |  |
| 40 | 40 | 1132 | 1132 | data\final_db\5gb\images\img_00000040.jpg |  |
| 41 | 41 | 1133 | 1133 | data\final_db\5gb\images\img_00000041.jpg |  |
| 42 | 42 | 1134 | 1134 | data\final_db\5gb\images\img_00000042.jpg |  |
| 43 | 43 | 1135 | 1135 | data\final_db\5gb\images\img_00000043.jpg |  |
| 44 | 44 | 1136 | 1136 | data\final_db\5gb\images\img_00000044.jpg |  |
| 45 | 45 | 1137 | 1137 | data\final_db\5gb\images\img_00000045.jpg |  |
| 46 | 46 | 1139 | 1139 | data\final_db\5gb\images\img_00000046.jpg |  |
| 47 | 47 | 1140 | 1140 | data\final_db\5gb\images\img_00000047.jpg |  |
| 48 | 48 | 1141 | 1141 | data\final_db\5gb\images\img_00000048.jpg |  |
| 49 | 49 | 1142 | 1142 | data\final_db\5gb\images\img_00000049.jpg |  |

## Page 14

prompt_metadata.csv 파일 간소화 표
제외한 컬럼 : text_for_embedding,retrieval_text,ad_prompt_hint
final_image_id final_image_path business_category product_group product_name original_food
0 data\final_db\5gb\images\img_00000000.jpg pub fried_side 추어튀김 추어튀김
1 data\final_db\5gb\images\img_00000001.jpg pub fried_side 추어튀김 추어튀김
2 data\final_db\5gb\images\img_00000002.jpg pub fried_side 추어튀김 추어튀김
3 data\final_db\5gb\images\img_00000003.jpg pub fried_side 추어튀김 추어튀김
4 data\final_db\5gb\images\img_00000004.jpg pub fried_side 추어튀김 추어튀김
5 data\final_db\5gb\images\img_00000005.jpg pub fried_side 추어튀김 추어튀김
6 data\final_db\5gb\images\img_00000006.jpg pub fried_side 추어튀김 추어튀김
7 data\final_db\5gb\images\img_00000007.jpg pub fried_side 추어튀김 추어튀김
8 data\final_db\5gb\images\img_00000008.jpg pub fried_side 추어튀김 추어튀김
9 data\final_db\5gb\images\img_00000009.jpg pub fried_side 추어튀김 추어튀김
10 data\final_db\5gb\images\img_00000010.jpg pub fried_side 추어튀김 추어튀김
11 data\final_db\5gb\images\img_00000011.jpg pub fried_side 추어튀김 추어튀김
12 data\final_db\5gb\images\img_00000012.jpg pub fried_side 추어튀김 추어튀김
DB 14

### Extracted Tables

#### Table 14.1

| final_image_id | final_image_path | business_category | product_group | product_name | original_food |
| --- | --- | --- | --- | --- | --- |
| 0 | data\final_db\5gb\images\img_00000000.jpg | pub | fried_side | 추어튀김 |  |
| 1 | data\final_db\5gb\images\img_00000001.jpg | pub | fried_side | 추어튀김 |  |
| 2 | data\final_db\5gb\images\img_00000002.jpg | pub | fried_side | 추어튀김 |  |
| 3 | data\final_db\5gb\images\img_00000003.jpg | pub | fried_side | 추어튀김 |  |
| 4 | data\final_db\5gb\images\img_00000004.jpg | pub | fried_side | 추어튀김 |  |
| 5 | data\final_db\5gb\images\img_00000005.jpg | pub | fried_side | 추어튀김 |  |
| 6 | data\final_db\5gb\images\img_00000006.jpg | pub | fried_side | 추어튀김 |  |
| 7 | data\final_db\5gb\images\img_00000007.jpg | pub | fried_side | 추어튀김 |  |
| 8 | data\final_db\5gb\images\img_00000008.jpg | pub | fried_side | 추어튀김 |  |
| 9 | data\final_db\5gb\images\img_00000009.jpg | pub | fried_side | 추어튀김 |  |
| 10 | data\final_db\5gb\images\img_00000010.jpg | pub | fried_side | 추어튀김 |  |
| 11 | data\final_db\5gb\images\img_00000011.jpg | pub | fried_side | 추어튀김 |  |

## Page 15

final_image_id final_image_path business_category product_group product_name original_food
13 data\final_db\5gb\images\img_00000013.jpg pub fried_side 추어튀김 추어튀김
14 data\final_db\5gb\images\img_00000014.jpg pub fried_side 추어튀김 추어튀김
15 data\final_db\5gb\images\img_00000015.jpg pub fried_side 추어튀김 추어튀김
16 data\final_db\5gb\images\img_00000016.jpg pub fried_side 추어튀김 추어튀김
17 data\final_db\5gb\images\img_00000017.jpg pub fried_side 추어튀김 추어튀김
18 data\final_db\5gb\images\img_00000018.jpg pub fried_side 추어튀김 추어튀김
19 data\final_db\5gb\images\img_00000019.jpg bakery bread 꽃빵 꽃빵
20 data\final_db\5gb\images\img_00000020.jpg bakery bread 꽃빵 꽃빵
21 data\final_db\5gb\images\img_00000021.jpg bakery bread 꽃빵 꽃빵
22 data\final_db\5gb\images\img_00000022.jpg bakery bread 꽃빵 꽃빵
23 data\final_db\5gb\images\img_00000023.jpg bakery bread 꽃빵 꽃빵
24 data\final_db\5gb\images\img_00000024.jpg bakery bread 꽃빵 꽃빵
DB 15

### Extracted Tables

#### Table 15.1

| final_image_id | final_image_path | business_category | product_group | product_name | original_food |
| --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |
| 13 | data\final_db\5gb\images\img_00000013.jpg | pub | fried_side | 추어튀김 |  |
| 14 | data\final_db\5gb\images\img_00000014.jpg | pub | fried_side | 추어튀김 |  |
| 15 | data\final_db\5gb\images\img_00000015.jpg | pub | fried_side | 추어튀김 |  |
| 16 | data\final_db\5gb\images\img_00000016.jpg | pub | fried_side | 추어튀김 |  |
| 17 | data\final_db\5gb\images\img_00000017.jpg | pub | fried_side | 추어튀김 |  |
| 18 | data\final_db\5gb\images\img_00000018.jpg | pub | fried_side | 추어튀김 |  |
| 19 | data\final_db\5gb\images\img_00000019.jpg | bakery | bread | 꽃빵 |  |
| 20 | data\final_db\5gb\images\img_00000020.jpg | bakery | bread | 꽃빵 |  |
| 21 | data\final_db\5gb\images\img_00000021.jpg | bakery | bread | 꽃빵 |  |
| 22 | data\final_db\5gb\images\img_00000022.jpg | bakery | bread | 꽃빵 |  |
| 23 | data\final_db\5gb\images\img_00000023.jpg | bakery | bread | 꽃빵 |  |
| 24 | data\final_db\5gb\images\img_00000024.jpg | bakery | bread | 꽃빵 |  |

## Page 16

final_image_id final_image_path business_category product_group product_name original_food
25 data\final_db\5gb\images\img_00000025.jpg bakery bread 꽃빵 꽃빵
26 data\final_db\5gb\images\img_00000026.jpg bakery bread 꽃빵 꽃빵
27 data\final_db\5gb\images\img_00000027.jpg bakery bread 꽃빵 꽃빵
28 data\final_db\5gb\images\img_00000028.jpg bakery bread 꽃빵 꽃빵
29 data\final_db\5gb\images\img_00000029.jpg bakery bread 꽃빵 꽃빵
30 data\final_db\5gb\images\img_00000030.jpg bakery bread 꽃빵 꽃빵
31 data\final_db\5gb\images\img_00000031.jpg bakery bread 꽃빵 꽃빵
32 data\final_db\5gb\images\img_00000032.jpg bakery bread 꽃빵 꽃빵
33 data\final_db\5gb\images\img_00000033.jpg bakery bread 꽃빵 꽃빵
34 data\final_db\5gb\images\img_00000034.jpg bakery bread 꽃빵 꽃빵
35 data\final_db\5gb\images\img_00000035.jpg bakery bread 꽃빵 꽃빵
36 data\final_db\5gb\images\img_00000036.jpg bakery bread 꽃빵 꽃빵
37 data\final_db\5gb\images\img_00000037.jpg bakery bread 꽃빵 꽃빵
DB 16

### Extracted Tables

#### Table 16.1

| final_image_id | final_image_path | business_category | product_group | product_name | original_food |
| --- | --- | --- | --- | --- | --- |
| 25 | data\final_db\5gb\images\img_00000025.jpg | bakery | bread | 꽃빵 |  |
| 26 | data\final_db\5gb\images\img_00000026.jpg | bakery | bread | 꽃빵 |  |
| 27 | data\final_db\5gb\images\img_00000027.jpg | bakery | bread | 꽃빵 |  |
| 28 | data\final_db\5gb\images\img_00000028.jpg | bakery | bread | 꽃빵 |  |
| 29 | data\final_db\5gb\images\img_00000029.jpg | bakery | bread | 꽃빵 |  |
| 30 | data\final_db\5gb\images\img_00000030.jpg | bakery | bread | 꽃빵 |  |
| 31 | data\final_db\5gb\images\img_00000031.jpg | bakery | bread | 꽃빵 |  |
| 32 | data\final_db\5gb\images\img_00000032.jpg | bakery | bread | 꽃빵 |  |
| 33 | data\final_db\5gb\images\img_00000033.jpg | bakery | bread | 꽃빵 |  |
| 34 | data\final_db\5gb\images\img_00000034.jpg | bakery | bread | 꽃빵 |  |
| 35 | data\final_db\5gb\images\img_00000035.jpg | bakery | bread | 꽃빵 |  |
| 36 | data\final_db\5gb\images\img_00000036.jpg | bakery | bread | 꽃빵 |  |
| 37 | data\final_db\5gb\images\img_00000037.jpg | bakery | bread | 꽃빵 |  |

## Page 17

final_image_id final_image_path business_category product_group product_name original_food
38 data\final_db\5gb\images\img_00000038.jpg bakery bread 꽃빵 꽃빵
39 data\final_db\5gb\images\img_00000039.jpg pub grilled_side 마라살꼬치 마라살꼬치
40 data\final_db\5gb\images\img_00000040.jpg pub grilled_side 마라살꼬치 마라살꼬치
41 data\final_db\5gb\images\img_00000041.jpg pub grilled_side 마라살꼬치 마라살꼬치
42 data\final_db\5gb\images\img_00000042.jpg pub grilled_side 마라살꼬치 마라살꼬치
43 data\final_db\5gb\images\img_00000043.jpg pub grilled_side 마라살꼬치 마라살꼬치
44 data\final_db\5gb\images\img_00000044.jpg pub grilled_side 마라살꼬치 마라살꼬치
45 data\final_db\5gb\images\img_00000045.jpg pub grilled_side 마라살꼬치 마라살꼬치
46 data\final_db\5gb\images\img_00000046.jpg pub grilled_side 마라살꼬치 마라살꼬치
47 data\final_db\5gb\images\img_00000047.jpg pub grilled_side 마라살꼬치 마라살꼬치
48 data\final_db\5gb\images\img_00000048.jpg pub grilled_side 마라살꼬치 마라살꼬치
DB 17

### Extracted Tables

#### Table 17.1

| final_image_id | final_image_path | business_category | product_group | product_name | original_food |
| --- | --- | --- | --- | --- | --- |
| 38 | data\final_db\5gb\images\img_00000038.jpg | bakery | bread | 꽃빵 |  |
| 39 | data\final_db\5gb\images\img_00000039.jpg | pub | grilled_side | 마라살꼬치 |  |
| 40 | data\final_db\5gb\images\img_00000040.jpg | pub | grilled_side | 마라살꼬치 |  |
| 41 | data\final_db\5gb\images\img_00000041.jpg | pub | grilled_side | 마라살꼬치 |  |
| 42 | data\final_db\5gb\images\img_00000042.jpg | pub | grilled_side | 마라살꼬치 |  |
| 43 | data\final_db\5gb\images\img_00000043.jpg | pub | grilled_side | 마라살꼬치 |  |
| 44 | data\final_db\5gb\images\img_00000044.jpg | pub | grilled_side | 마라살꼬치 |  |
| 45 | data\final_db\5gb\images\img_00000045.jpg | pub | grilled_side | 마라살꼬치 |  |
| 46 | data\final_db\5gb\images\img_00000046.jpg | pub | grilled_side | 마라살꼬치 |  |
| 47 | data\final_db\5gb\images\img_00000047.jpg | pub | grilled_side | 마라살꼬치 |  |
| 48 | data\final_db\5gb\images\img_00000048.jpg | pub | grilled_side | 마라살꼬치 |  |

## Page 18

final_image_id final_image_path business_category product_group product_name original_food
49 data\final_db\5gb\images\img_00000049.jpg pub grilled_side 마라살꼬치 마라살꼬치
DB 18

### Extracted Tables

#### Table 18.1

| final_image_id | final_image_path | business_category | product_group | product_name | original_food |
| --- | --- | --- | --- | --- | --- |
| 49 | data\final_db\5gb\images\img_00000049.jpg | pub | grilled_side | 마라살꼬치 |  |
