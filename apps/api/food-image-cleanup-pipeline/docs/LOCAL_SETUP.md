# 로컬 실행 안내

이 폴더는 네이버 블로그 음식 사진의 배경 제거·생성·합성 전용 파이프라인이다.

```powershell
cd C:\dev\final_1_team\apps\api
pip install -e .[image]
pip install -r food-image-cleanup-pipeline\requirements-local.txt
cd food-image-cleanup-pipeline
python -m scripts.download_models --all
python -m scripts.run_background_replacement --input data/input/example.jpg --metadata data/input/example_metadata.json --enable-matting --enable-background-generator
```
