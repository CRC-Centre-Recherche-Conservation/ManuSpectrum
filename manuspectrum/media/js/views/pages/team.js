import initMsNav from "utils/ms-nav";
import initPasswordFields from "utils/accounts/password-field";
import revealOnScroll from "utils/reveal-on-scroll";

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

    initPasswordFields(document);

    revealOnScroll(0.1);
});
