import listen, { stopAll } from "./listen";

/**
 * XRF comparison: the mercury map (top image) is clipped at `--split` to
 * reveal the calcium map beneath.
 *
 * - Mouse: the split follows the pointer and returns to 100 on leave, unless
 *   the range has focus.
 * - Touch and pen: pressing sets the split where the finger is and dragging
 *   moves it; it stays where the finger lifts.
 * - Keyboard and assistive technologies: the visually hidden range.
 *
 * Every source updates both `range.value` and `--split` (always with `%`), and
 * `is-comparing` is set while the split is below 100.
 */

/**
 * @param {ParentNode} [root=document]
 * @returns {() => void} removes the listeners
 */
export default function initXrfCompare(root = document) {
    const box = root.querySelector("#ms-xrf-compare");
    const range = box ? box.querySelector(".ms-compare-range") : null;
    if (!box || !range) {
        return () => {};
    }
    let pressed = false;

    const setSplit = (value) => {
        const split = Math.max(0, Math.min(100, Math.round(value)));
        range.value = String(split);
        box.style.setProperty("--split", `${split}%`);
        box.classList.toggle("is-comparing", split < 100);
    };
    const fromPointer = (event) => {
        const rect = box.getBoundingClientRect();
        return rect.width ? ((event.clientX - rect.left) / rect.width) * 100 : 100;
    };
    const onMove = (event) => {
        if (event.pointerType === "mouse" || pressed) {
            setSplit(fromPointer(event));
        }
    };
    const onDown = (event) => {
        if (event.pointerType !== "mouse") {
            pressed = true;
            setSplit(fromPointer(event));
        }
    };
    const onUp = () => {
        pressed = false;
    };
    const onLeave = (event) => {
        pressed = false;
        if (event.pointerType === "mouse" && document.activeElement !== range) {
            setSplit(100);
        }
    };
    const onInput = () => setSplit(Number(range.value));

    const stops = [
        listen(box, "pointermove", onMove),
        listen(box, "pointerdown", onDown),
        listen(box, "pointerup", onUp),
        listen(box, "pointercancel", onUp),
        listen(box, "pointerleave", onLeave),
        listen(range, "input", onInput),
    ];
    return () => stopAll(stops);
}
