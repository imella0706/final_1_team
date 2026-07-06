const API_BASE_URL = "http://localhost:8000/api/v1";

const form = document.querySelector("#ad-form");
const modelSelect = document.querySelector("#copy-model");
const modelHelp = document.querySelector("#model-help");
const apiConnection = document.querySelector("#api-connection");
const resetButton = document.querySelector("#reset-button");
const generateButton = form.querySelector(".generate-button");
const runState = document.querySelector("#run-state");
const pipeline = [...document.querySelectorAll("#pipeline li")];
const pipelineModel = document.querySelector("#pipeline-model");
const payloadPreview = document.querySelector("#payload-preview");
const errorBox = document.querySelector("#error-box");
const errorMessage = document.querySelector("#error-message");
const outputPanel = document.querySelector("#output-panel");
const emptyState = document.querySelector("#empty-state");
const generatedContent = document.querySelector("#generated-content");

const labelMaps = {
  businessType: {
    카페: "cafe",
    베이커리: "bakery",
    디저트: "dessert",
    음식점: "restaurant",
    주점: "pub",
  },
  situation: {
    신메뉴: "new_menu",
    할인: "discount",
    이벤트: "event",
    배달: "delivery",
    포장: "takeout",
    "방문 유도": "visit",
  },
  target: {
    "10대": "teens",
    "20대": "twenties",
    직장인: "office_workers",
    가족: "families",
    커플: "couples",
  },
  tone: {
    감성적: "emotional",
    친근한: "friendly",
    재치있는: "playful",
    고급스러운: "premium",
  },
  channel: {
    인스타그램: "instagram",
    "네이버 블로그": "naver_blog",
    배달앱: "delivery_app",
    "매장 포스터": "store_poster",
  },
};

const shortModelNames = {
  "Qwen/Qwen2.5-7B-Instruct": "Qwen 2.5 7B",
  "meta-llama/Llama-3.1-8B-Instruct": "Llama 3.1 8B",
  "nvidia/meta/llama-3.1-8b-instruct": "NVIDIA Llama 3.1 8B",
  "mistralai/Mistral-7B-Instruct-v0.3": "Mistral 7B v0.3",
  "google/gemma-2-9b-it": "Gemma 2 9B",
  "microsoft/Phi-4-mini-instruct": "Phi 4 Mini",
  "upstage/SOLAR-10.7B-Instruct-v1.0": "SOLAR 10.7B",
};

