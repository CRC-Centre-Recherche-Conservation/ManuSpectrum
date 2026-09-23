/**
 * Analysis points on the manuscript image, each opening its server-rendered
 * popup (`aria-controls` → `#ms-analysis-popup-N`, initially `hidden`).
 *
 * Opening removes `hidden` first, measures the popup and positions it inside
 * the viewer, then adds `.active` on the next animation frame so the CSS fade
 * plays. Closing removes `.active` and restores `hidden` on the opacity
 * `transitionend` (350 ms fallback); reopening cancels a pending hide. One
 * popup is open at a time. The document listeners (Escape, outside click)
 * exist only while a popup is open; an outside click is one outside every
 * popup and every point, and propagation is never stopped.
 */
const HIDE_FALLBACK_MS = 350;
const GAP = 8;
const EDGE = 4;

/**
 * @param {ParentNode} [root=document]
 * @returns {() => void} closes any popup and removes the listeners
 */
export default function initAnalysisViewer(root = document) {
    const viewer = root.querySelector("#ms-analysis-viewer");
    if (!viewer) {
        return () => {};
    }
    const points = Array.from(viewer.querySelectorAll(".ms-analysis-point"));
    const pendingHide = new Map();
    let open = null;
    let frame = 0;

    const popupOf = (point) => viewer.querySelector(`#${point.getAttribute("aria-controls")}`);

    const cancelHide = (popup) => {
        const cancel = pendingHide.get(popup);
        if (cancel) {
            cancel();
        }
    };
    const scheduleHide = (popup) => {
        cancelHide(popup);
        let timer = 0;
        const onEnd = (event) => {
            if (event.target === popup && event.propertyName === "opacity") {
                done();
            }
        };
        const cleanup = () => {
            clearTimeout(timer);
            popup.removeEventListener("transitionend", onEnd);
            pendingHide.delete(popup);
        };
        const done = () => {
            cleanup();
            popup.hidden = true;
        };
        timer = setTimeout(done, HIDE_FALLBACK_MS);
        popup.addEventListener("transitionend", onEnd);
        pendingHide.set(popup, cleanup);
    };
    const position = (point, popup) => {
        const box = viewer.getBoundingClientRect();
        const pt = point.getBoundingClientRect();
        const width = popup.offsetWidth;
        const height = popup.offsetHeight;
        let left = pt.left - box.left + pt.width / 2 - width / 2;
        let top = pt.bottom - box.top + GAP;
        if (left < EDGE) {
            left = EDGE;
        }
        if (left + width > box.width - EDGE) {
            left = box.width - width - EDGE;
        }
        if (top + height > box.height) {
            top = pt.top - box.top - height - GAP;
        }
        if (top < EDGE) {
            top = EDGE;
        }
        popup.style.left = `${left}px`;
        popup.style.top = `${top}px`;
    };

    const onKey = (event) => {
        if (event.key === "Escape") {
            close();
        }
    };
    const onDocClick = (event) => {
        if (!event.target.closest(".ms-analysis-popup, .ms-analysis-point")) {
            close();
        }
    };
    function close() {
        if (!open) {
            return;
        }
        const { point, popup } = open;
        open = null;
        cancelAnimationFrame(frame);
        popup.classList.remove("active");
        point.classList.remove("active");
        point.setAttribute("aria-expanded", "false");
        viewer.classList.remove("has-popup");
        scheduleHide(popup);
        document.removeEventListener("keydown", onKey);
        document.removeEventListener("click", onDocClick);
    }
    function openFor(point) {
        const popup = popupOf(point);
        if (!popup) {
            return;
        }
        close();
        cancelHide(popup);
        popup.hidden = false;
        position(point, popup);
        point.classList.add("active");
        point.setAttribute("aria-expanded", "true");
        viewer.classList.add("has-popup");
        frame = requestAnimationFrame(() => popup.classList.add("active"));
        open = { point, popup };
        document.addEventListener("keydown", onKey);
        document.addEventListener("click", onDocClick);
    }
    const onPoint = (event) => {
        const point = event.currentTarget;
        if (open && open.point === point) {
            close();
        } else {
            openFor(point);
        }
    };

    points.forEach((point) => point.addEventListener("click", onPoint));
    return () => {
        close();
        pendingHide.forEach((cancel) => cancel());
        points.forEach((point) => point.removeEventListener("click", onPoint));
    };
}
