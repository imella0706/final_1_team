const pageHost = window.location.hostname || "127.0.0.1";
const configuredApiOrigin = document
  .querySelector('meta[name="brandmate-api-origin"]')
  ?.content.trim()
  .replace(/\/$/, "");
const isStaticDevelopmentPort = ["5500", "5501"].includes(window.location.port);
const defaultApiOrigin = isStaticDevelopmentPort
  ? `${window.location.protocol}//${pageHost}:7660`
  : window.location.origin;
// [Design Intent] Static local development talks to :7660. Production defaults
// to a same-origin reverse proxy, avoiding HTTPS mixed-content and CORS drift.
const API_BASE_URL = `${configuredApiOrigin || defaultApiOrigin}/api/v1`;

const $ = (selector) => document.querySelector(selector);

const form = $("#ad-form");
const copyModelSelect = $("#copy-model");
const visionModelSelect = $("#vision-model");
const imageModelSelect = $("#image-model");
const copyModelHelp = $("#copy-model-help");
const visionModelHelp = $("#vision-model-help");
const imageModelHelp = $("#image-model-help");
const apiState = $("#api-state");
const channelSelect = $("#channel-select");
const resetButton = $("#reset-button");
const generateButton = form.querySelector(".generate-button");
const runState = $("#run-state");
const pipelineItems = [...document.querySelectorAll("#pipeline li")];
const errorBox = $("#error-box");
const errorMessage = $("#error-message");
const payloadPreview = $("#payload-preview");
const outputPanel = $("#output-panel");
const emptyState = $("#empty-state");
const generatedContent = $("#generated-content");
const referenceImageInput = $("#reference-image");
const referencePreview = $("#reference-preview");
const referencePreviewImage = $("#reference-preview-image");
const referencePreviewName = $("#reference-preview-name");
const referencePreviewMeta = $("#reference-preview-meta");
const referencePreviewClear = $("#reference-preview-clear");
const referenceCutoutToggle = $("#reference-cutout");
const downloadPosterButton = $("#download-poster-button");
const copyPosterButton = $("#copy-poster-button");
const copyNaverBlogButton = $("#copy-naver-blog-button");
const referenceImageLabel = $("#reference-image-label");
const productList = $("#product-list");
const addProductButton = $("#add-product-button");
const voiceScript = $("#voice-script");
const voiceScriptCount = $("#voice-script-count");
const voiceSelect = $("#voice-select");
const voiceInstructions = $("#voice-instructions");
const voiceSpeed = $("#voice-speed");
const voiceSpeedValue = $("#voice-speed-value");
const generateVoiceButton = $("#generate-voice-button");
const voiceState = $("#voice-state");
const voiceError = $("#voice-error");
const voiceOutput = $("#voice-output");
const voicePlayer = $("#voice-player");
const downloadVoiceButton = $("#download-voice-button");

const openAiVoiceOptions = [
  ["coral", "Coral · 밝고 자연스러움"],
  ["nova", "Nova · 활기차고 친근함"],
  ["alloy", "Alloy · 균형 잡힌 중성"],
  ["onyx", "Onyx · 낮고 차분함"],
  ["shimmer", "Shimmer · 부드럽고 밝음"],
  ["echo", "Echo · 또렷하고 안정적"],
  ["ash", "Ash · 차분하고 자연스러움"],
  ["sage", "Sage · 따뜻하고 신뢰감 있음"],
  ["fable", "Fable · 표현력이 풍부함"],
];
const appMain = $("#app-main");
const authDialog = $("#auth-dialog");
const authTabs = $("#auth-tabs");
const authUser = $("#auth-user");
const authUserName = $("#auth-user-name");
const loginTab = $("#login-tab");
const signupTab = $("#signup-tab");
const loginForm = $("#login-form");
const signupForm = $("#signup-form");
const forgotPasswordForm = $("#forgot-password-form");
const resetPasswordForm = $("#reset-password-form");
const loginError = $("#login-error");
const signupError = $("#signup-error");
const forgotPasswordError = $("#forgot-password-error");
const resetPasswordError = $("#reset-password-error");
const forgotPasswordButton = $("#forgot-password-button");
const logoutButton = $("#logout-button");
const securityButton = $("#security-button");
const securityDialog = $("#security-dialog");
const securityCloseButton = $("#security-close-button");
const sessionList = $("#session-list");
const changePasswordForm = $("#change-password-form");
const changePasswordError = $("#change-password-error");
const serviceSelection = $("#service-selection");
const adStudio = $("#ad-studio");
const openAdStudioButton = $("#open-ad-studio");
const backToServicesButton = $("#back-to-services");

