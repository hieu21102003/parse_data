const $ = (selector) => document.querySelector(selector);
const resultsEl = $("#results");
const feedbackEl = $("#feedback");
const fileInput = $("#file-input");
const selectedFiles = $("#selected-files");

function setBusy(button, busy, label) {
  button.disabled = busy;
  button.dataset.originalLabel ||= button.querySelector("span").textContent;
  button.querySelector("span").textContent = busy ? label : button.dataset.originalLabel;
}

function showFeedback(message, kind = "loading") {
  feedbackEl.textContent = message;
  feedbackEl.className = `feedback ${kind}`;
  feedbackEl.hidden = false;
}

function clearFeedback() {
  feedbackEl.hidden = true;
  feedbackEl.textContent = "";
}

function safeText(value, fallback = "—") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function renderResults(data, label) {
  clearFeedback();
  resultsEl.replaceChildren();
  const records = data.records || [];
  const heading = document.createElement("div");
  heading.className = "result-heading";
  const title = document.createElement("h2");
  title.textContent = label;
  const count = document.createElement("span");
  count.textContent = `${data.count ?? records.length} kết quả`;
  heading.append(title, count);
  resultsEl.append(heading);

  if (!records.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Chưa tìm thấy mã tiêu chuẩn trong nội dung này. Thử nhập mã rõ hơn hoặc tải tài liệu có văn bản.";
    resultsEl.append(empty);
    return;
  }

  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  const table = document.createElement("table");
  table.className = "results-table";
  const columns = [
    { key: "stt", label: "STT", className: "col-stt" },
    { key: "parent_level_1", label: "Cấp 1 (Nhóm)", className: "col-parent-1" },
    { key: "parent_level_2", label: "Cấp 2 (Tiểu mục)", className: "col-parent-2" },
    { key: "standard_name", label: "Tên tiêu chuẩn", className: "col-name" },
    { key: "raw_text", label: "Mã trong file", className: "col-raw" },
    { key: "corrected_code", label: "Mã đã parse", className: "col-code" },
    { key: "organization", label: "Tổ chức", className: "col-org" },
    { key: "main_number", label: "Số hiệu", className: "col-main" },
    { key: "year", label: "Năm", className: "col-year" },
    { key: "parts", label: "Phần", className: "col-parts" },
    { key: "status", label: "Trạng thái", className: "col-status" },
  ];
  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  for (const col of columns) {
    const th = document.createElement("th");
    th.scope = "col";
    th.className = col.className;
    th.textContent = col.label;
    headerRow.append(th);
  }
  thead.append(headerRow);
  const tbody = document.createElement("tbody");
  for (const record of records) {
    const row = document.createElement("tr");
    for (const col of columns) {
      const cell = document.createElement("td");
      cell.className = col.className;
      if (col.key === "status") {
        const badge = document.createElement("span");
        badge.className = `badge ${record.verified ? "verified" : "unverified"}`;
        badge.textContent = record.verified ? "Đủ tin cậy" : "Cần đối chiếu";
        cell.append(badge);
      } else {
        cell.textContent = safeText(record[col.key]);
      }
      row.append(cell);
    }
    tbody.append(row);

    if (record.explanation) {
      const noteRow = document.createElement("tr");
      noteRow.className = "explanation-row";
      const noteCell = document.createElement("td");
      noteCell.colSpan = columns.length;
      noteCell.textContent = record.source_file ? `${record.source_file} · ${record.explanation}` : record.explanation;
      noteRow.append(noteCell);
      tbody.append(noteRow);
    }
  }
  table.append(thead, tbody);
  wrap.append(table);
  resultsEl.append(wrap);
}

async function parseRequest(url, options, button, busyLabel, resultLabel) {
  setBusy(button, true, busyLabel);
  resultsEl.replaceChildren();
  showFeedback("Đang phân tích nội dung…");
  try {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || "Có lỗi khi phân tích.");
    renderResults(data, resultLabel);
  } catch (error) {
    showFeedback(error.message || "Không kết nối được tới máy chủ.", "error");
  } finally {
    setBusy(button, false, busyLabel);
  }
}

$("#tab-chat").addEventListener("click", () => switchMode("chat"));
$("#tab-upload").addEventListener("click", () => switchMode("upload"));
function switchMode(mode) {
  const chat = mode === "chat";
  $("#tab-chat").classList.toggle("active", chat);
  $("#tab-upload").classList.toggle("active", !chat);
  $("#tab-chat").setAttribute("aria-selected", String(chat));
  $("#tab-upload").setAttribute("aria-selected", String(!chat));
  $("#panel-chat").hidden = !chat;
  $("#panel-upload").hidden = chat;
  $("#panel-chat").classList.toggle("hidden", !chat);
  $("#panel-upload").classList.toggle("hidden", chat);
}

$("#text-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button[type=submit]");
  parseRequest("/api/parse/text", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: $("#text-input").value, use_ai_fallback: $("#ai-text").checked }),
  }, button, "Đang phân tích…", "Kết quả phân tích");
});

document.querySelectorAll(".suggestion").forEach((button) => button.addEventListener("click", () => {
  $("#text-input").value = button.dataset.value;
  $("#text-input").focus();
}));

function showSelectedFiles() {
  selectedFiles.replaceChildren();
  for (const file of fileInput.files || []) {
    const chip = document.createElement("div");
    chip.className = "file-chip";
    const icon = document.createElement("span");
    icon.className = "doc-icon";
    icon.textContent = "▤";
    const name = document.createElement("span");
    name.textContent = file.name;
    const size = document.createElement("small");
    size.textContent = `${(file.size / 1024 / 1024).toFixed(2)} MB`;
    chip.append(icon, name, size);
    selectedFiles.append(chip);
  }
}
fileInput.addEventListener("change", showSelectedFiles);

const dropzone = $("#dropzone");
for (const eventName of ["dragenter", "dragover"]) dropzone.addEventListener(eventName, (event) => {
  event.preventDefault();
  dropzone.classList.add("dragover");
});
for (const eventName of ["dragleave", "drop"]) dropzone.addEventListener(eventName, (event) => {
  event.preventDefault();
  dropzone.classList.remove("dragover");
});
dropzone.addEventListener("drop", (event) => {
  const transfer = new DataTransfer();
  for (const file of event.dataTransfer.files) transfer.items.add(file);
  fileInput.files = transfer.files;
  showSelectedFiles();
});

$("#file-form").addEventListener("submit", (event) => {
  event.preventDefault();
  if (!fileInput.files.length) {
    showFeedback("Hãy chọn ít nhất một tài liệu để phân tích.", "error");
    return;
  }
  const body = new FormData();
  for (const file of fileInput.files) body.append("files", file);
  body.append("use_ai_fallback", String($("#ai-file").checked));
  const button = event.currentTarget.querySelector("button[type=submit]");
  parseRequest("/api/parse/files", { method: "POST", body }, button, "Đang đọc tài liệu…", "Kết quả từ tài liệu");
});
