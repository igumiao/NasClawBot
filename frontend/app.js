document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("chat-form");
  const messageInput = document.getElementById("message");
  const output = document.getElementById("response-output");

  if (!form || !messageInput || !output) {
    return;
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = messageInput.value.trim();
    if (!message) {
      output.textContent = "Please type a message first.";
      return;
    }

    output.textContent = "Task 1 shell: chat endpoint will be wired in later tasks.";
  });
});
