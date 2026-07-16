from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def safe_read_json(json_path: Path) -> Optional[Dict[str, Any]]:
    """
    JSON 파일을 안전하게 읽는다.
    """
    try:
        with json_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except UnicodeDecodeError:
        try:
            with json_path.open("r", encoding="cp949") as f:
                return json.load(f)
        except Exception:
            return None
    except Exception:
        return None


def flatten_dict(
    data: Dict[str, Any],
    parent_key: str = "",
    sep: str = ".",
) -> Dict[str, Any]:
    """
    중첩 JSON을 평탄화한다.

    예:
    {"data": {"image_info": {"file_name": "abc.jpg"}}}
    ->
    {"data.image_info.file_name": "abc.jpg"}
    """
    items: Dict[str, Any] = {}

    for key, value in data.items():
        new_key = f"{parent_key}{sep}{key}" if parent_key else str(key)

        if isinstance(value, dict):
            items.update(flatten_dict(value, new_key, sep=sep))
        elif isinstance(value, list):
            items[new_key] = json.dumps(value, ensure_ascii=False)
        else:
            items[new_key] = value

    return items


def find_first_value(
    flat_data: Dict[str, Any], candidates: Iterable[str]
) -> Optional[Any]:
    """
    후보 키 중 실제 존재하는 첫 번째 값을 반환한다.
    """
    for key in candidates:
        value = flat_data.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def normalize_text(value: Any) -> str:
    """
    텍스트 값을 안전하게 문자열로 변환한다.
    """
    if value is None:
        return ""
    return str(value).strip()


def extract_food_name_from_file_name(file_name: Any) -> str:
    """
    AI Hub 파일명에서 음식명을 추출한다.

    예:
    A_13_A13001_가자미구이_02_09.jpg
    ->
    가자미구이
    """
    if file_name is None:
        return ""

    stem = Path(str(file_name)).stem
    parts = stem.split("_")

    if len(parts) >= 4:
        return parts[3].strip()

    return ""


def looks_like_code(value: Any) -> bool:
    """
    FC03S02, VG05, CS01 같은 코드값인지 확인한다.
    """
    if value is None:
        return False

    text = str(value).strip()

    patterns = [
        r"FC\d+S\d+",
        r"VG\d+",
        r"CS\d+",
        r"SI\d+",
        r"RC\d+",
        r"[A-Z]{1,5}\d{1,5}[A-Z]?\d*",
    ]

    return any(re.fullmatch(pattern, text) for pattern in patterns)


def clean_food_name(value: Any) -> str:
    """
    음식명 후보를 정리한다.
    코드처럼 보이면 빈 문자열로 처리한다.
    """
    text = normalize_text(value)

    if looks_like_code(text):
        return ""

    return text


def collect_image_files(image_dir: Path) -> Dict[str, Path]:
    """
    이미지 파일을 stem 기준으로 인덱싱한다.

    예:
    A_13_A13001_가자미구이_02_09.jpg
    ->
    {"A_13_A13001_가자미구이_02_09": Path(...)}
    """
    image_map: Dict[str, Path] = {}

    if not image_dir.exists():
        return image_map

    for path in image_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            image_map[path.stem] = path

    return image_map


def guess_image_path(
    json_path: Path,
    flat_data: Dict[str, Any],
    image_map: Dict[str, Path],
) -> Optional[str]:
    """
    JSON 내부 file_name 또는 JSON 파일명 기준으로 이미지 경로를 찾는다.
    """
    image_name = find_first_value(
        flat_data,
        [
            "data.image_info.file_name",
            "image_info.file_name",
            "image",
            "image_name",
            "imageName",
            "file_name",
            "fileName",
            "filename",
            "img_name",
            "imgName",
            "image.filename",
            "image.file_name",
            "images.file_name",
            "info.image_name",
            "meta.image_name",
        ],
    )

    if image_name:
        image_stem = Path(str(image_name)).stem
        if image_stem in image_map:
            return str(image_map[image_stem])

    if json_path.stem in image_map:
        return str(image_map[json_path.stem])

    return None


def list_json_files(annotation_dir: Path) -> List[Path]:
    """
    annotation 폴더 하위의 JSON 파일 전체를 반환한다.
    """
    if not annotation_dir.exists():
        return []
    return sorted(annotation_dir.rglob("*.json"))