let hasGeneratedAd = false;
let referencePreviewDataUrl = null;
let generatedVoiceDataUrl = "";
let generatedVoiceExtension = "mp3";
let configuredVoiceProviderLabel = "openai · gpt-4o-mini-tts";
let latestNaverBlogPasteText = "";
let accessToken = null;
let currentUser = null;
let refreshRequest = null;
const initialActionParams = new URLSearchParams(window.location.hash.replace(/^#/, ""));
let pendingResetToken = initialActionParams.get("reset_token");

const fallbackCopyModels = [
  {
    id: "openai/gpt-5.4-mini",
    name: "OpenAI GPT-5.4 Mini",
    note: "속도/비용 테스트용 GPT 모델. 실서비스 후보 비교에 적합",
    recommended: true,
  },
  {
    id: "Qwen/Qwen2.5-7B-Instruct",
    name: "Qwen 2.5 7B Instruct",
    note: "한국어 광고 문구의 기본 비교 모델",
  },
  {
    id: "mistralai/Mistral-7B-Instruct-v0.3",
    name: "Mistral 7B Instruct v0.3",
    note: "Featherless AI 라우팅으로 사용할 수 있는 비교 모델",
  },
];

const fallbackImageModels = [
  {
    id: "openai/gpt-image-1-mini",
    name: "OpenAI gpt-image-1-mini",
    provider: "OpenAI",
    note: "저비용/일반 이미지 생성용으로 우선 사용합니다.",
    recommended: true,
  },
  {
    id: "black-forest-labs/FLUX.1-schnell",
    name: "FLUX.1 Schnell",
    provider: "Hugging Face Router",
    note: "광고 시안용 이미지 생성을 빠르게 확인할 때 적합합니다.",
  },
  {
    id: "stabilityai/stable-diffusion-xl-base-1.0",
    name: "Stable Diffusion XL Base 1.0",
    provider: "Hugging Face Router",
    note: "범용 이미지 생성 모델입니다.",
  },
  {
    id: "prompthero/openjourney",
    name: "Openjourney",
    provider: "Hugging Face Router",
    note: "스타일이 있는 홍보/포스터 시안에 적합합니다.",
  },
];

const fallbackVisionModels = [
  {
    id: "openai/gpt-5.4-mini",
    name: "GPT-5.4 Mini Vision",
    provider: "OpenAI",
    note: "기존 OpenAI 사진 분석 모델입니다.",
    enabled: true,
    recommended: true,
  },
  {
    id: "Qwen/Qwen2.5-VL-7B-Instruct",
    name: "Qwen2.5-VL-7B-Instruct",
    provider: "Hugging Face",
    note: "사진 이해, OCR, 이미지 설명과 한국어 분석에 적합합니다.",
    enabled: true,
  },
];

const displayLabels = {
  businessType: {
    cafe: "카페",
    bakery: "베이커리",
    dessert: "디저트",
    restaurant: "음식점",
    pub: "주점",
  },
  situation: {
    new_menu: "신메뉴",
    discount: "세트메뉴 할인",
    event: "이벤트",
    delivery: "배달",
    takeout: "포장",
    visit: "방문 유도",
  },
  ageGroup: {
    teens: "10대",
    twenties: "20대",
    thirties: "30대",
    forties: "40대",
    fifties_plus: "50대 이상",
  },
  target: {
    office_workers: "직장인",
    students: "학생",
    middle_school_students: "중학생",
    high_school_students: "고등학생",
    college_students: "대학생",
    families: "가족",
    couples: "커플",
    solo: "혼자",
  },
  gender: {
    all: "전체",
    female: "여성",
    male: "남성",
  },
  occupationGroup: {
    none: "해당 없음",
    office_worker: "직장인",
    student: "학생",
    self_employed: "자영업",
    freelancer: "프리랜서",
    professional: "전문직",
    homemaker: "주부",
    job_seeker: "취준생",
    other: "기타",
  },
};

function wait(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function commaList(value) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatLatencySeconds(latencyMs) {
  if (typeof latencyMs !== "number" || Number.isNaN(latencyMs)) {
    return "미집계";
  }
  const seconds = latencyMs / 1000;
  return `${seconds.toFixed(seconds >= 10 ? 0 : 1)}초`;
}

function formatFileSize(bytes) {
  if (!Number.isFinite(bytes)) {
    return "";
  }
  if (bytes >= 1024 * 1024) {
    return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
  }
  return `${Math.max(1, Math.round(bytes / 1024))}KB`;
}

function displayValue(group, value) {
  return displayLabels[group]?.[value] || value;
}

function displayList(group, values) {
  return values.map((value) => displayValue(group, value)).filter(Boolean).join(", ");
}

function optionalLine(label, value) {
  const trimmed = `${value || ""}`.trim();
  return trimmed ? `${label}: ${trimmed}` : null;
}

function readProductRows() {
  const rows = [...document.querySelectorAll(".product-row")];
  const products = rows
    .map((row) => {
      const name = row.querySelector('[name="productName"]')?.value.trim() || "";
      const price = row.querySelector('[name="productPrice"]')?.value.trim() || "";
      return { name, price };
    })
    .filter((item) => item.name);
  return products;
}

function formatProductPrices(products) {
  return products
    .filter((item) => item.price)
    .map((item) => `${item.name} ${item.price}`)
    .join(", ");
}

function addProductRow() {
  const row = document.createElement("div");
  row.className = "product-row";

  const nameInput = document.createElement("input");
  nameInput.name = "productName";
  nameInput.placeholder = "상품명";

  const priceInput = document.createElement("input");
  priceInput.name = "productPrice";
  priceInput.placeholder = "가격";
  priceInput.maxLength = 80;

  const removeButton = document.createElement("button");
  removeButton.className = "text-button product-remove-button";
  removeButton.type = "button";
  removeButton.textContent = "삭제";
  removeButton.addEventListener("click", () => row.remove());

  row.append(nameInput, priceInput, removeButton);
  productList?.append(row);
  nameInput.focus();
}

function defaultChannelRecommendation(channel) {
  const recommendations = {
    instagram: {
      format_name: "인스타그램 피드",
      writing_direction: "첫 문장은 짧게, 본문에는 상품 매력과 CTA를 이어서 배치하세요.",
      image_direction: "4:5 피드 이미지에 상품을 크게 보여 주세요.",
      placement_tip: "이미지에는 짧은 헤드라인만, 자세한 설명과 해시태그는 캡션에 넣으면 좋습니다.",
      overlay_headline: "오늘은 달콤하게, 특별하게",
      caption: "상품의 매력과 방문 맥락을 자연스러운 인스타 캡션으로 사용하세요.",
      publish_cta: "매장에서 만나보세요.",
      publish_hashtags: ["#디저트맛집", "#카페추천"],
      publish_title: "인스타그램 피드 게시물",
      publish_body: "상품 소개 본문과 CTA를 캡션으로 사용하세요.",
      promotion_template: "이미지\n게시 제목\n캡션 본문\nCTA\n해시태그",
      image_insert_guide: "생성 이미지는 피드 첫 장에 배치하세요.",
    },
    naver_blog: {
      format_name: "네이버 블로그",
      writing_direction: "작성된 글을 도입부, 상품 설명, 방문/주문 안내 문단으로 나누세요.",
      image_direction: "대표 이미지는 글 첫머리에, 상품 상세 이미지는 본문 중간에 넣으세요.",
      placement_tip: "글과 사진을 번갈아 배치하면 읽는 흐름이 자연스럽습니다.",
      overlay_headline: "",
      caption: "",
      publish_cta: "",
      publish_hashtags: [],
      publish_title: "네이버 블로그 게시글",
      publish_body: "도입, 상품 설명, 방문 안내 순서로 본문을 구성하세요.",
      promotion_template: "제목\n대표 사진\n도입\n상품 설명\n방문/주문 안내\nCTA",
      image_insert_guide: "대표 이미지는 제목 아래, 추가 이미지는 상품 설명 문단 뒤에 넣으세요.",
      blog_title: "네이버 블로그 게시글",
      thumbnail_photo: "사진 1",
      thumbnail_reason: "첫 화면에서 매장 또는 대표 메뉴를 가장 빠르게 보여줄 수 있습니다.",
      photo_order: ["사진 1", "사진 2", "사진 3"],
      blog_sections: [],
    },
    delivery_app: {
      format_name: "배달앱 포스터",
      writing_direction: "상품명, 가격/혜택, 주문 CTA가 바로 보이게 짧게 쓰세요.",
      image_direction: "상품 중심의 포스터 전체 이미지로 사용하세요.",
      placement_tip: "앱 카드에서는 이미지 아래에 핵심 혜택과 주문 버튼 문구를 붙이면 좋습니다.",
      overlay_headline: "",
      caption: "",
      publish_cta: "",
      publish_hashtags: [],
      publish_title: "배달앱 포스터",
      publish_body: "상품명, 가격/혜택, 주문 CTA가 빠르게 보이게 작성하세요.",
      promotion_template: "포스터 제목\n상품 이미지\n가격/혜택\n주문 CTA",
      image_insert_guide: "생성 이미지는 앱 대표 카드 또는 배너 영역에 사용하세요.",
    },
    store_poster: {
      format_name: "매장 포스터",
      writing_direction: "멀리서도 읽히는 한 줄 헤드라인과 짧은 CTA를 사용하세요.",
      image_direction: "상품이 크게 보이는 세로 포스터 이미지로 사용하세요.",
      placement_tip: "상단 헤드라인, 중앙 상품, 하단 CTA 순서가 안정적입니다.",
      overlay_headline: "",
      caption: "",
      publish_cta: "",
      publish_hashtags: [],
      publish_title: "매장 포스터",
      publish_body: "짧은 상품 설명과 방문 CTA를 함께 사용하세요.",
      promotion_template: "상단 헤드라인\n중앙 상품 이미지\n하단 CTA",
      image_insert_guide: "생성 이미지는 포스터 중앙에 크게 배치하세요.",
    },
  };
  return recommendations[channel] || {
    format_name: "디지털 광고",
    writing_direction: "본문과 CTA를 함께 사용하세요.",
    image_direction: "상품 중심 이미지를 사용하세요.",
    placement_tip: "글과 이미지가 같은 핵심 메시지를 말하도록 배치하세요.",
    overlay_headline: "",
    caption: "",
    publish_cta: "",
    publish_hashtags: [],
    publish_title: "디지털 광고 게시물",
    publish_body: "본문과 CTA를 함께 사용하세요.",
    promotion_template: "제목\n이미지\n본문\nCTA",
    image_insert_guide: "생성 이미지를 게시물 상단에 넣으세요.",
  };
}

function setText(selector, text) {
  $(selector).textContent = text || "";
}

function splitLongCanvasToken(context, token, maxWidth) {
  const parts = [];
  let part = "";
  [...token].forEach((character) => {
    const nextPart = `${part}${character}`;
    if (context.measureText(nextPart).width <= maxWidth || !part) {
      part = nextPart;
      return;
    }
    parts.push(part);
    part = character;
  });
  if (part) {
    parts.push(part);
  }
  return parts;
}

function wrapCanvasText(context, text, maxWidth) {
  const words = `${text || ""}`
    .trim()
    .split(/\s+/)
    .flatMap((word) =>
      context.measureText(word).width > maxWidth ? splitLongCanvasToken(context, word, maxWidth) : [word],
    )
    .filter(Boolean);
  const lines = [];
  let line = "";
  words.forEach((word) => {
    const nextLine = line ? `${line} ${word}` : word;
    if (context.measureText(nextLine).width <= maxWidth || !line) {
      line = nextLine;
      return;
    }
    lines.push(line);
    line = word;
  });
  if (line) {
    lines.push(line);
  }
  return lines;
}

function truncateCanvasLine(line, maxCharacters = 38) {
  const text = `${line || ""}`.trim();
  if ([...text].length <= maxCharacters) {
    return text;
  }
  return `${[...text].slice(0, Math.max(1, maxCharacters - 1)).join("")}…`;
}

function splitPosterTitle(title) {
  const cleanTitle = `${title || ""}`.replace(/\s+/g, " ").trim();
  if (!cleanTitle) {
    return { headline: "", subtitle: "" };
  }
  const separators = [" – ", " - ", " — ", " | ", " / ", ": "];
  const separator = separators.find((item) => cleanTitle.includes(item));
  if (separator && [...cleanTitle].length > 24) {
    const [headline, ...rest] = cleanTitle.split(separator);
    return {
      headline: truncateCanvasLine(headline, 24),
      subtitle: truncateCanvasLine(rest.join(separator), 44),
    };
  }
  if ([...cleanTitle].length > 28) {
    return {
      headline: truncateCanvasLine([...cleanTitle].slice(0, 24).join(""), 24),
      subtitle: truncateCanvasLine([...cleanTitle].slice(24).join("").trim(), 44),
    };
  }
  return { headline: cleanTitle, subtitle: "" };
}

function buildShortPosterHeadline(input) {
  const region = `${input?.copy?.region || ""}`.trim();
  const localArea = region.match(/[가-힣0-9]+(?:동|읍|면|리|가)/g)?.at(-1) || "";
  const businessType = displayValue("businessType", input?.copy?.business_type || "").trim();
  const businessName = `${input?.copy?.business_name || ""}`.trim();
  return [localArea, businessType, businessName].filter(Boolean).join(" ");
}

function fitCanvasText(context, text, maxWidth, options) {
  const minSize = options.minSize || 28;
  const maxLines = options.maxLines || 2;
  for (let size = options.maxSize; size >= minSize; size -= 2) {
    context.font = `${options.weight || 650} ${size}px ${options.family}`;
    const lines = wrapCanvasText(context, text, maxWidth);
    if (lines.length <= maxLines) {
      return {
        font: context.font,
        fontSize: size,
        lineHeight: Math.round(size * (options.lineHeightRatio || 1.22)),
        lines,
      };
    }
  }
  context.font = `${options.weight || 650} ${minSize}px ${options.family}`;
  const lines = wrapCanvasText(context, text, maxWidth).slice(0, maxLines);
  if (lines.length) {
    lines[lines.length - 1] = truncateCanvasLine(lines[lines.length - 1], options.fallbackCharacters || 36);
  }
  return {
    font: context.font,
    fontSize: minSize,
    lineHeight: Math.round(minSize * (options.lineHeightRatio || 1.22)),
    lines,
  };
}

async function buildMergedPosterBlob() {
  const image = $("#generated-image");
  const headline = $("#poster-headline").textContent.trim();
  const subtitle = $("#poster-subtitle")?.textContent.trim() || "";
  if (!image?.src || !headline) {
    throw new Error("합칠 이미지와 문구가 아직 없습니다.");
  }

  if (!image.complete) {
    await new Promise((resolve, reject) => {
      image.addEventListener("load", resolve, { once: true });
      image.addEventListener("error", reject, { once: true });
    });
  }

  const width = image.naturalWidth || 1024;
  const height = image.naturalHeight || Math.round(width * 1.25);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext("2d");
  context.drawImage(image, 0, 0, width, height);

  const gradient = context.createLinearGradient(0, height * 0.52, 0, height);
  gradient.addColorStop(0, "rgba(24, 18, 14, 0)");
  gradient.addColorStop(0.42, "rgba(24, 18, 14, 0.34)");
  gradient.addColorStop(1, "rgba(24, 18, 14, 0.78)");
  context.fillStyle = gradient;
  context.fillRect(0, 0, width, height);

  const padding = Math.round(width * 0.075);
  context.textBaseline = "bottom";
  context.fillStyle = "#ffffff";
  context.shadowColor = "rgba(0, 0, 0, 0.45)";
  context.shadowBlur = Math.round(width * 0.018);
  context.shadowOffsetY = Math.round(width * 0.006);

  const textWidth = width - padding * 2;
  const headlineFit = fitCanvasText(context, headline, textWidth, {
    maxSize: Math.max(46, Math.round(width * 0.064)),
    minSize: Math.max(30, Math.round(width * 0.036)),
    maxLines: 2,
    weight: 700,
    family: 'Georgia, "Noto Serif KR", serif',
    fallbackCharacters: 28,
  });
  const subtitleFit = subtitle
    ? fitCanvasText(context, subtitle, textWidth, {
        maxSize: Math.max(24, Math.round(width * 0.034)),
        minSize: Math.max(18, Math.round(width * 0.023)),
        maxLines: 2,
        weight: 600,
        family: '"Noto Sans KR", Arial, sans-serif',
        lineHeightRatio: 1.32,
        fallbackCharacters: 44,
      })
    : { lines: [], lineHeight: 0, font: "" };
  const gap = subtitleFit.lines.length ? Math.round(width * 0.018) : 0;
  const totalHeight =
    headlineFit.lineHeight * headlineFit.lines.length + subtitleFit.lineHeight * subtitleFit.lines.length + gap;
  let y = height - padding - totalHeight + headlineFit.lineHeight;

  context.font = headlineFit.font;
  context.fillStyle = "#ffffff";
  headlineFit.lines.forEach((line) => {
    context.fillText(line, padding, y);
    y += headlineFit.lineHeight;
  });

  if (subtitleFit.lines.length) {
    y += gap;
    context.font = subtitleFit.font;
    context.fillStyle = "rgba(255, 255, 255, 0.88)";
    subtitleFit.lines.forEach((line) => {
      context.fillText(line, padding, y);
      y += subtitleFit.lineHeight;
    });
  }

  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error("포스터 이미지를 만들 수 없습니다."));
    }, "image/png");
  });
}

