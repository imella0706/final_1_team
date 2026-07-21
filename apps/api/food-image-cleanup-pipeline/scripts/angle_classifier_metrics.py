"""촬영 각도 이미지 분류 학습·평가에서 공유하는 지표 함수."""

from __future__ import annotations

from pathlib import Path


def classification_metrics(confusion: list[list[int]], class_names: list[str]) -> dict[str, object]:
    total = sum(sum(row) for row in confusion)
    correct = sum(confusion[index][index] for index in range(len(class_names)))
    per_class: dict[str, dict[str, float | int]] = {}
    recalls: list[float] = []
    f1_scores: list[float] = []
    for index, name in enumerate(class_names):
        true_positive = confusion[index][index]
        false_positive = sum(confusion[row][index] for row in range(len(class_names)) if row != index)
        false_negative = sum(confusion[index][column] for column in range(len(class_names)) if column != index)
        support = sum(confusion[index])
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[name] = {"precision": precision, "recall": recall, "f1": f1, "support": support}
        recalls.append(recall)
        f1_scores.append(f1)
    return {
        "accuracy": correct / total if total else 0.0,
        "balanced_accuracy": sum(recalls) / len(recalls) if recalls else 0.0,
        "macro_f1": sum(f1_scores) / len(f1_scores) if f1_scores else 0.0,
        "total": total,
        "confusion_matrix": confusion,
        "per_class": per_class,
    }


def save_confusion_matrix_png(confusion: list[list[int]], class_names: list[str], path: Path) -> None:
    """추가 그래프 라이브러리 없이 혼동 행렬 PNG를 저장한다."""

    from PIL import Image, ImageDraw, ImageFont

    cell, margin, header = 120, 28, 150
    size = header + cell * len(class_names) + margin
    canvas = Image.new("RGB", (size, size), "white")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    max_value = max((value for row in confusion for value in row), default=1) or 1
    draw.text((header, 8), "예측 클래스", fill="black", font=font)
    draw.text((8, header), "정답", fill="black", font=font)
    for index, name in enumerate(class_names):
        draw.text((header + index * cell + 6, header - 18), name, fill="black", font=font)
        draw.text((header - 45, header + index * cell + 8), name, fill="black", font=font)
    for row_index, row in enumerate(confusion):
        for column_index, value in enumerate(row):
            intensity = int(235 - 185 * (value / max_value))
            color = (intensity, int(245 - 80 * (value / max_value)), 255)
            x0 = header + column_index * cell
            y0 = header + row_index * cell
            draw.rectangle((x0, y0, x0 + cell, y0 + cell), fill=color, outline="gray")
            draw.text((x0 + 8, y0 + 8), str(value), fill="black", font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)
