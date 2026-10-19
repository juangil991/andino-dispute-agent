"use strict";

// Textos fijos de la página (spec 008 §7.2).
const TEXTS = {
  title: "Banco Andino — Asistente de disputas",
  greeting:
    "Hola, soy el asistente de disputas de Banco Andino. Antes de revisar tu cuenta necesito " +
    "identificarte. Para empezar, indícame tu número de documento, tu nombre completo o los " +
    "últimos 4 dígitos de tu tarjeta.",
  inputLabel: "Escribe tu mensaje",
  send: "Enviar",
  typing: "El agente está escribiendo…",
  counter: (remaining) => "Quedan " + remaining + " caracteres",
  authorUser: "Tú",
  authorAgent: "Agente",
  unsent: "No enviado",
  incomplete: "Incompleto",
  escalated: "Tu caso fue derivado a un analista. Una persona continuará la atención.",
  unavailableConversation: "Esta conversación ya no está disponible.",
  newConversation: "Iniciar una conversación nueva",
  offline: "No hay conexión a internet. Revisa tu conexión y vuelve a intentarlo.",
  timeout: "La respuesta está tardando más de lo normal. Puedes volver a intentarlo.",
  unavailable: "No pudimos atenderte en este momento. Intenta de nuevo en unos minutos.",
  retry: "Reintentar",
};

// Estado en memoria: nunca se guarda en el navegador (RN-008-12).
const state = {
  conversationId: null,
  pending: false,
  failedText: null,
  closed: false,
  notice: null,
  receiving: false, // ya llegó la primera palabra del turno en curso
};

const conversation = document.getElementById("conversation");
// Borrador de la respuesta que va llegando: fuera de la región viva (RN-009-15).
const draft = document.getElementById("draft");

// Crea una burbuja con textContent (nunca HTML) y un prefijo accesible oculto (RN-008-09/21).
function createBubble(author, text) {
  const isUser = author === "user";
  const bubble = document.createElement("div");
  bubble.className = "message " + (isUser ? "message-user" : "message-agent");
  bubble.dataset.author = isUser ? "user" : "agent";

  const prefix = document.createElement("span");
  prefix.className = "visually-hidden";
  prefix.textContent = (isUser ? TEXTS.authorUser : TEXTS.authorAgent) + ": ";

  const body = document.createElement("span");
  body.className = "message-text";
  body.textContent = text;

  bubble.append(prefix, body);
  return bubble;
}

// La conversación sigue al último mensaje mientras la cliente no suba a releer: si se aleja del
// final se deja de seguir, y enviar un mensaje propio vuelve a seguirlo.
const FOLLOW_MARGIN_PX = 48;
let following = true;

conversation.addEventListener("scroll", () => {
  following =
    conversation.scrollHeight - conversation.scrollTop - conversation.clientHeight <=
    FOLLOW_MARGIN_PX;
});

function scrollToEnd(force) {
  if (force) {
    following = true;
  }
  if (following) {
    conversation.scrollTop = conversation.scrollHeight;
  }
}

// El indicador de espera y los avisos quedan siempre debajo del último mensaje.
function placeInConversation(bubble) {
  conversation.insertBefore(bubble, document.getElementById("typing"));
  scrollToEnd(false);
}

function appendMessage(author, text) {
  const bubble = createBubble(author, text);
  placeInConversation(bubble);
  if (author === "user") {
    scrollToEnd(true);
  }
  return bubble;
}

// Analizador SSE puro: separa los eventos completos del resto sin terminar. Tolera eventos
// partidos entre lecturas y fines de línea `\r\n`, `\r` o `\n`. Cada evento: {name, data}.
function parseSseBuffer(buffer) {
  let text = buffer;
  let held = "";
  if (text.endsWith("\r")) {
    held = "\r"; // podría ser la mitad de un `\r\n` partido entre lecturas
    text = text.slice(0, -1);
  }
  text = text.replace(/\r\n|\r/g, "\n");
  const blocks = text.split("\n\n");
  const rest = blocks.pop() + held;
  const events = [];
  for (const block of blocks) {
    let name = null;
    const dataLines = [];
    for (const line of block.split("\n")) {
      if (line === "" || line.startsWith(":")) {
        continue;
      }
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      let value = colon === -1 ? "" : line.slice(colon + 1);
      if (value.startsWith(" ")) {
        value = value.slice(1);
      }
      if (field === "event") {
        name = value;
      } else if (field === "data") {
        dataLines.push(value);
      }
    }
    if (name !== null || dataLines.length > 0) {
      events.push({ name: name, data: dataLines.join("\n") });
    }
  }
  return { events: events, rest: rest };
}

