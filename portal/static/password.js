"use strict";

/* Show/hide button (an eye) inside every password field of the page: sign-in and password change.
   The field goes back to hidden when its form is submitted, so password managers see a password field. */
(() => {
  const SVG = "http://www.w3.org/2000/svg";

  function icon(crossed) {
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const shapes = [["path", { d: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" }],
                    ["circle", { cx: "12", cy: "12", r: "3" }]];
    if (crossed) shapes.push(["path", { d: "M4 4l16 16" }]);
    for (const [name, attributes] of shapes) {
      const shape = document.createElementNS(SVG, name);
      Object.entries(attributes).forEach(([key, value]) => shape.setAttribute(key, value));
      svg.append(shape);
    }
    return svg;
  }

  function label(button, shown) {
    const key = shown ? "password.hide" : "password.show";
    button.dataset.i18nAttr = `aria-label:${key};title:${key}`;
    button.setAttribute("aria-label", I18N.t(key));
    button.title = I18N.t(key);
  }

  function hide(input, button) {
    input.type = "password";
    button.setAttribute("aria-pressed", "false");
    button.replaceChildren(icon(false));
    label(button, false);
  }

  function enhance(input) {
    const wrap = document.createElement("span");
    wrap.className = "password-field";
    input.parentNode.insertBefore(wrap, input);
    wrap.append(input);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "reveal";
    if (input.id) button.setAttribute("aria-controls", input.id);
    wrap.append(button);
    hide(input, button);
    button.addEventListener("click", () => {
      if (input.type === "password") {
        input.type = "text";
        button.setAttribute("aria-pressed", "true");
        button.replaceChildren(icon(true));
        label(button, true);
      } else {
        hide(input, button);
      }
      const end = input.value.length;
      input.focus({ preventScroll: true });
      try { input.setSelectionRange(end, end); } catch { /* not supported by this field type */ }
    });
    input.form?.addEventListener("submit", () => hide(input, button), true);
    input.form?.addEventListener("reset", () => hide(input, button));
  }

  document.querySelectorAll('input[type="password"]').forEach(enhance);
})();
