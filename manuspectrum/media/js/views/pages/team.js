import initMsNav from "utils/ms-nav";

document.addEventListener("DOMContentLoaded", () => {
    initMsNav();

    document.querySelectorAll(".ms-member-img").forEach((img) => {
        const markFallback = () => {
            const box = img.closest(".ms-member-photo");
            if (box) box.classList.add("is-fallback");
        };
        img.addEventListener("error", markFallback);
        // catch images that already failed before this script ran
        if (img.complete && img.naturalWidth === 0) markFallback();
    });

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
        { threshold: 0.1 },
    );
    els.forEach((e) => io.observe(e));
});