// Valida un evento SSE (spec 009 §7.1): tipo conocido, JSON válido y campos con su tipo.
// Devuelve {type, ...campos usados}; lanza Error si es inválido. `outcomes` nunca se usa.
function validateStreamEvent(raw) {
  let data;
  try {
    data = JSON.parse(raw.data);
  } catch (error) {
    throw new Error("invalid event data");
  }
  if (data === null || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("invalid event data");
  }
  const id = data.conversation_id;
  if (id !== undefined && id !== null && typeof id !== "string") {
    throw new Error("invalid conversation_id");
  }
  const conversationId = typeof id === "string" ? id : null;
  if (raw.name === "start") {
    return { type: "start", conversationId: conversationId };
  }
  if (raw.name === "word" && typeof data.text === "string") {
    return { type: "word", text: data.text };
  }
  if (
    raw.name === "end" &&
    typeof data.reply === "string" &&
    (data.status === "ACTIVE" || data.status === "ESCALATED")
  ) {
    return { type: "end", conversationId: conversationId, reply: data.reply, status: data.status };
  }
  if (raw.name === "interrupted" && typeof data.reply === "string" && data.status === "ESCALATED") {
    return {
      type: "interrupted",
      conversationId: conversationId,
      reply: data.reply,
      status: data.status,
    };
  }
  throw new Error("invalid event");
}

// La conversación ya no existe en el servidor (404): se cierra sin reintento (RN-008-15).
class ConversationGoneError extends Error {}

// Falla de red de `fetch` (sin conexión, DNS, corte): se avisa como falta de conexión.
class NetworkError extends Error {}

// Tabla única: clase de fallo -> texto fijo de §7.2 (nunca código, cuerpo ni error).
const FAILURE_NOTICES = {
  offline: TEXTS.offline,
  timeout: TEXTS.timeout,
  unavailable: TEXTS.unavailable,
};
const REPLY_TIMEOUT_MS = 60000;

function classifyFailure(error, timedOut) {
  if (timedOut) {
    return "timeout";
  }
  if (error instanceof NetworkError || navigator.onLine === false) {
    return "offline";
  }
  return "unavailable";
}

// Burbuja borrador del agente que crece con cada palabra (vive en #draft hasta `end`).
let draftBubble = null;
// Con `prefers-reduced-motion: reduce` el borrador se acumula oculto (RN-009-20); se lee en
// cada envío, no solo al cargar.
let reducedMotion = false;

function clearDraft() {
  draftBubble = null;
  draft.style.display = "";
  draft.replaceChildren();
}

// Una palabra: crea la burbuja en #draft con la primera y añade el fragmento como texto.
function appendWord(fragment) {
  if (draftBubble === null) {
    draftBubble = createBubble("agent", "");
    draft.style.display = reducedMotion ? "none" : "";
    draft.append(draftBubble);
    // El indicador deja de verse con la primera palabra (RN-009-14), salvo con movimiento
    // reducido: se mantiene hasta el final (RN-009-20).
    state.receiving = !reducedMotion;
    render();
  }
  draftBubble.querySelector(".message-text").textContent += fragment;
}

// Red + lectura del flujo SSE + validación: devuelve el evento `end` válido o lanza un Error
// (RN-008-10, RN-009-13). Devuelve null si el intento dejó de ser el vigente.
async function postMessage(text, signal, isCurrent, onWord) {
  const payload = { message: text };
  if (state.conversationId !== null) {
    payload.conversation_id = state.conversationId;
  }
  if (navigator.onLine === false) {
    throw new NetworkError();
  }
  let response;
  try {
    response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: signal,
    });
  } catch (error) {
    if (error instanceof TypeError) {
      throw new NetworkError();
    }
    throw error;
  }
  if (response.status === 404) {
    throw new ConversationGoneError();
  }
  if (response.status !== 200) {
    throw new Error("unexpected status " + response.status);
  }
  if (response.body === null) {
    throw new Error("empty body");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  try {
    for (;;) {
      let chunk;
      try {
        chunk = await reader.read();
      } catch (error) {
        if (error instanceof TypeError) {
          throw new NetworkError();
        }
        throw error;
      }
      if (!isCurrent()) {
        return null;
      }
      if (chunk.done) {
        break;
      }
      buffer += decoder.decode(chunk.value, { stream: true });
      const parsed = parseSseBuffer(buffer);
      buffer = parsed.rest;
      for (const raw of parsed.events) {
        const event = validateStreamEvent(raw);
        if (event.type === "start") {
          if (event.conversationId !== null) {
            state.conversationId = event.conversationId;
          }
        } else if (event.type === "word") {
          appendWord(event.text);
          onWord();
        } else {
          return event;
        }
      }
    }
  } finally {
    reader.cancel().catch(() => {});
  }
  throw new Error("stream closed without end");
}