async function downloadMergedPoster() {
  const blob = await buildMergedPosterBlob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = `brandmate-poster-${Date.now()}.png`;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}

async function copyMergedPoster() {
  if (!navigator.clipboard || !window.ClipboardItem) {
    throw new Error("이 브라우저에서는 이미지 복사를 지원하지 않습니다. 저장 버튼을 사용해 주세요.");
  }
  const blob = await buildMergedPosterBlob();
  await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
}

function normalizeParagraphs(value) {
  return `${value || ""}`
    .replace(/\r\n/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function normalizeNaverBlogBody(value) {
  return normalizeParagraphs(value)
    .split("\n")
    .filter(
      (line) =>
        !/^\[(?:대표\s*사진\s*추천|대표사진\s*추천|추천\s*사진\s*순서|사진\s*순서\s*추천(?:\s*이유)?)\s*[-:：]/.test(
          line.trim(),
        ),
    )
    .join("\n")
    .replace(/\[사진\s*\d+\s*-\s*매장 내부 또는 전경\]/g, "[사진 2 - 매장 내부 또는 전경]")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function buildNaverBlogPasteText(input, recommendation, copy, publishHashtags) {
  if (input.copy.channel !== "naver_blog") {
    return "";
  }
  const title = normalizeParagraphs(recommendation.blog_title || recommendation.publish_title || copy.headlines?.[0]);
  const body = normalizeNaverBlogBody(recommendation.publish_body || copy.body_copies?.[0] || "");
  const hashtags = normalizeParagraphs(publishHashtags || copy.hashtags?.join(" ") || "");
  const hasTitle = title && body.startsWith(title);
  const hasHashtags = hashtags && body.includes(hashtags);
  return [hasTitle ? "" : title, body, hasHashtags ? "" : hashtags]
    .filter(Boolean)
    .join("\n\n")
    .trim();
}

async function copyNaverBlogPasteText() {
  if (!latestNaverBlogPasteText) {
    throw new Error("복사할 네이버 블로그 원고가 아직 없습니다.");
  }
  if (!navigator.clipboard?.writeText) {
    throw new Error("현재 브라우저에서 텍스트 복사를 지원하지 않습니다.");
  }
  await navigator.clipboard.writeText(latestNaverBlogPasteText);
}

function buildContextLine(input) {
  const parts = [
    displayValue("businessType", input.copy.business_type),
    displayValue("situation", input.copy.situation),
    displayList("ageGroup", input.copy.age_groups),
    displayValue("gender", input.audience.gender),
    input.audience.occupation_group !== "none"
      ? displayValue("occupationGroup", input.audience.occupation_group)
      : "",
    displayList("target", input.copy.target_audiences),
    input.audience.region,
    input.audience.trade_area,
  ];
  return parts.filter(Boolean).join(" · ");
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("참고 이미지를 읽는 데 실패했습니다."));
    reader.readAsDataURL(file);
  });
}

function loadImage(dataUrl) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("이미지를 처리하는 데 실패했습니다."));
    image.src = dataUrl;
  });
}

