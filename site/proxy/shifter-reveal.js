// DOM port of Shifter's ScrollReveal and useScrollAnimation components.
// Keep content visible without JS, and reveal below-fold content only once.
export function initShifterReveals() {
  const elements = [...document.querySelectorAll('[data-shifter-reveal]')];
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
  if (reducedMotion.matches || !('IntersectionObserver' in window)) return;

  const observers = [];
  for (const element of elements) {
    const heading = element.dataset.shifterReveal === 'heading';
    const rect = element.getBoundingClientRect();
    const visible = heading
      ? rect.top < innerHeight && rect.bottom > 0
      : rect.top < innerHeight * .85;
    if (visible) continue;
    element.classList.add('reveal-pending');
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      element.classList.replace('reveal-pending', 'reveal-visible');
      observer.disconnect();
    }, {rootMargin: heading ? '-50px' : '-80px'});
    observer.observe(element);
    observers.push(observer);
  }

  reducedMotion.addEventListener('change', event => {
    if (!event.matches) return;
    observers.forEach(observer => observer.disconnect());
    elements.forEach(element => element.classList.remove('reveal-pending', 'reveal-visible'));
  });
}
