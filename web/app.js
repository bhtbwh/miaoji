const TARGET_SAMPLE_RATE = 16000;
const SUMMARY_KEYS = ["会议摘要", "决策事项", "待办事项", "每个人负责什么", "风险/问题"];

const state = {
  socket: null,
  audioContext: null,
  mediaStream: null,
  sourceNode: null,
  processorNode: null,
  recording: false,
  paused: false,
  startedAt: 0,
  pausedMs: 0,
  pauseStartedAt: 0,
  durationTimer: 0,
  segmentCount: 0,
  meetingId: "",
  stopping: false,
  draftElement: null,
  currentSummary: null,
  summaryStatus: { state: "idle", last_updated_at: null, last_error: "", model: "" },
  summaryHistoryCount: 0,
};

const els = {
  connectionState: document.querySelector("#connectionState"),
  meetingTitle: document.querySelector("#meetingTitle"),
  startBtn: document.querySelector("#startBtn"),
  pauseBtn: document.querySelector("#pauseBtn"),
  stopBtn: document.querySelector("#stopBtn"),
  statusLine: document.querySelector("#statusLine"),
  levelBar: document.querySelector("#levelBar"),
  durationText: document.querySelector("#durationText"),
  transcriptList: document.querySelector("#transcriptList"),
  segmentCount: document.querySelector("#segmentCount"),
  summaryGrid: document.querySelector("#summaryGrid"),
  summaryState: document.querySelector("#summaryState"),
  summaryMeta: document.querySelector("#summaryMeta"),
  meetingList: document.querySelector("#meetingList"),
  refreshMeetingsBtn: document.querySelector("#refreshMeetingsBtn"),
};

renderSummary();
renderTranscriptEmpty();
loadMeetings();
registerServiceWorker();

els.startBtn.addEventListener("click", startRecording);
els.pauseBtn.addEventListener("click", togglePause);
els.stopBtn.addEventListener("click", stopRecording);
els.refreshMeetingsBtn.addEventListener("click", loadMeetings);

async function startRecording() {
  if (state.recording) return;
  if (!window.isSecureContext && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
    setStatus("手机浏览器需要 HTTPS 才能打开麦克风。请按 README 使用证书启动服务。", true);
    return;
  }

  setStatus("正在请求麦克风权限...");
  try {
    state.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: { ideal: 1 },
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false,
      },
      video: false,
    });

    state.audioContext = createAudioContext();
    state.sourceNode = state.audioContext.createMediaStreamSource(state.mediaStream);
    state.processorNode = state.audioContext.createScriptProcessor(4096, 1, 1);
    state.sourceNode.connect(state.processorNode);
    state.processorNode.connect(state.audioContext.destination);

    const wsUrl = buildRecorderUrl(els.meetingTitle.value.trim());
    state.socket = new WebSocket(wsUrl);
    state.socket.binaryType = "arraybuffer";
    bindSocket(state.socket);

    state.processorNode.onaudioprocess = (event) => {
      if (!state.recording || state.paused || !isSocketOpen()) return;
      const input = event.inputBuffer.getChannelData(0);
      updateMeter(input);
      const pcm = resampleToInt16(input, state.audioContext.sampleRate, TARGET_SAMPLE_RATE);
      if (pcm.byteLength > 0) {
        state.socket.send(pcm);
      }
    };

    state.recording = true;
    state.paused = false;
    state.startedAt = Date.now();
    state.pausedMs = 0;
    state.stopping = false;
    state.segmentCount = 0;
    state.meetingId = "";
    state.draftElement = null;
    state.currentSummary = null;
    state.summaryStatus = { state: "idle", last_updated_at: null, last_error: "", model: "" };
    state.summaryHistoryCount = 0;
    els.transcriptList.innerHTML = "";
    renderTranscriptEmpty();
    renderSummary();
    updateControls();
    tickDuration();
    state.durationTimer = window.setInterval(tickDuration, 500);
    setStatus("正在连接本地转写服务...");
  } catch (error) {
    cleanupAudio();
    setConnection("error", "失败");
    setStatus(`无法开始录音：${error.message || error}`, true);
    updateControls();
  }
}

