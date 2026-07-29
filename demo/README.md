# Trend to ad demo

저장소에 이미 있는 Careet, Gogumafarm, YouTube, NAVER CSV를 읽어 다음 산출물을 만드는 로컬 데모다.

```text
로컬 CSV/JSON 스냅샷
→ 공통 TrendCard 정규화
→ 키워드·최신성·출처·신호 기반 검색
→ 10초 광고 스토리보드와 영상 모델용 프롬프트
→ 세로형 MP4 애니매틱과 브라우저용 GIF
```

외부 API와 API 키는 사용하지 않는다. MP4는 실제 생성형 영상이 아니라 검색부터 결과물 생성까지 연결됐음을 보여주는 모션그래픽 애니매틱이다.

## 실행

프로젝트 루트에서 실행한다.

```powershell
python -m pip install -r demo\requirements.txt
python -m demo.trend_ad `
  --brief "니가 좋아 밈을 활용한 여름 카페 신메뉴 숏폼 광고" `
  --product "제로 콜드브루" `
  --audience "20대 직장인" `
  --cta "오늘 한 잔 만나보기"
```

현재 개발 환경에는 필요한 패키지가 이미 설치돼 있어 첫 번째 명령 없이 실행할 수 있다.

특정 밈을 우선하려면 다음처럼 지정한다.

```powershell
python -m demo.trend_ad --meme "Wow Okay" --product "Fortuna"
```

영상 라이브러리 없이 검색과 프롬프트만 확인할 수도 있다.

```powershell
python -m demo.trend_ad --prompt-only --output-dir demo\output-prompt
```

## 산출물

기본 위치는 `demo/output/`이다.

- `report.html`: 영상, 선택 근거, 후보 순위와 프롬프트를 한 화면에 표시
- `retrieval.json`: 상위 후보와 점수·일치 키워드
- `storyboard.json`: 영상 API에 전달할 수 있는 구조화된 4장면 계획
- `prompt.txt`: 영상 생성 모델용 프롬프트
- `animatic.mp4`: 540×960, 24fps, 10초 무음 애니매틱
- `preview.gif`: 브라우저에서 바로 보이는 저해상도 미리보기

```powershell
Start-Process demo\output\report.html
```

## 실제 영상 모델 연결 지점

`storyboard.json`의 `generation_prompt`, `scenes`, `trend`를 호스팅 영상 API 작업 요청으로 보내고 완료된 MP4를 `animatic.mp4` 대신 저장하면 된다. 외부 플랫폼 URL은 발견 근거일 뿐 생성 모델 입력으로 사용하지 않는다. 실제 생성에는 자사 또는 AI 입력과 상업적 2차 이용이 허가된 레퍼런스만 사용해야 한다.

## 테스트

```powershell
python -m unittest discover -s demo\tests -v
```

한글 폰트 자동 탐색이 실패하는 환경에서는 `TREND_DEMO_FONT`에 TTF/TTC 경로를 지정한다.

