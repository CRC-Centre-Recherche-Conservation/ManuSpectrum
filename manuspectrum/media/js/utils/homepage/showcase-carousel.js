/**
 * Showcase carousel: arrows, dots and manual scrolling stay in sync.
 *
 * Arrows and dots set the target slide synchronously, then scroll the track
 * (`instant` under reduced motion). An IntersectionObserver follows manual
 * scrolling: it only acts on entries with `intersectionRatio >= 0.6`. While a
 * programmed scroll runs, it ignores every entry except the target slide
 * reaching that ratio, which ends the scroll; `scrollend` ends it too, and a
 * 1500 ms timer is the safety net for browsers with no `scrollend` on a long
 * multi-slide smooth scroll. The active dot has `.active` and
 * `aria-current="true"`.
 */
const PROGRAMMED_SCROLL_MS = 1500;
const RATIO = 0.6;

/**
 * @param {ParentNode} [root=document]
 * @returns {() => void} removes the listeners and the observer
 */
export default function initShowcaseCarousel(root = document) {
    const track = root.querySelector("#ms-showcase-track");
    if (!track) {
        return () => {};
    }
    const slides = Array.from(track.children);
    const dots = Array.from(root.querySelectorAll("#ms-showcase-nav .ms-showcase-dot"));
    const prev = root.querySelector("#ms-showcase-prev");
    const next = root.querySelector("#ms-showcase-next");
    let current = 0;
    let programmed = false;
    let timer = null;

    const markActive = () => {
        dots.forEach((dot, i) => {
            const on = i === current;
            dot.classList.toggle("active", on);
            if (on) {
                dot.setAttribute("aria-current", "true");
            } else {
                dot.removeAttribute("aria-current");
            }
        });
    };
    const endProgrammed = () => {
        programmed = false;
        clearTimeout(timer);
    };
    const goTo = (index) => {
        current = (index + slides.length) % slides.length;
        markActive();
        programmed = true;
        clearTimeout(timer);
        timer = setTimeout(endProgrammed, PROGRAMMED_SCROLL_MS);
        const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        track.scrollTo({ left: slides[current].offsetLeft - track.offsetLeft, behavior: reduce ? "instant" : "smooth" });
    };
    const onPrev = () => goTo(current - 1);
    const onNext = () => goTo(current + 1);
    const onDot = (event) => goTo(dots.indexOf(event.currentTarget));

    let io = null;
    if ("IntersectionObserver" in window) {
        io = new IntersectionObserver(
            (entries) => {
                entries.forEach((entry) => {
                    const index = slides.indexOf(entry.target);
                    if (index === -1 || entry.intersectionRatio < RATIO) {
                        return;
                    }
                    if (programmed) {
                        if (index === current) {
                            endProgrammed();
                        }
                        return;
                    }
                    if (index !== current) {
                        current = index;
                        markActive();
                    }
                });
            },
            { root: track, threshold: RATIO },
        );
        slides.forEach((slide) => io.observe(slide));
    }

    track.addEventListener("scrollend", endProgrammed);
    if (prev) {
        prev.addEventListener("click", onPrev);
    }
    if (next) {
        next.addEventListener("click", onNext);
    }
    dots.forEach((dot) => dot.addEventListener("click", onDot));
    markActive();

    return () => {
        clearTimeout(timer);
        if (io) {
            io.disconnect();
        }
        track.removeEventListener("scrollend", endProgrammed);
        if (prev) {
            prev.removeEventListener("click", onPrev);
        }
        if (next) {
            next.removeEventListener("click", onNext);
        }
        dots.forEach((dot) => dot.removeEventListener("click", onDot));
    };
}
