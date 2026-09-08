// Adds `is-visible` to every `.reveal` element as it enters the viewport
// (was copy-pasted in graph-explorer.js, contact.js, conceptual-model.js and
// inlined in team.js). Without IntersectionObserver everything is revealed
// immediately — content must never stay hidden.
export default function revealOnScroll(threshold = 0.15) {
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
        { threshold },
    );
    els.forEach((e) => io.observe(e));
}