function bindSocket(socket) {
  socket.addEventListener("open", () => {
    setConnection("live", "录音中");
    setStatus("连接成功，正在实时转写。");
  });

  socket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "meeting_started") {
      state.meetingId = payload.meeting.id;
      setStatus(`已创建会议：${payload.meeting.title}`);
    } else if (payload.type === "transcript") {
      appendSegment(payload.segment);
      if (payload.duration_seconds) {
        els.durationText.textContent = formatDuration(payload.duration_seconds * 1000);
      }
    } else if (payload.type === "summary") {
      updateSummary(payload);
    } else if (payload.type === "meeting_finished") {
      setStatus("会议已保存。");
      loadMeetings();
    } else if (payload.type === "error") {
      setConnection("error", "异常");
      setStatus(payload.message, true);
    }
  });

  socket.addEventListener("close", () => {
    if (state.recording && !state.stopping) {
      setStatus("连接已关闭，当前录音已停止。");
      stopRecording({ notifyServer: false });
    }
    setConnection("", "未连接");
  });

  socket.addEventListener("error", () => {
    setConnection("error", "异常");
    setStatus("WebSocket 连接失败，请确认电脑服务正在运行。", true);
  });
}

function togglePause() {
  if (!state.recording) return;
  state.paused = !state.paused;
  if (state.paused) {
    state.pauseStartedAt = Date.now();
    setConnection("", "已暂停");
    setStatus("录音已暂停。");
  } else {
    state.pausedMs += Date.now() - state.pauseStartedAt;
    setConnection("live", "录音中");
    setStatus("录音已继续。");
  }
  updateControls();
}

function stopRecording(options = { notifyServer: true }) {
  if (!state.recording && !state.socket) return;
  state.recording = false;
  state.paused = false;
  state.stopping = true;
  window.clearInterval(state.durationTimer);
  els.levelBar.style.width = "0%";

  if (options.notifyServer && isSocketOpen()) {
    state.socket.send(JSON.stringify({ type: "stop" }));
  }
  if (state.socket && state.socket.readyState <= WebSocket.OPEN) {
    window.setTimeout(() => state.socket?.close(), 250);
  }

  cleanupAudio();
  updateControls();
  setConnection("", "未连接");
  setStatus(state.meetingId ? "正在保存会议..." : "录音已结束。");
}

function cleanupAudio() {
  if (state.processorNode) {
    state.processorNode.disconnect();
    state.processorNode.onaudioprocess = null;
  }
  if (state.sourceNode) state.sourceNode.disconnect();
  if (state.mediaStream) {
    state.mediaStream.getTracks().forEach((track) => track.stop());
  }
  if (state.audioContext && state.audioContext.state !== "closed") {
    state.audioContext.close();
  }
  state.processorNode = null;
  state.sourceNode = null;
  state.mediaStream = null;
  state.audioContext = null;
}

function buildRecorderUrl(title) {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  const params = new URLSearchParams();
  if (title) params.set("title", title);
  return `${protocol}://${location.host}/ws/record?${params.toString()}`;
}

function resampleToInt16(input, inputRate, outputRate) {
  if (inputRate === outputRate) {
    return floatToInt16(input);
  }
  if (inputRate > outputRate) {
    return downsampleToInt16(input, inputRate, outputRate);
  }
  const ratio = inputRate / outputRate;
  const outputLength = Math.floor(input.length / ratio);
  const output = new Float32Array(outputLength);
  for (let i = 0; i < outputLength; i += 1) {
    const position = i * ratio;
    const before = Math.floor(position);
    const after = Math.min(before + 1, input.length - 1);
    const weight = position - before;
    output[i] = input[before] * (1 - weight) + input[after] * weight;
  }
  return floatToInt16(output);
}

function downsampleToInt16(input, inputRate, outputRate) {
  const ratio = inputRate / outputRate;
  const outputLength = Math.floor(input.length / ratio);
  const output = new Float32Array(outputLength);
  for (let i = 0; i < outputLength; i += 1) {
    const start = Math.floor(i * ratio);
    const end = Math.min(Math.floor((i + 1) * ratio), input.length);
    let sum = 0;
    let count = 0;
    for (let j = start; j < end; j += 1) {
      sum += input[j];
      count += 1;
    }
    output[i] = count ? sum / count : input[Math.min(start, input.length - 1)] || 0;
  }
  return floatToInt16(output);
}

function createAudioContext() {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  try {
    return new AudioContextClass({ sampleRate: TARGET_SAMPLE_RATE });
  } catch (_) {
    return new AudioContextClass();
  }
}