function colorDistance(data, offset, color) {
  const red = data[offset] - color.red;
  const green = data[offset + 1] - color.green;
  const blue = data[offset + 2] - color.blue;
  return Math.sqrt(red * red + green * green + blue * blue);
}

function averageBackgroundColor(data, width, height) {
  const samples = [];
  const sampleSize = Math.min(18, Math.floor(Math.min(width, height) / 8));
  const corners = [
    [0, 0],
    [width - sampleSize, 0],
    [0, height - sampleSize],
    [width - sampleSize, height - sampleSize],
  ];

  corners.forEach(([startX, startY]) => {
    for (let y = startY; y < startY + sampleSize; y += 1) {
      for (let x = startX; x < startX + sampleSize; x += 1) {
        const offset = (y * width + x) * 4;
        samples.push([data[offset], data[offset + 1], data[offset + 2]]);
      }
    }
  });

  const total = samples.reduce(
    (sum, color) => ({
      red: sum.red + color[0],
      green: sum.green + color[1],
      blue: sum.blue + color[2],
    }),
    { red: 0, green: 0, blue: 0 },
  );

  return {
    red: total.red / samples.length,
    green: total.green / samples.length,
    blue: total.blue / samples.length,
  };
}

function removeConnectedBackground(imageData, width, height) {
  const data = imageData.data;
  const background = averageBackgroundColor(data, width, height);
  const hardTolerance = 58;
  const softTolerance = 30;
  const visited = new Uint8Array(width * height);
  const queue = [];

  function enqueueIfBackground(x, y) {
    if (x < 0 || y < 0 || x >= width || y >= height) return;
    const index = y * width + x;
    if (visited[index]) return;
    const offset = index * 4;
    if (colorDistance(data, offset, background) > hardTolerance + softTolerance) return;
    visited[index] = 1;
    queue.push(index);
  }

  for (let x = 0; x < width; x += 1) {
    enqueueIfBackground(x, 0);
    enqueueIfBackground(x, height - 1);
  }
  for (let y = 0; y < height; y += 1) {
    enqueueIfBackground(0, y);
    enqueueIfBackground(width - 1, y);
  }

  for (let cursor = 0; cursor < queue.length; cursor += 1) {
    const index = queue[cursor];
    const x = index % width;
    const y = Math.floor(index / width);
    enqueueIfBackground(x + 1, y);
    enqueueIfBackground(x - 1, y);
    enqueueIfBackground(x, y + 1);
    enqueueIfBackground(x, y - 1);
  }

  queue.forEach((index) => {
    const offset = index * 4;
    const distance = colorDistance(data, offset, background);
    const alpha =
      distance <= hardTolerance
        ? 0
        : Math.round(255 * ((distance - hardTolerance) / softTolerance));
    data[offset + 3] = Math.min(255, Math.max(0, alpha));
  });

  return imageData;
}

async function createReferenceCutout(file) {
  const dataUrl = await readFileAsDataUrl(file);
  const image = await loadImage(dataUrl);
  const maxSize = 1280;
  const scale = Math.min(1, maxSize / Math.max(image.naturalWidth, image.naturalHeight));
  const width = Math.max(1, Math.round(image.naturalWidth * scale));
  const height = Math.max(1, Math.round(image.naturalHeight * scale));
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d", { willReadFrequently: true });
  canvas.width = width;
  canvas.height = height;
  context.drawImage(image, 0, 0, width, height);

  const imageData = context.getImageData(0, 0, width, height);
  context.putImageData(removeConnectedBackground(imageData, width, height), 0, 0);
  return canvas.toDataURL("image/png");
}

async function buildReferenceDataUrl(file) {
  if (!referenceCutoutToggle?.checked) {
    return readFileAsDataUrl(file);
  }
  return createReferenceCutout(file);
}

function setStage(index, state, label) {
  const item = pipelineItems[index];
  item.classList.remove("active", "complete", "error");
  if (state) item.classList.add(state);
  item.querySelector("small").textContent = label;
}

function resetPipeline() {
  pipelineItems.forEach((item) => {
    item.classList.remove("active", "complete", "error");
    item.querySelector("small").textContent = "대기";
  });
  errorBox.hidden = true;
}

function showEmptyState() {
  hasGeneratedAd = false;
  emptyState.hidden = false;
  generatedContent.hidden = true;
  outputPanel.classList.add("is-empty");
}

function showGeneratedState() {
  hasGeneratedAd = true;
  emptyState.hidden = true;
  generatedContent.hidden = false;
  outputPanel.classList.remove("is-empty");
}

function updateVoiceScriptCount() {
  if (voiceScriptCount && voiceScript) {
    voiceScriptCount.textContent = String(voiceScript.value.length);
  }
}

function resetVoiceResult() {
  generatedVoiceDataUrl = "";
  generatedVoiceExtension = "mp3";
  if (voicePlayer) {
    voicePlayer.pause();
    voicePlayer.removeAttribute("src");
    voicePlayer.load();
  }
  if (voiceOutput) voiceOutput.hidden = true;
  if (voiceError) voiceError.hidden = true;
  if (voiceState) {
    voiceState.textContent = "준비됨";
    voiceState.className = "voice-state";
  }
  const audioModelLabel = $("#result-audio-model");
  if (audioModelLabel) audioModelLabel.textContent = configuredVoiceProviderLabel;
}

function normalizeContentResult(result) {
  const copy = result.copy || result.copy_result;
  const image = result.image;

  if (!copy || !image) {
    throw new Error("생성된 광고 콘텐츠가 API 응답에 없습니다.");
  }

  return {
    ...result,
    copy,
    image,
  };
}

async function readReferenceImage() {
  const file = referenceImageInput?.files?.[0];
  if (!file) {
    return null;
  }
  if (channelSelect?.value === "naver_blog") {
    return readFileAsDataUrl(file);
  }

  if (referencePreviewDataUrl) {
    return referencePreviewDataUrl;
  }
  return buildReferenceDataUrl(file);
}

async function readBlogImages() {
  const files = [...(referenceImageInput?.files || [])].filter((file) =>
    file.type.startsWith("image/"),
  );
  const images = [];
  for (const [index, file] of files.slice(0, 8).entries()) {
    images.push({
      id: `사진 ${index + 1}`,
      name: file.name,
      data_url: await readFileAsDataUrl(file),
    });
  }
  return images;
}

function clearReferencePreview() {
  if (referenceImageInput) {
    referenceImageInput.value = "";
  }
  referencePreviewDataUrl = null;
  if (!referencePreview) {
    return;
  }
  referencePreview.hidden = true;
  referencePreviewImage?.removeAttribute("src");
  if (referencePreviewName) referencePreviewName.textContent = "";
  if (referencePreviewMeta) referencePreviewMeta.textContent = "";
}

