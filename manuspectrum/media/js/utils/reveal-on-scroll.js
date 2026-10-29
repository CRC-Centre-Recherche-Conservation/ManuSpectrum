/**
 * Reveals elements as they scroll into view; content is visible by default.
 *
 * At start-up, every element with at least one pixel inside the viewport gets
 * `is-visible` at once. The others get `is-pending` (hidden by CSS, without
 * transition) and are observed: on intersection `is-pending` is removed and
 * `is-visible` added, which plays the transition declared on `.reveal`.
 * `threshold` and `rootMargin` only tune the observer. Without
 * IntersectionObserver every element is revealed.
 *
 * @param {number} [threshold=0.15]
 * @param {{ selector?: string, rootMargin?: string }} [options]
 */
export default function revealOnScroll(threshold = 0.15, { selector = ".reveal", rootMargin = "0px" } = {}) {
    const els = Array.from(document.querySelectorAll(selector));
    if (!("IntersectionObserver" in window)) {
        els.forEach((el) => el.classList.add("is-visible"));
        return;
    }
    const width = window.innerWidth;
    const height = window.innerHeight;
    const onScreen = els.map((el) => {
        const rect = el.getBoundingClientRect();
        return rect.bottom > 0 && rect.top < height && rect.right > 0 && rect.left < width;
    });
    const io = new IntersectionObserver(
        (entries) => {
            entries.forEach((entry) => {
                if (entry.isIntersecting) {
                    entry.target.classList.remove("is-pending");
                    entry.target.classList.add("is-visible");
                    io.unobserve(entry.target);
                }
            });
        },
        { threshold, rootMargin },
    );
    els.forEach((el, i) => {
        if (onScreen[i]) {
            el.classList.add("is-visible");
        } else {
            el.classList.add("is-pending");
            io.observe(el);
        }
    });
}
