# Naver Blog Pipeline Improvements

## Goal

Naver Blog is not an ad-image generation channel. Its goal is to turn uploaded photos into a complete SEO-aware blog post with recommended photo order, thumbnail selection, section placement, and copy-ready body text.

## Current Problems And Fixes

### 1. Image Generation Pipeline Remained

Problem: Naver Blog still produced image-generation artifacts such as `visual_brief`, `product_visualization`, and `image_prompt`.

Cause: The Instagram pipeline was reused and only the channel value changed.

Fix: Naver Blog skips image generation, product visualization, image prompt normalization, and image validation. Uploaded photos are used directly.

### 2. Blog Copy Looked Like Ad Copy

Problem: Output was too shallow, often limited to intro, representative menu, and visit guide.

Cause: The model was still prompted like an ad copywriter.

Fix: Naver Blog now uses a dedicated SEO blog editor prompt. The blog purpose determines the article structure.

### 3. Uploaded Photos Were Underused

Problem: Multiple uploaded photos were not fully reflected in the article.

Cause: Photos were described individually without a complete article flow.

Fix: Vision analysis now returns richer photo metadata, and the blog prompt asks the model to assign roles to as many uploaded photos as possible.

### 4. Photo Order Was Not Recommended Well

Problem: Photo order often followed upload order.

Cause: The pipeline did not explicitly ask for relationship-based ordering.

Fix: Vision analysis now asks for `recommended_order` and `ordering_reason`. The blog prompt requires order based on thumbnail, store intro, representative menu, additional menu, drinks/desserts, and closing flow.

### 5. Thumbnail Recommendation Was Too Abstract

Problem: Thumbnail reasons were generic.

Cause: The prompt did not define selection criteria.

Fix: Thumbnail reasoning now considers product size, focus, color, click potential, and subject recognizability.

### 6. SEO Was Weak

Problem: SEO keywords were mostly used only in the title.

Cause: There was no placement rule for keywords.

Fix: SEO keywords are distributed across the title, first paragraph, middle section, closing paragraph, and hashtags.

### 7. Vision Analysis Was Too Thin

Problem: Vision output only included rough type, key element, position, and thumbnail score.

Cause: The analysis was optimized for a short note, not blog composition.

Fix: Vision output now asks for photo metadata:

```json
{
  "photo_type": "",
  "main_subject": "",
  "camera_angle": "",
  "photo_quality": "",
  "recommended_section": "",
  "thumbnail_score": 5,
  "thumbnail_reason": "",
  "recommended_caption": "",
  "seo_keywords": []
}
```

### 8. No Intermediate Planning Step

Problem: The pipeline moved directly from Vision to LLM writing.

Cause: Photo metadata was not treated as a planning layer.

Fix: The practical flow is now:

```text
Photo upload
↓
Vision analysis
↓
Photo metadata JSON
↓
Photo role classification
↓
Thumbnail recommendation
↓
Photo order recommendation
↓
Blog structure generation
↓
SEO title generation
↓
Body with photo placement
↓
Complete Naver Blog post
```

### 9. Blog Purpose Was Not Strong Enough

Problem: Store intro, new menu, event, and review-style outputs looked too similar.

Cause: Blog purpose was passed as input but did not strongly control the structure.

Fix: The prompt now uses purpose-specific structures:

- Store intro: intro, store atmosphere, representative menu, price, location, closing
- Representative menu: hero photo, taste and texture, price, use case, visit guide
- New menu: intro, new menu, flavor, price, pairing, event, closing
- Event: event summary, featured product, participation method, period/condition, CTA
- Review style: visit motivation, exterior, interior, ordered menu, honest review, revisit intent
- Brand story: philosophy, making process, space, representative menu, closing

## Final Direction

Naver Blog should be an AI content editor for small businesses:

> Upload several photos, and AI analyzes them, recommends the best order and thumbnail, then creates an SEO-aware Naver Blog post with photo placements.