async function updateReferencePreview() {
  const files = [...(referenceImageInput?.files || [])];
  const file = files[0];
  if (!file) {
    clearReferencePreview();
    return;
  }

  if (!file.type.startsWith("image/")) {
    window.alert("이미지 파일만 선택해 주세요.");
    clearReferencePreview();
    return;
  }

  try {
    if (!referencePreview || !referencePreviewImage) {
      return;
    }
    referencePreviewDataUrl =
      channelSelect?.value === "naver_blog"
        ? await readFileAsDataUrl(file)
        : await buildReferenceDataUrl(file);
    referencePreviewImage.src = referencePreviewDataUrl;
    if (referencePreviewName) {
      referencePreviewName.textContent =
        files.length > 1 ? `${file.name} 외 ${files.length - 1}장` : file.name;
    }
    if (referencePreviewMeta) {
      const mode = channelSelect?.value === "naver_blog"
        ? "블로그 사진 분석"
        : referenceCutoutToggle?.checked
          ? "제품만 추출"
          : "원본";
      referencePreviewMeta.textContent = `${mode} · ${file.type || "image"} · ${formatFileSize(file.size)}`;
    }
    referencePreview.hidden = false;
  } catch (error) {
    window.alert(error.message);
    clearReferencePreview();
  }
}

function updateChannelMode() {
  const isBlog = channelSelect?.value === "naver_blog";
  if (referenceImageLabel) {
    referenceImageLabel.textContent = isBlog ? "블로그 사진 여러 장(선택)" : "참고 이미지(선택)";
  }
  if (referenceCutoutToggle) {
    referenceCutoutToggle.closest("label").hidden = isBlog;
  }
  updateReferencePreview();
}

async function readForm() {
  const data = new FormData(form);
  const channel = data.get("channel");
  const referenceImageDataUrl = await readReferenceImage();
  const blogImages = channel === "naver_blog" ? await readBlogImages() : [];
  const gender = data.get("gender") || "all";
  const occupationGroup = data.get("occupationGroup") || "none";
  const products = readProductRows();
  const productNames = products.map((item) => item.name);
  const productPrice = formatProductPrices(products);
  const interests = data.get("interests");
  const region = data.get("region");
  const tradeArea = data.get("tradeArea");
  const audienceDetail = data.get("audienceDetail");
  const baseFeatures = data
    .get("features")
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
  const audienceContext = [
    optionalLine("성별 타겟", displayValue("gender", gender)),
    occupationGroup !== "none"
      ? optionalLine("직업군", displayValue("occupationGroup", occupationGroup))
      : null,
    optionalLine("타겟", displayList("target", data.getAll("target"))),
    optionalLine("제품가격", productPrice),
    optionalLine("관심사", interests),
    optionalLine("지역", region),
    optionalLine("상권", tradeArea),
    optionalLine("세부 타겟", audienceDetail),
  ].filter(Boolean);
  const requiredTerms = [productPrice, region, tradeArea]
    .map((value) => `${value || ""}`.trim())
    .filter(Boolean);

  return {
    copy: {
      model: data.get("copyModel"),
      business_name: data.get("businessName").trim(),
      business_type: data.get("businessType"),
      situation: data.get("situation"),
      age_groups: data.getAll("ageGroup"),
      target_audiences: data.getAll("target"),
      tone: data.get("tone"),
      product_names: productNames,
      features: [...baseFeatures, ...audienceContext].slice(0, 10),
      channel,
      promotion: audienceContext.join(" / ") || null,
      required_terms: requiredTerms.slice(0, 10),
      prohibited_terms: commaList(data.get("prohibited")),
      gender,
      occupation_group: occupationGroup,
      product_price: `${productPrice || ""}`.trim(),
      interests: commaList(interests || ""),
      region: `${region || ""}`.trim(),
      trade_area: `${tradeArea || ""}`.trim(),
      audience_detail: `${audienceDetail || ""}`.trim(),
      blog_purpose: null,
      blog_emphasis: [],
      blog_style: null,
      seo_keywords: [],
      blog_length: null,
      additional_request: null,
      operating_info: `${data.get("operatingInfo") || ""}`.trim() || null,
    },
    audience: {
      gender,
      occupation_group: occupationGroup,
      product_price: `${productPrice || ""}`.trim(),
      interests: commaList(interests || ""),
      region: `${region || ""}`.trim(),
      trade_area: `${tradeArea || ""}`.trim(),
      detail: `${audienceDetail || ""}`.trim(),
    },
    image_model: data.get("imageModel"),
    vision_model: data.get("visionModel"),
    image_width: 1024,
    image_height: 1280,
    reference_image_data_url: referenceImageDataUrl,
    blog_images: blogImages,
  };
}

class ApiRequestError extends Error {
  constructor(message, status, code = "API_REQUEST_FAILED") {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
  }
}

async function requestJson(path, options = {}, useAccessToken = false) {
  const headers = new Headers(options.headers || {});
  if (useAccessToken && accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
    credentials: "include",
  });
  let body = {};
  try {
    body = await response.json();
  } catch {
    body = {};
  }
  return { response, body };
}

function toApiError(response, body) {
  const error = body.error || {};
  return new ApiRequestError(
    error.message || body.detail || `API error (${response.status})`,
    response.status,
    error.code,
  );
}

function applySession(session) {
  accessToken = session.access_token;
  currentUser = session.user;
}

async function authRequest(path, options = {}) {
  const { response, body } = await requestJson(path, options, false);
  if (!response.ok) {
    throw toApiError(response, body);
  }
  return body;
}

async function refreshSession() {
  if (!refreshRequest) {
    const rotate = () => authRequest("/auth/refresh", { method: "POST" });
    // [Design Intent] In-tab calls share one Promise and the Web Locks API
    // serializes refresh rotation across tabs that share the same HttpOnly cookie.
    const coordinated = navigator.locks?.request
      ? navigator.locks.request("brandmate-auth-refresh", rotate)
      : rotate();
    refreshRequest = coordinated
      .then((session) => {
        applySession(session);
        return session;
      })
      .finally(() => {
        refreshRequest = null;
      });
  }
  return refreshRequest;
}

async function fetchJson(path, options = {}, allowRefresh = true) {
  const { response, body } = await requestJson(path, options, true);
  if (response.status === 401 && allowRefresh) {
    try {
      await refreshSession();
      return fetchJson(path, options, false);
    } catch {
      showAuthGate("세션이 만료되었습니다. 다시 로그인해 주세요.");
      throw new ApiRequestError("로그인이 필요합니다.", 401, "AUTH_REQUIRED");
    }
  }
  if (!response.ok) {
    throw toApiError(response, body);
  }
  return body;
}

function setAuthMode(mode) {
  const showLogin = mode === "login";
  const showSignup = mode === "signup";
  const showForgot = mode === "forgot";
  const showReset = mode === "reset";
  authTabs.hidden = !(showLogin || showSignup);
  loginTab.setAttribute("aria-selected", String(showLogin));
  signupTab.setAttribute("aria-selected", String(showSignup));
  loginForm.hidden = !showLogin;
  signupForm.hidden = !showSignup;
  forgotPasswordForm.hidden = !showForgot;
  resetPasswordForm.hidden = !showReset;
  [loginError, signupError, forgotPasswordError, resetPasswordError].forEach((element) => {
    element.hidden = true;
    element.classList.remove("auth-notice");
  });
  window.setTimeout(() => {
    const focusTarget = {
      login: "#login-email",
      signup: "#signup-name",
      forgot: "#forgot-password-email",
      reset: "#reset-password",
    }[mode];
    $(focusTarget)?.focus();
  }, 0);
}

function showAuthGate(message = "", notice = false) {
  accessToken = null;
  currentUser = null;
  appMain.hidden = true;
  serviceSelection.hidden = false;
  adStudio.hidden = true;
  authUser.hidden = true;
  apiState.textContent = "로그인 필요";
  apiState.className = "offline";
  setAuthMode("login");
  loginError.textContent = message;
  loginError.classList.toggle("auth-notice", notice);
  loginError.hidden = !message;
  if (!authDialog.open) {
    authDialog.showModal();
  }
}

