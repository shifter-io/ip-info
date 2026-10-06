// Controls the visual loading state only; session authorization stays in app.js.
export class PageLoading {
  constructor(element, viewport, onTimeout, timeoutMs = 25000) {
    this.element = element;
    this.viewport = viewport;
    this.onTimeout = onTimeout;
    this.timeoutMs = timeoutMs;
  }
  start() {
    clearTimeout(this.timer);
    this.element.hidden = false;
    this.viewport.setAttribute('aria-busy', 'true');
    this.timer = setTimeout(() => {
      this.finish();
      this.onTimeout();
    }, this.timeoutMs);
  }
  finish() {
    clearTimeout(this.timer);
    this.element.hidden = true;
    this.viewport.setAttribute('aria-busy', 'false');
  }
}
