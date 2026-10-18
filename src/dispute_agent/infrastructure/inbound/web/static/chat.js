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
};

const conversation = document.getElementById("conversation");

// Crea una burbuja con textContent (nunca HTML) y un prefijo accesible oculto (RN-008-09/21).
function appendMessage(author, text) {
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
  // El indicador de espera y los avisos quedan siempre debajo del último mensaje.
  conversation.insertBefore(bubble, document.getElementById("typing"));
  return bubble;
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

// Red + validación: devuelve la respuesta 200 válida o lanza un Error (RN-008-10).
async function postMessage(text, signal) {
  const payload = { message: text };
  if (state.conversationId !== null) {
    payload.conversation_id = state.conversationId;
  }
  if (navigator.onLine === false) {
    throw new NetworkError();
  }
  let response;
  try {
    response = await fetch("/api/chat", {
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
  const data = await response.json();
  const validStatus = data && (data.status === "ACTIVE" || data.status === "ESCALATED");
  if (!data || typeof data.reply !== "string" || !validStatus) {
    throw new Error("invalid response");
  }
  return data;
}

// Presentación: solo `reply` se muestra; el resto de campos nunca se pinta (RN-008-10).
function showReply(data) {
  if (typeof data.conversation_id === "string") {
    state.conversationId = data.conversation_id;
  }
  appendMessage("agent", data.reply);
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

function applyFailure(kind, text, bubble) {
  state.failedText = text;
  failedBubble = bubble;
  state.notice = FAILURE_NOTICES[kind];
}

// Un intento de envío de `text` (nuevo o reintento) con tiempo límite de 60 s.
async function attemptSend(text, bubble) {
  currentAttempt += 1;
  const attempt = currentAttempt;
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    if (attempt !== currentAttempt) {
      return;
    }
    timedOut = true;
    currentAttempt += 1; // invalida cualquier respuesta tardía de este intento
    controller.abort();
    applyFailure("timeout", text, bubble);
    state.pending = false;
    render();
  }, REPLY_TIMEOUT_MS);
  state.pending = true;
  render();
  try {
    const data = await postMessage(text, controller.signal);
    if (attempt !== currentAttempt) {
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
    if (attempt === currentAttempt) {
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
  typing.textContent = TEXTS.typing;
  typing.hidden = !state.pending;
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