function showServiceSelection() {
  serviceSelection.hidden = false;
  adStudio.hidden = true;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showAdStudio() {
  serviceSelection.hidden = true;
  adStudio.hidden = false;
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showAuthenticated(session) {
  applySession(session);
  authUserName.textContent = currentUser.display_name;
  authUser.hidden = false;
  appMain.hidden = false;
  showServiceSelection();
  if (authDialog.open) {
    authDialog.close();
  }
}

function setFormBusy(authForm, busy) {
  const submit = authForm.querySelector('button[type="submit"]');
  submit.disabled = busy;
}

function renderSessions(sessions) {
  sessionList.replaceChildren();
  sessions.forEach((session) => {
    const row = document.createElement("div");
    row.className = "session-item";
    const description = document.createElement("div");
    const name = document.createElement("strong");
    const lastSeen = document.createElement("small");
    name.textContent = `${session.device_name}${session.current ? " · 현재 기기" : ""}`;
    lastSeen.textContent = `최근 사용 ${new Date(session.last_seen_at).toLocaleString("ko-KR")}`;
    description.append(name, lastSeen);
    row.append(description);
    if (!session.current) {
      const revokeButton = document.createElement("button");
      revokeButton.type = "button";
      revokeButton.className = "topbar-command";
      revokeButton.textContent = "로그아웃";
      revokeButton.addEventListener("click", async () => {
        revokeButton.disabled = true;
        try {
          await fetchJson(`/auth/sessions/${session.id}`, { method: "DELETE" });
          await loadSessions();
        } catch (error) {
          window.alert(error.message);
        } finally {
          revokeButton.disabled = false;
        }
      });
      row.append(revokeButton);
    }
    sessionList.append(row);
  });
}

async function loadSessions() {
  const body = await fetchJson("/auth/sessions");
  renderSessions(body.sessions);
}

async function bootstrapAuth() {
  const verifyToken = initialActionParams.get("verify_token");
  if (verifyToken) {
    try {
      await authRequest("/auth/verify-email", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: verifyToken }),
      });
      // [Design Intent] Action tokens arrive in the URL fragment, which is never
      // sent to the static web server, and are removed from browser history here.
      window.history.replaceState(
        {},
        "",
        `${window.location.pathname}${window.location.search}`,
      );
      showAuthGate("이메일 인증이 완료되었습니다. 로그인해 주세요.", true);
    } catch (error) {
      showAuthGate(error.message);
    }
    return;
  }
  if (pendingResetToken) {
    appMain.hidden = true;
    authUser.hidden = true;
    setAuthMode("reset");
    if (!authDialog.open) authDialog.showModal();
    return;
  }
  try {
    const session = await refreshSession();
    showAuthenticated(session);
    await Promise.all([loadModels(), loadAudioProviders()]);
  } catch {
    showAuthGate();
  }
}

function fillSelect(select, models) {
  select.replaceChildren();
  models.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.name;
    option.dataset.note = model.note;
    option.dataset.provider = model.provider || "";
    option.selected = model.recommended;
    select.append(option);
  });
}

function fillVisionSelect(models) {
  visionModelSelect.replaceChildren();
  const groups = new Map();
  models.forEach((model) => {
    const provider = model.provider || "기타";
    if (!groups.has(provider)) {
      const group = document.createElement("optgroup");
      group.label = provider;
      groups.set(provider, group);
      visionModelSelect.append(group);
    }
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.enabled === false ? `${model.name} (설정 필요)` : model.name;
    option.dataset.note = model.note;
    option.dataset.provider = provider;
    option.disabled = model.enabled === false;
    option.selected = Boolean(model.recommended && model.enabled !== false);
    groups.get(provider).append(option);
  });
}

function imageProviderGroup(provider) {
  if (provider === "OpenAI" || provider === "OpenAI Responses API") {
    return "GPT / OpenAI";
  }
  if (provider === "Hugging Face Router") {
    return "Hugging Face";
  }
  if (provider === "Local ComfyUI") {
    return "Local ComfyUI";
  }
  return provider || "기타";
}

function fillImageSelect(models) {
  imageModelSelect.replaceChildren();
  const groups = new Map();
  models.forEach((model) => {
    const groupName = imageProviderGroup(model.provider);
    if (!groups.has(groupName)) {
      const group = document.createElement("optgroup");
      group.label = groupName;
      groups.set(groupName, group);
      imageModelSelect.append(group);
    }
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.name;
    option.dataset.note = model.note;
    option.dataset.provider = model.provider || "";
    option.selected = Boolean(model.recommended);
    groups.get(groupName).append(option);
  });
}

function updateModelHelp() {
  const copyOption = copyModelSelect.selectedOptions[0];
  const visionOption = visionModelSelect.selectedOptions[0];
  const imageOption = imageModelSelect.selectedOptions[0];
  copyModelHelp.textContent = copyOption?.dataset.note || "광고 문구 모델을 선택해 주세요.";
  visionModelHelp.textContent = visionOption?.dataset.note || "사진 분석 모델을 선택해 주세요.";
  imageModelHelp.textContent = imageOption?.dataset.note || "이미지 생성 모델을 선택해 주세요.";
}

async function loadModels() {
  fillSelect(copyModelSelect, fallbackCopyModels);
  fillVisionSelect(fallbackVisionModels);
  fillImageSelect(fallbackImageModels);
  updateModelHelp();

  try {
    const [copyModels, visionModels, imageModels] = await Promise.all([
      fetchJson("/ad-copies/models"),
      fetchJson("/ad-content/vision-models"),
      fetchJson("/ad-content/image-models"),
    ]);
    fillSelect(copyModelSelect, copyModels);
    fillVisionSelect(visionModels);
    fillImageSelect(imageModels);
    updateModelHelp();
    apiState.textContent = "API 연결됨";
    apiState.className = "online";
  } catch (error) {
    apiState.textContent = "API 연결 실패, 기본 목록 사용";
    apiState.className = "offline";
    copyModelHelp.textContent = error.message;
    visionModelHelp.textContent = error.message;
    imageModelHelp.textContent = error.message;
  }
}

async function generateContent(payload) {
  return fetchJson("/ad-content/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function generateAudio(payload) {
  return fetchJson("/ad-content/audio/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function fillVoiceSelect(voices) {
  if (!voiceSelect) return;
  voiceSelect.replaceChildren();
  voices.forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    voiceSelect.append(option);
  });
}

async function loadAudioProviders() {
  fillVoiceSelect(openAiVoiceOptions);
  try {
    const providers = await fetchJson("/ad-content/audio/providers");
    const cosyvoice = providers.find((provider) => provider.provider === "cosyvoice");
    const openai = providers.find((provider) => provider.provider === "openai");
    if (cosyvoice?.available && cosyvoice.voices?.length) {
      fillVoiceSelect(
        cosyvoice.voices.map((voice) => [
          voice,
          voice === "default" ? "Default · 로컬 기준 음성" : `${voice} · 로컬 음성`,
        ]),
      );
      configuredVoiceProviderLabel = `cosyvoice · ${cosyvoice.model}`;
      if (voiceInstructions) {
        voiceInstructions.disabled = !cosyvoice.instructions_supported;
        voiceInstructions.title = cosyvoice.instructions_supported
          ? ""
          : "로컬 안전 모드에서는 기준 음성의 말투와 속도 설정을 사용합니다.";
      }
    } else if (openai) {
      configuredVoiceProviderLabel = `openai · ${openai.model}`;
      if (voiceInstructions) {
        voiceInstructions.disabled = false;
        voiceInstructions.title = "";
      }
    }
    setText("#result-audio-model", configuredVoiceProviderLabel);
  } catch {
    configuredVoiceProviderLabel = "음성 제공자 확인 필요";
    setText("#result-audio-model", "음성 제공자 확인 필요");
  }
}