// Presentación: solo `reply` se muestra; el resto de campos nunca se pinta (RN-008-10).
// Si hubo palabras, la burbuja borrador pasa a ser exactamente `reply` y se mueve a la
// conversación; si no (texto fijo), la burbuja aparece completa de una vez (RN-009-21).
function showReply(data) {
  if (data.conversationId !== null) {
    state.conversationId = data.conversationId;
  }
  if (data.type === "interrupted") {
    // El parcial se conserva marcado `Incompleto` y `reply` va completo debajo (RN-009-18).
    if (draftBubble !== null) {
      const mark = document.createElement("span");
      mark.className = "message-incomplete-mark";
      mark.textContent = " " + TEXTS.incomplete;
      draftBubble.append(mark);
      placeInConversation(draftBubble);
      clearDraft();
    }
    appendMessage("agent", data.reply);
  } else if (draftBubble !== null) {
    draftBubble.querySelector(".message-text").textContent = data.reply;
    placeInConversation(draftBubble);
    clearDraft();
  } else {
    appendMessage("agent", data.reply);
  }
  if (data.status === "ESCALATED") {
    state.closed = true;
    state.notice = TEXTS.escalated;
  }
}

const form = document.getElementById("composer");
const input = document.getElementById("message");

// Identificador del intento vigente: las respuestas de intentos abortados se descartan.
let currentAttempt = 0;
// Burbuja del mensaje que no se pudo enviar (para marcarla y no repintarla al reintentar).
let failedBubble = null;
// Controlador del flujo en curso, para abortarlo al iniciar una conversación nueva.
let currentController = null;

// Marca `Incompleto` la burbuja parcial y la deja en la conversación (RN-009-24). Devuelve
// true si había palabras.
function keepPartialAsIncomplete() {
  if (draftBubble === null) {
    return false;
  }
  const mark = document.createElement("span");
  mark.className = "message-incomplete-mark";
  mark.textContent = " " + TEXTS.incomplete;
  draftBubble.append(mark);
  placeInConversation(draftBubble);
  clearDraft();
  return true;
}

// Con palabras parciales el mensaje de la cliente no se marca `No enviado` (RN-009-24), pero el
// texto sigue guardado para `Reintentar`.
function applyFailure(kind, text, bubble) {
  const hadWords = keepPartialAsIncomplete();
  state.failedText = text;
  failedBubble = hadWords ? null : bubble;
  state.notice = FAILURE_NOTICES[kind];
}

// Un intento de envío de `text` (nuevo o reintento). La espera de 60 s sin palabra nueva se
// cuenta desde el envío y se reinicia con cada `word` (RN-009-22).
async function attemptSend(text, bubble) {
  currentAttempt += 1;
  const attempt = currentAttempt;
  const controller = new AbortController();
  currentController = controller;
  let timedOut = false;
  let timer = null;
  // Corta la espera del flujo: los eventos posteriores de este intento se descartan.
  const cutOff = (kind) => {
    if (attempt !== currentAttempt) {
      return;
    }
    currentAttempt += 1; // invalida cualquier evento tardío de este intento
    controller.abort();
    state.receiving = false;
    applyFailure(kind, text, bubble);
    state.pending = false;
    render();
  };
  const armTimer = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      timedOut = true;
      cutOff("timeout");
    }, REPLY_TIMEOUT_MS);
  };
  const onOffline = () => cutOff("offline");
  window.addEventListener("offline", onOffline);
  armTimer();
  state.pending = true;
  state.receiving = false;
  reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  render();
  try {
    const data = await postMessage(
      text,
      controller.signal,
      () => attempt === currentAttempt,
      armTimer,
    );
    if (data === null || attempt !== currentAttempt) {
      return;
    }
    state.failedText = null;
    failedBubble = null;
    state.notice = null;
    showReply(data);
  } catch (error) {
    if (attempt !== currentAttempt) {
      return;
    }
    if (error instanceof ConversationGoneError) {
      state.failedText = null;
      failedBubble = null;
      state.closed = true;
      state.notice = TEXTS.unavailableConversation;
    } else {
      applyFailure(classifyFailure(error, timedOut), text, bubble);
    }
  } finally {
    clearTimeout(timer);
    window.removeEventListener("offline", onOffline);
    if (attempt === currentAttempt) {
      clearDraft();
      state.receiving = false;
      state.pending = false;
      render();
      // Al habilitarse la caja tras la respuesta, el foco vuelve a ella (RN-008-20).
      if (!input.disabled) {
        input.focus();
      }
    }
  }
}

