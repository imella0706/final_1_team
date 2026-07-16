@echo off
chcp 65001

echo ============================================
echo AIHub Food Ad RAG Pipeline: Step 11 to Final
echo ============================================

cd /d C:\aihub-food-ad-rag

echo.
echo [0] Activate virtual environment
call .venv\Scripts\activate

echo.
echo [1] Check Step 10 output
if exist data\metadata\tagged_metadata.parquet (
    echo [OK] Found data\metadata\tagged_metadata.parquet
    set INPUT_METADATA=data\metadata\tagged_metadata.parquet
) else (
    echo [WARN] data\metadata\tagged_metadata.parquet not found.
    echo [WARN] Fallback to data\metadata\deduplicated_metadata.parquet
    set INPUT_METADATA=data\metadata\deduplicated_metadata.parquet
)

if not exist %INPUT_METADATA% (
    echo.
    echo [ERROR] Input metadata not found: %INPUT_METADATA%
    echo [ERROR] Run step 9 or step 10 first.
    pause
    exit /b 1
)

echo.
echo [INFO] Using input metadata:
echo %INPUT_METADATA%

echo.
echo [2] Install Step 11 libraries
pip install torch torchvision open-clip-torch

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install Step 11 libraries.
    pause
    exit /b 1
)

echo.
echo [3] Check Step 11 libraries
python -c "import torch, torchvision, open_clip; print('step 11 libs ok'); print('torch:', torch.__version__); print('cuda:', torch.cuda.is_available())"

if errorlevel 1 (
    echo.
    echo [ERROR] Step 11 library check failed.
    pause
    exit /b 1
)

echo.
echo [4] Run Step 11 - CLIP Embedding
python src\07_clip_embedding.py --input %INPUT_METADATA% --device cpu --batch-size 4

if errorlevel 1 (
    echo.
    echo [ERROR] Step 11 failed.
    pause
    exit /b 1
)

echo.
echo [5] Verify Step 11 outputs
if not exist data\embeddings\image_embeddings.npy (
    echo [ERROR] data\embeddings\image_embeddings.npy not found.
    pause
    exit /b 1
)

if not exist data\embeddings\embedding_metadata.parquet (
    echo [ERROR] data\embeddings\embedding_metadata.parquet not found.
    pause
    exit /b 1
)

python -c "import numpy as np, pandas as pd; emb=np.load('data/embeddings/image_embeddings.npy'); meta=pd.read_parquet('data/embeddings/embedding_metadata.parquet'); print('embeddings:', emb.shape); print('metadata:', meta.shape); print('same count:', emb.shape[0] == len(meta))"

if errorlevel 1 (
    echo.
    echo [ERROR] Step 11 verification failed.
    pause
    exit /b 1
)

echo.
echo [6] Install Step 12 and 13 libraries
pip install faiss-cpu pandas numpy pyarrow pyyaml tqdm pillow

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to install Step 12/13 libraries.
    pause
    exit /b 1
)

echo.
echo [7] Check FAISS
python -c "import faiss; print('faiss ok')"

if errorlevel 1 (
    echo.
    echo [ERROR] FAISS library check failed.
    pause
    exit /b 1
)

echo.
echo [8] Run Step 12 - Build FAISS
python src\08_build_faiss.py

if errorlevel 1 (
    echo.
    echo [ERROR] Step 12 failed.
    pause
    exit /b 1
)

echo.
echo [9] Verify Step 12 outputs
if not exist data\embeddings\faiss.index (
    echo [ERROR] data\embeddings\faiss.index not found.
    pause
    exit /b 1
)

if not exist data\embeddings\faiss_mapping.csv (
    echo [ERROR] data\embeddings\faiss_mapping.csv not found.
    pause
    exit /b 1
)

python -c "import faiss, numpy as np, pandas as pd; index=faiss.read_index('data/embeddings/faiss.index'); emb=np.load('data/embeddings/image_embeddings.npy').astype('float32'); faiss.normalize_L2(emb); D,I=index.search(emb[:1],5); meta=pd.read_csv('data/embeddings/faiss_mapping.csv'); print('scores:',D); print('indices:',I); print(meta.iloc[I[0]][['original_food_name','business_category','product_group','image_path']].to_string())"

if errorlevel 1 (
    echo.
    echo [ERROR] Step 12 verification failed.
    pause
    exit /b 1
)

echo.
echo [10] Run Step 13 - Make Final DB 5GB
python src\09_make_final_db.py --versions 5gb

if errorlevel 1 (
    echo.
    echo [ERROR] Step 13 failed.
    pause
    exit /b 1
)

echo.
echo [11] Verify Step 13 outputs
if not exist data\final_db\5gb\metadata.parquet (
    echo [ERROR] data\final_db\5gb\metadata.parquet not found.
    pause
    exit /b 1
)

if not exist data\final_db\5gb\prompt_metadata.parquet (
    echo [ERROR] data\final_db\5gb\prompt_metadata.parquet not found.
    pause
    exit /b 1
)

if not exist data\final_db\5gb\embeddings.npy (
    echo [ERROR] data\final_db\5gb\embeddings.npy not found.
    pause
    exit /b 1
)

if not exist data\final_db\5gb\faiss.index (
    echo [ERROR] data\final_db\5gb\faiss.index not found.
    pause
    exit /b 1
)

if not exist data\final_db\5gb\mapping.csv (
    echo [ERROR] data\final_db\5gb\mapping.csv not found.
    pause
    exit /b 1
)

if not exist data\final_db\5gb\summary.json (
    echo [ERROR] data\final_db\5gb\summary.json not found.
    pause
    exit /b 1
)

echo.
echo [12] Final DB summary
type data\final_db\5gb\summary.json

echo.
echo [13] Final DB FAISS search test
python -c "import faiss, numpy as np, pandas as pd; idx=faiss.read_index('data/final_db/5gb/faiss.index'); emb=np.load('data/final_db/5gb/embeddings.npy').astype('float32'); D,I=idx.search(emb[:1],5); m=pd.read_csv('data/final_db/5gb/mapping.csv'); print('scores:',D); print('indices:',I); print(m.iloc[I[0]][['original_food_name','business_category','product_group','final_image_path']].to_string())"

if errorlevel 1 (
    echo.
    echo [ERROR] Final DB search test failed.
    pause
    exit /b 1
)

echo.
echo ============================================
echo Step 11 to Final completed successfully.
echo ============================================

pause

# run_step11_to_final.bat
