# BrandMate Ad Content Studio

This is an additive frontend for the copy + image model integration. It does not modify the original `apps/web` files.

Run the extension API from `apps/api`:

```powershell
uvicorn app.extensions.ad_content.main:app --reload
```

Run this frontend from `apps/web-ad-content`:

```powershell
python -m http.server 5501
```

Open `http://localhost:5501`.
