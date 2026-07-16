from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import (
    build_storyboard,
    load_trend_cards,
    search_trends,
    write_html_report,
    write_text_artifacts,
)
from .render import render_animatic


DEFAULT_BRIEF = "니가 좋아 밈을 활용한 여름 카페 신메뉴 숏폼 광고"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create an ad prompt and animatic from the repository's local trend data."
    )
    parser.add_argument("--brief", default=DEFAULT_BRIEF, help="광고 제작 요청")
    parser.add_argument("--product", default="제로 콜드브루", help="제품 또는 서비스명")
    parser.add_argument("--audience", default="20대 직장인", help="핵심 타깃")
    parser.add_argument("--cta", default="오늘 한 잔 만나보기", help="마지막 CTA")
    parser.add_argument("--meme", help="특정 밈 이름을 우선 검색")
    parser.add_argument("--top-k", type=int, default=5, help="보고서에 표시할 후보 수")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="프로젝트 루트",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "output",
        help="산출물 디렉터리",
    )
    parser.add_argument("--prompt-only", action="store_true", help="MP4/GIF 생성을 건너뜀")
    parser.add_argument("--no-gif", action="store_true", help="브라우저용 GIF 생성을 건너뜀")
    parser.add_argument("--width", type=int, default=540)
    parser.add_argument("--height", type=int, default=960)
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--codec", default="mp4v", help="OpenCV fourcc codec")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    args = build_parser().parse_args(argv)
    if args.top_k < 1:
        raise SystemExit("--top-k must be at least 1")

    cards = load_trend_cards(args.repo_root)
    if not cards:
        raise SystemExit("No supported CSV snapshots were found under gather_data/")

    query = " ".join(value for value in (args.meme, args.brief, args.product, args.audience) if value)
    results = search_trends(cards, query, limit=args.top_k)
    if not results:
        raise SystemExit("Trend search returned no candidates")

    storyboard = build_storyboard(
        brief=args.brief,
        product=args.product,
        audience=args.audience,
        cta=args.cta,
        trend=results[0].card,
    )
    output_dir = args.output_dir.resolve()
    write_text_artifacts(output_dir, results=results, storyboard=storyboard)

    has_video = False
    has_gif = False
    if not args.prompt_only:
        gif_path = None if args.no_gif else output_dir / "preview.gif"
        render_animatic(
            storyboard,
            output_dir / "animatic.mp4",
            width=args.width,
            height=args.height,
            fps=args.fps,
            gif_path=gif_path,
            codec=args.codec,
        )
        has_video = True
        has_gif = gif_path is not None

    report = write_html_report(
        output_dir,
        results=results,
        storyboard=storyboard,
        has_video=has_video,
        has_gif=has_gif,
    )
    print(f"loaded_cards={len(cards)}")
    print(f"selected_trend={storyboard.trend.title}")
    print(f"selected_source={storyboard.trend.source}")
    print(f"report={report}")
    if has_video:
        print(f"video={output_dir / 'animatic.mp4'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
