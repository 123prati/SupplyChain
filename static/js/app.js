document.addEventListener("submit", (event) => {
  const form = event.target;
  const message = form.getAttribute("data-confirm");
  if (message && !window.confirm(message)) {
    event.preventDefault();
  }
});

document.querySelectorAll("input[type='number']").forEach((input) => {
  input.addEventListener("input", () => {
    if (input.value && Number(input.value) < 0) {
      input.value = 0;
    }
  });
});
