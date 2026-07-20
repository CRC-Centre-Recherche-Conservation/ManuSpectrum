import initMsNav from "utils/ms-nav";

function revealOnScroll() {
    const els = document.querySelectorAll(".reveal");
    if (!("IntersectionObserver" in window)) {
        els.forEach((e) => e.classList.add("is-visible"));
        return;
    }
    const io = new IntersectionObserver(
        (entries) => {
            entries.forEach((en) => {
                if (en.isIntersecting) {
                    en.target.classList.add("is-visible");
                    io.unobserve(en.target);
                }
            });
        },
        { threshold: 0.15 },
    );
    els.forEach((e) => io.observe(e));
}

function countUp() {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    document.querySelectorAll(".ms-cm-stat-value[data-count]").forEach((el) => {
        const target = parseInt(el.dataset.count, 10);
        if (reduce) {
            el.textContent = String(target);
            return;
        }
        let n = 0;
        const step = Math.max(1, Math.round(target / 40));
        const tick = () => {
            n = Math.min(target, n + step);
            el.textContent = String(n);
            if (n < target) requestAnimationFrame(tick);
        };
        const io = new IntersectionObserver((e) => {
            if (e[0].isIntersecting) {
                tick();
                io.disconnect();
            }
        });
        io.observe(el);
    });
}

document.addEventListener("DOMContentLoaded", () => {
    initMsNav();
    revealOnScroll();
    countUp();
});