function renderResult(input, result) {
  const { copy, image } = result;
  const headline = copy.headlines[0] || "";
  const hashtags = copy.hashtags?.length ? copy.hashtags.join(" ") : "#광고 #이벤트";
  const recommendation =
    copy.channel_recommendation ||
    result.channel_recommendation ||
    defaultChannelRecommendation(input.copy.channel);

  setText("#context-line", buildContextLine(input));
  setText("#headline", headline);
  setText("#body-copy", copy.body_copies[0]);
  setText("#cta", copy.ctas[0]);
  setText("#hashtags", hashtags);
  setText("#channel-format", recommendation.format_name);
  const publishHashtags = recommendation.publish_hashtags?.length
    ? recommendation.publish_hashtags.join(" ")
    : hashtags;
  const shortPosterHeadline =
    buildShortPosterHeadline(input) || recommendation.overlay_headline || recommendation.publish_title || headline;
  const posterTitle = splitPosterTitle(shortPosterHeadline);
  latestNaverBlogPasteText = buildNaverBlogPasteText(input, recommendation, copy, publishHashtags);
  setText("#overlay-headline", shortPosterHeadline);
  setText("#instagram-caption", recommendation.caption || recommendation.publish_body || copy.body_copies[0]);
  setText("#publish-cta", recommendation.publish_cta || copy.ctas[0]);
  setText("#publish-hashtags", publishHashtags);
  setText("#publish-title", recommendation.publish_title || headline);
  setText(
    "#publish-body",
    input.copy.channel === "naver_blog"
      ? latestNaverBlogPasteText
      : recommendation.publish_body ||
      [recommendation.caption || copy.body_copies[0], recommendation.publish_cta || copy.ctas[0], publishHashtags]
        .filter(Boolean)
        .join("\n\n"),
  );
  setText("#promotion-template", recommendation.promotion_template || "");
  const blogSections = recommendation.blog_sections?.length
    ? recommendation.blog_sections
        .map((section, index) => {
          const title = section.title || `섹션 ${index + 1}`;
          const photo = section.photo || "사진 없음";
          const body = section.body || "";
          return `${index + 1}. ${title}\n(${photo})\n${body}`;
        })
        .join("\n\n")
    : "";
  const blogLayout = [
    recommendation.blog_title ? `제목: ${recommendation.blog_title}` : "",
    recommendation.thumbnail_photo
      ? `썸네일: ${recommendation.thumbnail_photo}\n추천 이유: ${recommendation.thumbnail_reason || ""}`
      : "",
    blogSections,
  ]
    .filter(Boolean)
    .join("\n\n");
  setText("#blog-layout", blogLayout);
  const blogLayoutElement = $("#blog-layout");
  const blogLayoutLabel = $("#blog-layout-label");
  const blogCopyPreview = $("#naver-blog-copy-preview");
  const blogCopyLabel = $("#naver-blog-copy-label");
  if (blogLayoutElement) blogLayoutElement.hidden = !blogLayout;
  if (blogLayoutLabel) blogLayoutLabel.hidden = !blogLayout;
  if (blogCopyPreview) {
    blogCopyPreview.textContent = latestNaverBlogPasteText;
    blogCopyPreview.hidden = !latestNaverBlogPasteText;
  }
  if (blogCopyLabel) blogCopyLabel.hidden = !latestNaverBlogPasteText;
  if (copyNaverBlogButton) copyNaverBlogButton.hidden = !latestNaverBlogPasteText;
  setText("#channel-writing", recommendation.writing_direction);
  setText("#channel-image", recommendation.image_direction);
  setText("#channel-placement", recommendation.placement_tip);
  setText("#image-insert-guide", recommendation.image_insert_guide);
  setText("#poster-headline", posterTitle.headline);
  setText("#poster-subtitle", posterTitle.subtitle);
  setText("#safety-copy", copy.safety_notes[0] || "금지 표현이 발견되지 않았습니다.");
  setText("#result-copy-model", `${copy.model} · ${formatLatencySeconds(copy.latency_ms)}`);
  setText("#result-image-model", `${image.model} · ${formatLatencySeconds(image.latency_ms)}`);
  setText("#image-caption", result.image_prompt);
  $("#generated-image").src = `data:${image.media_type};base64,${image.image_base64}`;
  if (voiceScript) {
    voiceScript.value = [headline, copy.body_copies[0], copy.ctas[0]].filter(Boolean).join("\n\n");
    updateVoiceScriptCount();
  }
  resetVoiceResult();

  payloadPreview.textContent = JSON.stringify(
    {
      model_1_input: input.copy,
      audience_detail: input.audience,
      model_1_output: copy,
      model_2_input: {
        model: input.image_model,
        prompt: result.image_prompt,
        negative_prompt: result.negative_prompt,
        width: input.image_width,
        height: input.image_height,
      },
      validation: result.validation,
      models: result.models,
      model_2_output: {
        model: image.model,
        media_type: image.media_type,
        latency_ms: image.latency_ms,
      },
    },
    null,
    2,
  );

  showGeneratedState();
  outputPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function showError(error) {
  setStage(3, "error", "실패");
  runState.textContent = "실패";
  runState.className = "run-state";
  errorMessage.textContent = error.message;
  errorBox.hidden = false;
  if (!hasGeneratedAd) {
    showEmptyState();
    errorBox.hidden = false;
  }
  generateButton.disabled = false;
  generateButton.firstElementChild.textContent = "다시 생성";
}

async function runPipeline(input) {
  resetPipeline();
  runState.textContent = "처리 중";
  runState.className = "run-state running";
  generateButton.disabled = true;
  generateButton.firstElementChild.textContent = "모델 호출 중...";

  setStage(0, "active", "입력 확인");
  await wait(200);
  setStage(0, "complete", "완료");
  setStage(1, "active", copyModelSelect.selectedOptions[0]?.textContent || "호출 중");

  let result;
  try {
    result = normalizeContentResult(await generateContent(input));
  } catch (error) {
    showError(error);
    return;
  }

  setStage(1, "complete", `${formatLatencySeconds(result.copy.latency_ms)} · 완료`);
  setStage(2, "complete", "프롬프트 변환 완료");
  setStage(3, "complete", `${formatLatencySeconds(result.image.latency_ms)} · 완료`);
  runState.textContent = `완료 · ${formatLatencySeconds(
    (result.copy.latency_ms || 0) + (result.image.latency_ms || 0),
  )}`;
  runState.className = "run-state complete";
  generateButton.disabled = false;
  generateButton.firstElementChild.textContent = "다른 광고 생성";
  renderResult(input, result);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = await readForm();
  if (input.copy.product_names.length === 0) {
    window.alert("상품을 하나 이상 입력해 주세요.");
    return;
  }
  if (input.copy.age_groups.length === 0) {
    window.alert("나이대를 하나 선택해 주세요.");
    return;
  }
  if (input.copy.target_audiences.length === 0) {
    window.alert("타겟을 하나 이상 선택해 주세요.");
    return;
  }
  await runPipeline(input);
});

copyModelSelect.addEventListener("change", updateModelHelp);
visionModelSelect.addEventListener("change", updateModelHelp);
imageModelSelect.addEventListener("change", updateModelHelp);
referenceImageInput?.addEventListener("change", updateReferencePreview);
referenceCutoutToggle?.addEventListener("change", updateReferencePreview);
referencePreviewClear?.addEventListener("click", clearReferencePreview);
channelSelect?.addEventListener("change", updateChannelMode);
addProductButton?.addEventListener("click", addProductRow);
openAdStudioButton?.addEventListener("click", showAdStudio);
backToServicesButton?.addEventListener("click", showServiceSelection);

resetButton.addEventListener("click", () => {
  form.reset();
  latestNaverBlogPasteText = "";
  clearReferencePreview();
  resetPipeline();
  updateModelHelp();
  runState.textContent = "대기";
  runState.className = "run-state";
  payloadPreview.textContent = "아직 생성된 데이터가 없습니다.";
  const blogCopyPreview = $("#naver-blog-copy-preview");
  const blogCopyLabel = $("#naver-blog-copy-label");
  if (blogCopyPreview) blogCopyPreview.hidden = true;
  if (blogCopyLabel) blogCopyLabel.hidden = true;
  if (copyNaverBlogButton) copyNaverBlogButton.hidden = true;
  showEmptyState();
  generateButton.disabled = false;
  generateButton.firstElementChild.textContent = "광고 콘텐츠 생성";
  if (voiceScript) voiceScript.value = "";
  updateVoiceScriptCount();
  resetVoiceResult();
});