async function send() {
  if (state.pending || state.closed || state.failedText !== null) {
    return;
  }
  const text = input.value.trim();
  if (text === "") {
    return;
  }
  const bubble = appendMessage("user", text);
  input.value = "";
  updateCounter();
  await attemptSend(text, bubble);
}

async function retry() {
  if (state.pending || state.closed || state.failedText === null) {
    return;
  }
  await attemptSend(state.failedText, failedBubble);
}

const typing = document.getElementById("typing");
const sendButton = document.getElementById("send");
const notices = document.getElementById("notices");
const retryButton = document.getElementById("retry");
const newConversationButton = document.getElementById("new-conversation");

// Único punto que traduce el estado a la UI: indicador y bloqueo de controles (RN-008-07).
function render() {
  // El texto fijo del indicador vive en el HTML: no se reescribe en cada render para no
  // generar mutaciones de texto en la región viva mientras llegan palabras (RN-009-19).
  typing.hidden = !state.pending || state.receiving;
  const blocked = state.pending || state.closed || state.failedText !== null;
  input.disabled = blocked;
  sendButton.disabled = blocked;
  retryButton.hidden = state.failedText === null || state.closed;
  retryButton.disabled = state.pending;
  for (const bubble of conversation.querySelectorAll(".message-unsent")) {
    if (bubble !== failedBubble) {
      bubble.classList.remove("message-unsent");
      bubble.querySelector(".message-unsent-mark")?.remove();
    }
  }
  if (failedBubble !== null && !failedBubble.classList.contains("message-unsent")) {
    failedBubble.classList.add("message-unsent");
    const mark = document.createElement("span");
    mark.className = "message-unsent-mark";
    mark.textContent = " " + TEXTS.unsent;
    failedBubble.append(mark);
  }
  notices.replaceChildren();
  if (state.notice !== null) {
    const notice = document.createElement("p");
    notice.className = "notice";
    notice.textContent = state.notice;
    notices.append(notice);
  }
  newConversationButton.hidden = !state.closed;
  // El borrador, el indicador y los avisos cambian la altura visible: se mantiene el final a la vista.
  scrollToEnd(state.notice !== null);
}

// Conversación nueva: vacía el log, olvida la anterior y vuelve al saludo (RN-008-14).
function startNewConversation() {
  state.conversationId = null;
  state.pending = false;
  state.failedText = null;
  state.closed = false;
  state.notice = null;
  failedBubble = null;
  currentAttempt += 1;
  state.receiving = false;
  if (currentController !== null) {
    currentController.abort();
    currentController = null;
  }
  clearDraft();
  for (const bubble of conversation.querySelectorAll("[data-author]")) {
    bubble.remove();
  }
  appendMessage("agent", TEXTS.greeting);
  input.value = "";
  updateCounter();
  render();
  input.focus();
}

newConversationButton.addEventListener("click", startNewConversation);
retryButton.addEventListener("click", retry);

const counter = document.getElementById("counter");
const COUNTER_THRESHOLD = 200;

// Contador visible solo cuando quedan 200 caracteres o menos (RN-008-05).
function updateCounter() {
  const remaining = input.maxLength - input.value.length;
  if (remaining <= COUNTER_THRESHOLD) {
    counter.textContent = TEXTS.counter(remaining);
    counter.hidden = false;
  } else {
    counter.textContent = "";
    counter.hidden = true;
  }
}

input.addEventListener("input", updateCounter);

// Enter envía; Shift+Enter deja el salto de línea (RN-008-06).
input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    form.requestSubmit();
  }
});

form.addEventListener("submit", (event) => {
  event.preventDefault();
  send();
});

// Al cargar solo se pinta el saludo; no se llama al agente (RN-008-03).
appendMessage("agent", TEXTS.greeting);