def extract_metadata_record(
    json_path: Path,
    image_map: Dict[str, Path],
    raw_root: Path,
) -> Dict[str, Any]:
    """
    하나의 JSON 파일에서 표준 메타데이터 레코드를 생성한다.
    현재 AI Hub Validation JSON 구조에 맞춰 작성했다.

    실제 JSON 예:
    {
      "data": {
        "image_info": {
          "file_name": "A_13_A13001_가자미구이_02_09.jpg",
          "width": 2992,
          "height": 2992
        },
        "food_type": {
          "fc": "FC03S02",
          "vg": "VG05",
          "cs": "CS01",
          "si": ["SI01"],
          "loc": "RC10"
        }
      }
    }
    """
    raw_json = safe_read_json(json_path)

    if raw_json is None:
        return {
            "annotation_path": str(json_path),
            "image_path": None,
            "json_valid": False,
            "parse_error": True,
            "source_file_name": "",
            "original_major_category": "",
            "original_middle_category": "",
            "original_sub_category": "",
            "original_food_name": "",
            "product_name": "",
            "food_code": "",
        }

    flat = flatten_dict(raw_json)

    source_file_name = find_first_value(
        flat,
        [
            "data.image_info.file_name",
            "image_info.file_name",
            "file_name",
            "fileName",
            "filename",
        ],
    )

    image_path = guess_image_path(
        json_path=json_path,
        flat_data=flat,
        image_map=image_map,
    )

    food_name_from_file = extract_food_name_from_file_name(source_file_name)

    original_food_name = clean_food_name(food_name_from_file)

    # 혹시 파일명에서 음식명을 못 뽑는 경우를 대비한 fallback
    if not original_food_name:
        fallback_food_name = find_first_value(
            flat,
            [
                "food_name",
                "foodName",
                "menu_name",
                "menuName",
                "dish_name",
                "dishName",
                "data.food_name",
                "data.menu_name",
                "음식명",
                "메뉴명",
            ],
        )
        original_food_name = clean_food_name(fallback_food_name)

    product_name = original_food_name

    food_code = find_first_value(flat, ["data.food_type.fc", "food_type.fc"])
    view_group_code = find_first_value(flat, ["data.food_type.vg", "food_type.vg"])
    cooking_style_code = find_first_value(flat, ["data.food_type.cs", "food_type.cs"])
    situation_code = find_first_value(flat, ["data.food_type.si", "food_type.si"])
    location_code = find_first_value(flat, ["data.food_type.loc", "food_type.loc"])

    record = {
        "annotation_path": str(json_path),
        "image_path": image_path,
        "json_valid": True,
        "parse_error": False,
        "json_file_name": json_path.name,
        "json_stem": json_path.stem,
        "source_file_name": normalize_text(source_file_name),
        # 현재 JSON에는 한글 대/중/소분류가 직접 없으므로 우선 빈 값으로 둔다.
        # 이후 03_build_category_groups.py에서 food_code/product_name 기준으로 service category를 만든다.
        "original_major_category": "",
        "original_middle_category": "",
        "original_sub_category": "",
        "original_food_name": original_food_name,
        "product_name": product_name,
        "food_code": normalize_text(food_code),
        "view_group_code": normalize_text(view_group_code),
        "cooking_style_code": normalize_text(cooking_style_code),
        "situation_code": normalize_text(situation_code),
        "location_code": normalize_text(location_code),
        "image_width": find_first_value(
            flat, ["data.image_info.width", "image_info.width"]
        ),
        "image_height": find_first_value(
            flat, ["data.image_info.height", "image_info.height"]
        ),
        "image_weight": find_first_value(
            flat, ["data.image_info.weight", "image_info.weight"]
        ),
        "serving_weight": find_first_value(
            flat, ["data.image_info.s_weight", "image_info.s_weight"]
        ),
        "nutrition_g": find_first_value(flat, ["data.nutrition.g", "nutrition.g"]),
        "nutrition_energy": find_first_value(flat, ["data.nutrition.e", "nutrition.e"]),
        "nutrition_cal": find_first_value(
            flat, ["data.nutrition.cal", "nutrition.cal"]
        ),
        "nutrition_sugar": find_first_value(
            flat, ["data.nutrition.sug", "nutrition.sug"]
        ),
        "nutrition_fat": find_first_value(
            flat, ["data.nutrition.fat", "nutrition.fat"]
        ),
        "nutrition_protein": find_first_value(
            flat, ["data.nutrition.pro", "nutrition.pro"]
        ),
        "nutrition_sodium": find_first_value(
            flat, ["data.nutrition.na", "nutrition.na"]
        ),
        "nutrition_cholesterol": find_first_value(
            flat, ["data.nutrition.chol", "nutrition.chol"]
        ),
        "restaurant_name": normalize_text(
            find_first_value(flat, ["data.restaurant.name", "restaurant.name"])
        ),
        "restaurant_addr": normalize_text(
            find_first_value(flat, ["data.restaurant.addr", "restaurant.addr"])
        ),
        "raw_json_key_count": len(flat),
    }

    if image_path:
        try:
            image_path_obj = Path(image_path)
            record["image_file_name"] = image_path_obj.name
            record["image_extension"] = image_path_obj.suffix.lower()
            record["image_size_bytes"] = os.path.getsize(image_path_obj)
        except OSError:
            record["image_file_name"] = ""
            record["image_extension"] = ""
            record["image_size_bytes"] = None
    else:
        record["image_file_name"] = ""
        record["image_extension"] = ""
        record["image_size_bytes"] = None

    try:
        record["relative_annotation_path"] = str(json_path.relative_to(raw_root))
    except ValueError:
        record["relative_annotation_path"] = str(json_path)

    if image_path:
        try:
            record["relative_image_path"] = str(Path(image_path).relative_to(raw_root))
        except ValueError:
            record["relative_image_path"] = image_path
    else:
        record["relative_image_path"] = ""

    return record