function floatToInt16(float32) {
  const buffer = new ArrayBuffer(float32.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < float32.length; i += 1) {
    const sample = Math.max(-1, Math.min(1, float32[i]));
    view.setInt16(i * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
  }
  return buffer;
}

function updateMeter(input) {
  let sum = 0;
  for (let i = 0; i < input.length; i += 1) {
    sum += input[i] * input[i];
  }
  const rms = Math.sqrt(sum / input.length);
  const percent = Math.min(100, Math.round(rms * 280));
  els.levelBar.style.width = `${Math.max(4, percent)}%`;
}

function appendSegment(segment) {
  const empty = els.transcriptList.querySelector(".empty-state");
  if (empty) empty.remove();

  if (!segment.is_final) {
    const item = state.draftElement || document.createElement("div");
    item.className = "segment draft";
    if (!state.draftElement) {
      item.innerHTML = `<small></small><span></span>`;
      els.transcriptList.append(item);
      state.draftElement = item;
    }
    item.querySelector("small").textContent = `${new Date(segment.timestamp * 1000).toLocaleTimeString()} · 草稿`;
    item.querySelector("span").textContent = segment.text;
    els.transcriptList.scrollTop = els.transcriptList.scrollHeight;
    return;
  }

  const item = state.draftElement || document.createElement("div");
  item.className = "segment";
  item.innerHTML = `<small>${new Date(segment.timestamp * 1000).toLocaleTimeString()} · #${segment.index + 1}</small><span></span>`;
  item.querySelector("span").textContent = segment.text;
  if (!state.draftElement) {
    els.transcriptList.append(item);
  }
  state.draftElement = null;
  els.transcriptList.scrollTop = els.transcriptList.scrollHeight;
  state.segmentCount += 1;
  els.segmentCount.textContent = `${state.segmentCount} 段`;
}

function renderTranscriptEmpty() {
  if (els.transcriptList.children.length) return;
  const empty = document.createElement("div");
  empty.className = "empty-state";
  empty.textContent = "开始录音后，转写文字会实时出现在这里。";
  els.transcriptList.append(empty);
  els.segmentCount.textContent = "0 段";
}

function updateSummary(payload) {
  state.currentSummary = payload.summary || null;
  state.summaryStatus = payload.summary_status || state.summaryStatus;
  state.summaryHistoryCount = payload.history_count || 0;
  renderSummary();
}

function renderSummary() {
  const status = state.summaryStatus || {};
  const stateLabel = formatSummaryState(status.state);
  els.summaryState.textContent = stateLabel;
  els.summaryState.className = status.state === "error" ? "summary-state error" : "summary-state";

  const details = [];
  if (status.model) details.push(status.model);
  if (status.last_updated_at) details.push(`更新：${formatDateTime(status.last_updated_at)}`);
  if (state.summaryHistoryCount) details.push(`${state.summaryHistoryCount} 次更新`);
  if (status.last_error) details.push(`错误：${status.last_error}`);
  els.summaryMeta.textContent = details.length ? details.join(" · ") : "录音中会按新增正式转写滚动更新。";
  els.summaryMeta.classList.toggle("error", Boolean(status.last_error));

  els.summaryGrid.innerHTML = "";
  const summary = normalizeSummary(state.currentSummary);
  for (const key of SUMMARY_KEYS) {
    const item = document.createElement("div");
    item.className = "summary-item";
    const values = summary[key];
    const title = document.createElement("strong");
    title.textContent = key;
    item.append(title);
    if (!values.length) {
      const empty = document.createElement("p");
      empty.textContent = key === "每个人负责什么" ? "未识别到明确姓名或负责人。" : "暂无。";
      item.append(empty);
    } else {
      const list = document.createElement("ul");
      for (const value of values) {
        const row = document.createElement("li");
        row.textContent = stringifySummaryItem(value);
        list.append(row);
      }
      item.append(list);
    }
    els.summaryGrid.append(item);
  }
}

function normalizeSummary(summary) {
  const normalized = {};
  for (const key of SUMMARY_KEYS) {
    const value = summary && summary[key];
    normalized[key] = Array.isArray(value) ? value : value ? [value] : [];
  }
  return normalized;
}

function stringifySummaryItem(value) {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    return Object.entries(value)
      .map(([key, item]) => `${key}：${item}`)
      .join("；");
  }
  return String(value);
}