voiceScript?.addEventListener("input", updateVoiceScriptCount);
voiceSpeed?.addEventListener("input", () => {
  if (voiceSpeedValue) voiceSpeedValue.textContent = `${Number(voiceSpeed.value).toFixed(2).replace(/0$/, "")}×`;
});

generateVoiceButton?.addEventListener("click", async () => {
  const input = voiceScript?.value.trim() || "";
  if (!input) {
    voiceScript?.focus();
    return;
  }

  generateVoiceButton.disabled = true;
  generateVoiceButton.textContent = "음성 생성 중...";
  voiceError.hidden = true;
  voiceOutput.hidden = true;
  voiceState.textContent = "생성 중";
  voiceState.className = "voice-state running";

  try {
    const result = await generateAudio({
      input,
      voice: voiceSelect.value,
      instructions: voiceInstructions.value.trim() || null,
      speed: Number(voiceSpeed.value),
    });
    generatedVoiceDataUrl = `data:${result.media_type};base64,${result.audio_base64}`;
    generatedVoiceExtension = result.media_type === "audio/wav" ? "wav" : "mp3";
    voicePlayer.src = generatedVoiceDataUrl;
    voiceOutput.hidden = false;
    voiceState.textContent = result.fallback_used ? "완료 · 대체 모델 사용" : "완료";
    voiceState.className = "voice-state";
    setText(
      "#result-audio-model",
      `${result.provider || "openai"} · ${result.model} · ${result.voice} · ${formatLatencySeconds(result.latency_ms)}`,
    );
    downloadVoiceButton.textContent = `${generatedVoiceExtension.toUpperCase()} 저장`;
  } catch (error) {
    voiceState.textContent = "실패";
    voiceState.className = "voice-state error";
    voiceError.textContent = error.message;
    voiceError.hidden = false;
  } finally {
    generateVoiceButton.disabled = false;
    generateVoiceButton.textContent = "음성 광고 다시 생성";
  }
});

downloadVoiceButton?.addEventListener("click", () => {
  if (!generatedVoiceDataUrl) return;
  const link = document.createElement("a");
  link.href = generatedVoiceDataUrl;
  link.download = `brandmate-voice-ad-${Date.now()}.${generatedVoiceExtension}`;
  link.click();
});

downloadPosterButton?.addEventListener("click", async () => {
  try {
    await downloadMergedPoster();
  } catch (error) {
    window.alert(error.message);
  }
});

copyPosterButton?.addEventListener("click", async () => {
  try {
    await copyMergedPoster();
    copyPosterButton.textContent = "복사 완료";
    window.setTimeout(() => {
      copyPosterButton.textContent = "이미지+글자 복사";
    }, 1600);
  } catch (error) {
    window.alert(error.message);
  }
});

copyNaverBlogButton?.addEventListener("click", async () => {
  try {
    await copyNaverBlogPasteText();
    copyNaverBlogButton.textContent = "블로그 원고 복사 완료";
    window.setTimeout(() => {
      copyNaverBlogButton.textContent = "네이버 블로그 원고 복사";
    }, 1600);
  } catch (error) {
    window.alert(error.message);
  }
});

loginTab.addEventListener("click", () => setAuthMode("login"));
signupTab.addEventListener("click", () => setAuthMode("signup"));
forgotPasswordButton.addEventListener("click", () => setAuthMode("forgot"));
[...document.querySelectorAll(".auth-back-button")].forEach((button) => {
  button.addEventListener("click", () => setAuthMode("login"));
});
authDialog.addEventListener("cancel", (event) => event.preventDefault());

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.hidden = true;
  setFormBusy(loginForm, true);
  const data = new FormData(loginForm);
  try {
    const session = await authRequest("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: data.get("email"),
        password: data.get("password"),
      }),
    });
    loginForm.reset();
    showAuthenticated(session);
    await Promise.all([loadModels(), loadAudioProviders()]);
  } catch (error) {
    loginError.textContent = error.message;
    loginError.hidden = false;
  } finally {
    setFormBusy(loginForm, false);
  }
});

signupForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  signupError.hidden = true;
  const data = new FormData(signupForm);
  if (data.get("password") !== data.get("passwordConfirm")) {
    signupError.textContent = "비밀번호가 일치하지 않습니다.";
    signupError.hidden = false;
    return;
  }
  setFormBusy(signupForm, true);
  try {
    const credentials = {
      email: data.get("email"),
      password: data.get("password"),
    };
    const created = await authRequest("/auth/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ...credentials,
        display_name: data.get("displayName"),
      }),
    });
    if (!created.user.email_verified) {
      $("#login-email").value = credentials.email;
      signupForm.reset();
      showAuthGate("인증 메일을 보냈습니다. 이메일의 링크를 확인해 주세요.", true);
      return;
    }
    const session = await authRequest("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(credentials),
    });
    signupForm.reset();
    showAuthenticated(session);
    await Promise.all([loadModels(), loadAudioProviders()]);
  } catch (error) {
    signupError.textContent = error.message;
    signupError.hidden = false;
  } finally {
    setFormBusy(signupForm, false);
  }
});

forgotPasswordForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setFormBusy(forgotPasswordForm, true);
  forgotPasswordError.hidden = true;
  forgotPasswordError.classList.remove("auth-notice");
  const data = new FormData(forgotPasswordForm);
  try {
    const result = await authRequest("/auth/password-reset/request", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: data.get("email") }),
    });
    forgotPasswordError.textContent = result.message;
    forgotPasswordError.classList.add("auth-notice");
    forgotPasswordError.hidden = false;
  } catch (error) {
    forgotPasswordError.textContent = error.message;
    forgotPasswordError.hidden = false;
  } finally {
    setFormBusy(forgotPasswordForm, false);
  }
});

resetPasswordForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  resetPasswordError.hidden = true;
  const data = new FormData(resetPasswordForm);
  if (data.get("password") !== data.get("passwordConfirm")) {
    resetPasswordError.textContent = "비밀번호가 일치하지 않습니다.";
    resetPasswordError.hidden = false;
    return;
  }
  setFormBusy(resetPasswordForm, true);
  try {
    await authRequest("/auth/password-reset/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token: pendingResetToken,
        new_password: data.get("password"),
      }),
    });
    pendingResetToken = null;
    window.history.replaceState(
      {},
      "",
      `${window.location.pathname}${window.location.search}`,
    );
    resetPasswordForm.reset();
    showAuthGate("비밀번호가 변경되었습니다. 새 비밀번호로 로그인해 주세요.", true);
  } catch (error) {
    resetPasswordError.textContent = error.message;
    resetPasswordError.hidden = false;
  } finally {
    setFormBusy(resetPasswordForm, false);
  }
});

securityButton.addEventListener("click", async () => {
  securityButton.disabled = true;
  try {
    await loadSessions();
    securityDialog.showModal();
  } catch (error) {
    window.alert(error.message);
  } finally {
    securityButton.disabled = false;
  }
});

securityCloseButton.addEventListener("click", () => securityDialog.close());

changePasswordForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  changePasswordError.hidden = true;
  const data = new FormData(changePasswordForm);
  if (data.get("newPassword") !== data.get("newPasswordConfirm")) {
    changePasswordError.textContent = "새 비밀번호가 일치하지 않습니다.";
    changePasswordError.hidden = false;
    return;
  }
  setFormBusy(changePasswordForm, true);
  try {
    await fetchJson("/auth/password/change", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_password: data.get("currentPassword"),
        new_password: data.get("newPassword"),
      }),
    });
    changePasswordForm.reset();
    securityDialog.close();
    showAuthGate("비밀번호가 변경되어 모든 기기에서 로그아웃되었습니다.", true);
  } catch (error) {
    changePasswordError.textContent = error.message;
    changePasswordError.hidden = false;
  } finally {
    setFormBusy(changePasswordForm, false);
  }
});

logoutButton.addEventListener("click", async () => {
  logoutButton.disabled = true;
  try {
    await authRequest("/auth/logout", { method: "POST" });
  } finally {
    logoutButton.disabled = false;
    showAuthGate();
  }
});

showEmptyState();
updateChannelMode();
bootstrapAuth();
