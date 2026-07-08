const API_BASE_URL = "http://localhost:8000/api/v1";

const form = document.querySelector("#ad-form");
const copyModelSelect = document.querySelector("#copy-model");
const imageModelSelect = document.querySelector("#image-model");
const copyModelHelp = document.querySelector("#copy-model-help");
const imageModelHelp = document.querySelector("#image-model-help");
const apiState = document.querySelector("#api-state");
const resetButton = document.querySelector("#reset-button");
const generateButton = form.querySelector(".generate-button");
const runState = document.querySelector("#run-state");
const pipelineItems = [...document.querySelectorAll("#pipeline li")];
const errorBox = document.querySelector("#error-box");
const errorMessage = document.querySelector("#error-message");
const payloadPreview = document.querySelector("#payload-preview");
const outputPanel = document.querySelector("#output-panel");
const emptyState = document.querySelector("#empty-state");
const generatedContent = document.querySelector("#generated-content");
const artifactBox = document.querySelector("#artifact-box");
const artifactDirectory = document.querySelector("#artifact-directory");
const artifactJson = document.querySelector("#artifact-json");
const artifactImage = document.querySelector("#artifact-image");
const artifactPrompt = document.querySelector("#artifact-prompt");
const referenceImageInput = document.querySelector("#reference-image");
const referencePreview = document.querySelector("#reference-preview");
const referencePreviewImage = document.querySelector("#reference-preview-image");
const referencePreviewName = document.querySelector("#reference-preview-name");
const referencePreviewMeta = document.querySelector("#reference-preview-meta");
const referencePreviewClear = document.querySelector("#reference-preview-clear");

let hasGeneratedAd = false;

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
    families: "가족",
    couples: "커플",
    solo: "혼자",
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

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("참고 이미지를 읽는 데 실패했습니다."));
    reader.readAsDataURL(file);
  });
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

  return readFileAsDataUrl(file);
}

function clearReferencePreview() {
  if (referenceImageInput) {
    referenceImageInput.value = "";
  }
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
    referencePreviewImage.src = await readFileAsDataUrl(file);
    if (referencePreviewName) referencePreviewName.textContent = file.name;
    if (referencePreviewMeta) {
      referencePreviewMeta.textContent = `${file.type || "image"} · ${formatFileSize(file.size)}`;
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
      features: data
        .get("features")
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean),
      channel: data.get("channel"),
      promotion: null,
      required_terms: [],
      prohibited_terms: commaList(data.get("prohibited")),
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
  const businessType = displayLabels.businessType[input.copy.business_type] || input.copy.business_type;
  const situation = displayLabels.situation[input.copy.situation] || input.copy.situation;
  const ageGroups = input.copy.age_groups
    .map((age) => displayLabels.ageGroup[age] || age)
    .join(", ");
  const targets = input.copy.target_audiences
    .map((target) => displayLabels.target[target] || target)
    .join(", ");

  document.querySelector("#context-line").textContent =
    `${businessType} · ${situation} · ${ageGroups} · ${targets}`;
  document.querySelector("#headline").textContent = copy.headlines[0];
  document.querySelector("#body-copy").textContent = copy.body_copies[0];
  document.querySelector("#cta").textContent = copy.ctas[0];
  const hashtags = copy.hashtags?.length ? copy.hashtags.join(" ") : "#광고 #이벤트";
  document.querySelector("#hashtags").textContent = hashtags;
  document.querySelector("#poster-business").textContent = input.copy.business_name;
  document.querySelector("#poster-headline").textContent = copy.headlines[0];
  document.querySelector("#poster-body").textContent = copy.body_copies[0];
  document.querySelector("#poster-cta").textContent = copy.ctas[0];
  document.querySelector("#poster-hashtags").textContent = hashtags;
  document.querySelector("#safety-copy").textContent =
    copy.safety_notes[0] || "금지 표현이 발견되지 않았습니다.";
  document.querySelector("#result-copy-model").textContent =
    `${copy.model} · ${formatLatencySeconds(copy.latency_ms)}`;
  document.querySelector("#result-image-model").textContent =
    `${image.model} · ${formatLatencySeconds(image.latency_ms)}`;
  document.querySelector("#generated-image").src =
    `data:${image.media_type};base64,${image.image_base64}`;
  document.querySelector("#image-caption").textContent = result.image_prompt;
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
    window.alert("나이대를 하나 이상 선택해 주세요.");
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
