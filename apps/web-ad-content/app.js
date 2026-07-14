// [Design Intent] 정적 HTML 테스트 환경에서는 빌드 타임 env가 없으므로
// 실행 대상에 맞는 API URL 한 줄만 활성화한다.
// const API_BASE_URL = "http://34.55.162.157:7660/api/v1"; // GCP 서버 테스트용
const API_BASE_URL = "http://127.0.0.1:7660/api/v1"; // 로컬 FastAPI 테스트용
// const API_BASE_URL = "http://127.0.0.1:8000/api/v1"; // 로컬 FastAPI를 8000번으로 띄운 경우

const $ = (selector) => document.querySelector(selector);

const form = $("#ad-form");
const copyModelSelect = $("#copy-model");
const imageModelSelect = $("#image-model");
const copyModelHelp = $("#copy-model-help");
const imageModelHelp = $("#image-model-help");
const apiState = $("#api-state");
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
const artifactBox = $("#artifact-box");
const artifactDirectory = $("#artifact-directory");
const artifactJson = $("#artifact-json");
const artifactImage = $("#artifact-image");
const artifactPrompt = $("#artifact-prompt");
const referenceImageInput = $("#reference-image");
const referencePreview = $("#reference-preview");
const referencePreviewImage = $("#reference-preview-image");
const referencePreviewName = $("#reference-preview-name");
const referencePreviewMeta = $("#reference-preview-meta");
const referencePreviewClear = $("#reference-preview-clear");
const referenceCutoutToggle = $("#reference-cutout");

let hasGeneratedAd = false;
let referencePreviewDataUrl = null;

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

function setText(selector, text) {
  $(selector).textContent = text || "";
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

  if (referencePreviewDataUrl) {
    return referencePreviewDataUrl;
  }
  return buildReferenceDataUrl(file);
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
  const file = referenceImageInput?.files?.[0];
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
    referencePreviewDataUrl = await buildReferenceDataUrl(file);
    referencePreviewImage.src = referencePreviewDataUrl;
    if (referencePreviewName) referencePreviewName.textContent = file.name;
    if (referencePreviewMeta) {
      const mode = referenceCutoutToggle?.checked ? "제품만 추출" : "원본";
      referencePreviewMeta.textContent = `${mode} · ${file.type || "image"} · ${formatFileSize(file.size)}`;
    }
    referencePreview.hidden = false;
  } catch (error) {
    window.alert(error.message);
    clearReferencePreview();
  }
}

async function readForm() {
  const data = new FormData(form);
  const referenceImageDataUrl = await readReferenceImage();
  const gender = data.get("gender") || "all";
  const occupationGroup = data.get("occupationGroup") || "none";
  const productPrice = data.get("productPrice");
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
      product_names: commaList(data.get("products")),
      features: [...baseFeatures, ...audienceContext].slice(0, 10),
      channel: data.get("channel"),
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
    image_width: 1024,
    image_height: 1280,
    reference_image_data_url: referenceImageDataUrl,
  };
}

async function fetchJson(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, options);
  let body = {};
  try {
    body = await response.json();
  } catch {
    body = {};
  }
  if (!response.ok) {
    throw new Error(body.detail || `API error (${response.status})`);
  }
  return body;
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

function updateModelHelp() {
  const copyOption = copyModelSelect.selectedOptions[0];
  const imageOption = imageModelSelect.selectedOptions[0];
  copyModelHelp.textContent = copyOption?.dataset.note || "광고 문구 모델을 선택해 주세요.";
  imageModelHelp.textContent = imageOption?.dataset.note || "이미지 생성 모델을 선택해 주세요.";
}

async function loadModels() {
  try {
    const [copyModels, imageModels] = await Promise.all([
      fetchJson("/ad-copies/models"),
      fetchJson("/ad-content/image-models"),
    ]);
    fillSelect(copyModelSelect, copyModels);
    fillSelect(imageModelSelect, imageModels);
    updateModelHelp();
    apiState.textContent = "API 연결됨";
    apiState.className = "online";
  } catch (error) {
    apiState.textContent = "API 연결 실패";
    apiState.className = "offline";
    copyModelHelp.textContent = error.message;
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

function renderResult(input, result) {
  const { copy, image } = result;
  const headline = copy.headlines[0] || "";
  const hashtags = copy.hashtags?.length ? copy.hashtags.join(" ") : "#광고 #이벤트";

  setText("#context-line", buildContextLine(input));
  setText("#headline", headline);
  setText("#body-copy", copy.body_copies[0]);
  setText("#cta", copy.ctas[0]);
  setText("#hashtags", hashtags);
  setText("#poster-headline", headline);
  setText("#safety-copy", copy.safety_notes[0] || "금지 표현이 발견되지 않았습니다.");
  setText("#result-copy-model", `${copy.model} · ${formatLatencySeconds(copy.latency_ms)}`);
  setText("#result-image-model", `${image.model} · ${formatLatencySeconds(image.latency_ms)}`);
  setText("#image-caption", result.image_prompt);
  $("#generated-image").src = `data:${image.media_type};base64,${image.image_base64}`;

  if (result.artifacts && result.artifacts.directory) {
    artifactDirectory.textContent = `저장 폴더: ${result.artifacts.directory}`;
    artifactJson.textContent = `메타데이터 JSON: ${result.artifacts.metadata_json}`;
    artifactImage.textContent = `이미지 파일: ${result.artifacts.image}`;
    artifactPrompt.textContent = `이미지 프롬프트 텍스트: ${result.artifacts.image_prompt}`;
    artifactBox.hidden = false;
  } else {
    artifactBox.hidden = true;
  }

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
      artifacts: result.artifacts,
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
imageModelSelect.addEventListener("change", updateModelHelp);
referenceImageInput?.addEventListener("change", updateReferencePreview);
referenceCutoutToggle?.addEventListener("change", updateReferencePreview);
referencePreviewClear?.addEventListener("click", clearReferencePreview);

resetButton.addEventListener("click", () => {
  form.reset();
  clearReferencePreview();
  resetPipeline();
  updateModelHelp();
  runState.textContent = "대기";
  runState.className = "run-state";
  payloadPreview.textContent = "아직 생성된 데이터가 없습니다.";
  artifactBox.hidden = true;
  showEmptyState();
  generateButton.disabled = false;
  generateButton.firstElementChild.textContent = "광고 콘텐츠 생성";
});

showEmptyState();
loadModels();