const availabilityLabels = {
  hosted: "",
  gated: " · 접근 동의",
  local_only: " · 로컬 전용",
  research_only: " · 연구 전용",
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

function readForm() {
  const data = new FormData(form);
  const display = {
    businessType: data.get("businessType"),
    situation: data.get("situation"),
    targets: data.getAll("target"),
    tone: data.get("tone"),
    channel: data.get("channel"),
  };

  return {
    request: {
      model: data.get("model"),
      business_name: data.get("businessName").trim(),
      business_type: labelMaps.businessType[display.businessType],
      situation: labelMaps.situation[display.situation],
      target_audiences: display.targets.map((target) => labelMaps.target[target]),
      tone: labelMaps.tone[display.tone],
      product_names: commaList(data.get("products")),
      features: data
        .get("features")
        .split("\n")
        .map((item) => item.trim())
        .filter(Boolean),
      channel: labelMaps.channel[display.channel],
      promotion: null,
      required_terms: [],
      prohibited_terms: commaList(data.get("prohibited")),
    },
    display,
  };
}

async function requestAdCopy(request) {
  const response = await fetch(`${API_BASE_URL}/ad-copies/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });

  let body;
  try {
    body = await response.json();
  } catch {
    body = {};
  }

  if (!response.ok) {
    throw new Error(body.detail || `API 오류 (${response.status})`);
  }
  return body;
}

function setStage(index, state, label) {
  const item = pipeline[index];
  item.classList.remove("active", "complete", "error");
  if (state) item.classList.add(state);
  item.querySelector(".stage-state").textContent = label;
  if (state === "complete") item.querySelector(".pipeline-icon").textContent = "✓";
  if (state === "error") item.querySelector(".pipeline-icon").textContent = "!";
}

function resetPipeline() {
  const icons = ["IN", "M1", "→", "M2"];
  pipeline.forEach((item, index) => {
    item.classList.remove("active", "complete", "error");
    item.querySelector(".stage-state").textContent = "대기";
    item.querySelector(".pipeline-icon").textContent = icons[index];
  });
  errorBox.hidden = true;
}

function showError(error) {
  setStage(1, "error", "호출 실패");
  runState.textContent = "실패";
  runState.className = "run-state";
  errorMessage.textContent = error.message;
  errorBox.hidden = false;
  generateButton.disabled = false;
  generateButton.firstElementChild.textContent = "다시 시도";
}

async function runPipeline(input) {
  resetPipeline();
  runState.textContent = "처리 중";
  runState.className = "run-state running";
  generateButton.disabled = true;
  generateButton.firstElementChild.textContent = "선택한 LLM을 호출하는 중...";

  setStage(0, "active", "입력 확인 중");
  await wait(250);
  setStage(0, "complete", "구조화 완료");

  const modelName = shortModelNames[input.request.model];
  pipelineModel.textContent = `${modelName} · 실제 호출`;
  setStage(1, "active", `${modelName} 호출 중`);

  let result;
  try {
    result = await requestAdCopy(input.request);
  } catch (error) {
    showError(error);
    return;
  }

  setStage(1, "complete", `${(result.latency_ms / 1000).toFixed(1)}초 · 완료`);
  setStage(2, "active", "프롬프트 변환 중");
  await wait(350);
  setStage(2, "complete", "전달 완료");
  setStage(3, "active", "모의 이미지 생성 중");
  await wait(700);
  setStage(3, "complete", "모의 시안 완료");

  runState.textContent = `전체 완료 · ${(result.latency_ms / 1000).toFixed(1)}초`;
  runState.className = "run-state complete";
  generateButton.disabled = false;
  generateButton.firstElementChild.textContent = "다른 광고 다시 생성";
  renderResult(input, result);
}

function renderResult(input, result) {
  const { display, request } = input;
  document.querySelector("#context-line").textContent =
    `${display.businessType} · ${display.situation} · ${display.targets.join(", ")}`;
  document.querySelector("#headline").textContent = result.headlines[0];
  document.querySelector("#body-copy").textContent = result.body_copies[0];
  document.querySelector("#cta").textContent = result.ctas[0];
  document.querySelector("#safety-copy").textContent =
    result.safety_notes[0] || "지정한 기피 표현이 발견되지 않았습니다.";
  document.querySelector("#result-model").textContent =
    `${shortModelNames[result.model] || result.model} · ${result.provider} · ${result.latency_ms}ms`;

  const hashtags = document.querySelector("#hashtags");
  hashtags.replaceChildren();
  result.hashtags.forEach((hashtag) => {
    const chip = document.createElement("span");
    chip.textContent = hashtag;
    hashtags.append(chip);
  });

  document.querySelector("#poster-category").textContent =
    `${display.businessType.toUpperCase()} · ${display.situation.toUpperCase()}`;
  document.querySelector("#poster-business").textContent = request.business_name;
  document.querySelector("#poster-headline").textContent = result.headlines[0];
  document.querySelector("#poster-products").textContent = request.product_names.join(" · ");

  payloadPreview.textContent = JSON.stringify(
    {
      model_1_input: request,
      model_1_output: result,
      model_2_input: {
        prompt: result.image_prompt,
        aspect_ratio: "4:5",
        text_rendering: false,
      },
      model_2_output: {
        status: "mocked",
        asset: "css-preview",
      },
    },
    null,
    2,
  );

  emptyState.hidden = true;
  generatedContent.hidden = false;
  outputPanel.classList.remove("is-empty");
  outputPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function checkApiConnection() {
  try {
    const response = await fetch(`${API_BASE_URL}/ad-copies/models`);
    if (!response.ok) throw new Error();
    const models = await response.json();
    const selectedModel = modelSelect.value;

    modelSelect.replaceChildren();
    models.forEach((model) => {
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent =
        `${model.name} · ${model.size}${availabilityLabels[model.availability] || ""}`;
      option.dataset.note = `${model.recommended ? "추천 · " : ""}${model.note}`;
      option.selected = model.id === selectedModel;
      modelSelect.append(option);
    });

    updateModelDescription();
    apiConnection.textContent = "API 연결됨";
    apiConnection.className = "online";
  } catch {
    apiConnection.textContent = "API 연결 안 됨";
    apiConnection.className = "offline";
  }
}

function updateModelDescription() {
  const option = modelSelect.selectedOptions[0];
  modelHelp.textContent = option.dataset.note;
  pipelineModel.textContent = `${shortModelNames[option.value]} · 실제 호출`;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = readForm();
  if (input.request.target_audiences.length === 0) {
    window.alert("타겟을 한 명 이상 선택해주세요.");
    return;
  }
  await runPipeline(input);
});

modelSelect.addEventListener("change", updateModelDescription);

resetButton.addEventListener("click", () => {
  form.reset();
  resetPipeline();
  updateModelDescription();
  runState.textContent = "실행 전";
  runState.className = "run-state";
  payloadPreview.textContent = "아직 생성된 데이터가 없습니다.";
  generatedContent.hidden = true;
  emptyState.hidden = false;
  outputPanel.classList.add("is-empty");
  generateButton.disabled = false;
  generateButton.firstElementChild.textContent = "광고 생성 테스트";
});

updateModelDescription();
checkApiConnection();
