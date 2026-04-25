document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("chat-form");
  const messageInput = document.getElementById("message");
  const statusOutput = document.getElementById("status-output");
  const confirmationPanel = document.getElementById("confirmation-panel");
  const confirmationSummary = document.getElementById("confirmation-summary");
  const confirmationExplanation = document.getElementById("confirmation-explanation");
  const resultsList = document.getElementById("results-list");
  const receiptPanel = document.getElementById("receipt-panel");
  const receiptOutput = document.getElementById("receipt-output");
  const approveBtn = document.getElementById("approve-btn");
  const refineBtn = document.getElementById("refine-btn");
  const cancelBtn = document.getElementById("cancel-btn");

  if (
    !form ||
    !messageInput ||
    !statusOutput ||
    !confirmationPanel ||
    !confirmationSummary ||
    !confirmationExplanation ||
    !resultsList ||
    !receiptPanel ||
    !receiptOutput ||
    !approveBtn ||
    !refineBtn ||
    !cancelBtn
  ) {
    return;
  }

  const sessionId = `demo-${Date.now()}`;
  let currentPayload = null;

  const setStatus = (text) => {
    statusOutput.textContent = text;
  };

  const showConfirmation = (payload) => {
    currentPayload = payload || null;
    if (!payload) {
      confirmationPanel.classList.add("hidden");
      return;
    }

    confirmationSummary.textContent = payload.summary || "Review candidates before continuing.";
    confirmationExplanation.textContent = payload.explanation || "";
    resultsList.innerHTML = "";

    (payload.results || []).forEach((item, index) => {
      const row = document.createElement("label");
      row.className = "result-row";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "selected-result";
      radio.value = item.id;
      if (item.id === payload.recommended_result_id || index === 0) {
        radio.checked = true;
      }
      const text = document.createElement("span");
      text.textContent = `${item.title} | score=${item.score} | seeders=${item.seeders}`;
      row.appendChild(radio);
      row.appendChild(text);
      resultsList.appendChild(row);
    });

    confirmationPanel.classList.remove("hidden");
  };

  const showReceipt = (receipt) => {
    if (!receipt) {
      receiptPanel.classList.add("hidden");
      return;
    }
    receiptOutput.textContent = JSON.stringify(receipt, null, 2);
    receiptPanel.classList.remove("hidden");
  };

  const selectedResultId = () => {
    const checked = document.querySelector("input[name='selected-result']:checked");
    return checked ? checked.value : null;
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = messageInput.value.trim();
    if (!message) {
      setStatus("Please type a message first.");
      return;
    }

    setStatus("Searching candidates...");
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message }),
    });
    const body = await response.json();
    setStatus(body.status || "unknown");
    showConfirmation(body.confirmation_payload);
    showReceipt(body.receipt);
  });

  approveBtn.addEventListener("click", async () => {
    if (!currentPayload) {
      setStatus("No confirmation payload available.");
      return;
    }
    setStatus("Submitting approved result...");
    const response = await fetch("/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        action: "approve",
        selected_result_id: selectedResultId(),
        confirmation_payload: currentPayload,
      }),
    });
    const body = await response.json();
    setStatus(body.status || "unknown");
    showConfirmation(body.confirmation_payload);
    showReceipt(body.receipt);
  });

  refineBtn.addEventListener("click", async () => {
    const feedback = messageInput.value.trim();
    if (!feedback) {
      setStatus("Type refinement guidance in the message box first.");
      return;
    }
    setStatus("Refining search...");
    const response = await fetch("/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: sessionId,
        action: "reject_and_refine",
        feedback_text: feedback,
      }),
    });
    const body = await response.json();
    setStatus(body.status || "unknown");
    showConfirmation(body.confirmation_payload);
    showReceipt(body.receipt);
  });

  cancelBtn.addEventListener("click", async () => {
    setStatus("Canceling request...");
    const response = await fetch("/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, action: "cancel" }),
    });
    const body = await response.json();
    setStatus(body.status || "unknown");
    currentPayload = null;
    confirmationPanel.classList.add("hidden");
    showReceipt(null);
  });
});