function formatSummaryState(value) {
  if (value === "running") return "摘要中";
  if (value === "error") return "异常";
  return "待更新";
}

function formatDateTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString();
}

async function loadMeetings() {
  try {
    const response = await fetch("/api/meetings");
    const meetings = await response.json();
    els.meetingList.innerHTML = "";
    if (!meetings.length) {
      els.meetingList.innerHTML = `<div class="empty-state">暂无历史会议。</div>`;
      return;
    }
    for (const meeting of meetings) {
      const row = document.createElement("div");
      row.className = "meeting-row";
      const duration = formatDuration((meeting.duration_seconds || 0) * 1000);
      row.innerHTML = `
        <a href="/api/meetings/${meeting.id}/transcript.md" target="_blank" rel="noreferrer"></a>
        <div class="meeting-meta">${meeting.created_at} · ${duration} · ${meeting.segments} 段 · ${meeting.status} · ${formatSpeakerStatus(meeting)}</div>
        <div class="meeting-actions">
          <button class="small-btn refine-btn" type="button">会后精转</button>
          <button class="small-btn diarize-btn" type="button">说话人分离</button>
        </div>
      `;
      row.querySelector("a").textContent = meeting.title;
      row.querySelector(".refine-btn").addEventListener("click", (event) => {
        refineMeeting(meeting.id, event.currentTarget);
      });
      row.querySelector(".diarize-btn").addEventListener("click", (event) => {
        diarizeMeeting(meeting.id, event.currentTarget);
      });
      els.meetingList.append(row);
    }
  } catch (error) {
    els.meetingList.innerHTML = `<div class="empty-state">历史会议加载失败。</div>`;
  }
}

async function refineMeeting(meetingId, button) {
  const oldText = button.textContent;
  button.disabled = true;
  button.textContent = "精转中";
  try {
    const response = await fetch(`/api/meetings/${meetingId}/refine-transcript`, { method: "POST" });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || "精转失败");
    }
    button.textContent = "已精转";
    await loadMeetings();
  } catch (error) {
    button.textContent = oldText;
    setStatus(`会后精转失败：${error.message || error}`, true);
  } finally {
    button.disabled = false;
  }
}

async function diarizeMeeting(meetingId, button) {
  const oldText = button.textContent;
  button.disabled = true;
  button.textContent = "分离中";
  try {
    const response = await fetch(`/api/meetings/${meetingId}/diarize`, { method: "POST" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      const detail = payload.detail || payload.speaker_status?.last_error || "说话人分离失败";
      throw new Error(detail);
    }
    button.textContent = "已分离";
    await loadMeetings();
  } catch (error) {
    button.textContent = oldText;
    setStatus(`说话人分离失败：${error.message || error}`, true);
    await loadMeetings();
  } finally {
    button.disabled = false;
  }
}

function formatSpeakerStatus(meeting) {
  const status = meeting.speaker_status || {};
  if (status.state === "done") return `${meeting.speaker_segments || 0} 段说话人`;
  if (status.state === "running") return "说话人分离中";
  if (status.state === "error") return "说话人分离异常";
  return "未分离说话人";
}

function tickDuration() {
  if (!state.recording) return;
  const pausedPart = state.paused ? Date.now() - state.pauseStartedAt : 0;
  const elapsed = Date.now() - state.startedAt - state.pausedMs - pausedPart;
  els.durationText.textContent = formatDuration(elapsed);
}

function formatDuration(ms) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  return [hours, minutes, seconds].map((value) => String(value).padStart(2, "0")).join(":");
}

function setConnection(kind, text) {
  els.connectionState.className = "connection-pill";
  if (kind) els.connectionState.classList.add(kind);
  els.connectionState.textContent = text;
}

function setStatus(text, isError = false) {
  els.statusLine.textContent = text;
  els.statusLine.style.color = isError ? "var(--red)" : "var(--muted)";
}

function updateControls() {
  els.startBtn.disabled = state.recording;
  els.pauseBtn.disabled = !state.recording;
  els.stopBtn.disabled = !state.recording;
  els.pauseBtn.textContent = state.paused ? "继续" : "暂停";
  els.meetingTitle.disabled = state.recording;
}

function isSocketOpen() {
  return state.socket?.readyState === WebSocket.OPEN;
}

function registerServiceWorker() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
}
