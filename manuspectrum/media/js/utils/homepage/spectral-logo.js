/**
 * Interactive hero logo: a crosshair and tooltip that read the two curves,
 * and a zoomed view in a native <dialog>.
 *
 * Each curve is sampled once, on the first pointer move, into a table of y at
 * integer x from X_MIN to X_MAX (linear interpolation between samples; past
 * the end of the path the table holds its last y). A move reads the table and
 * writes the DOM once per animation frame; leaving cancels the pending frame.
 * Opening the dialog moves the SVG into it and marks it `is-drawn`, so the
 * draw-in animation never replays; closing (Close button, Escape, or a click
 * that starts and ends on the backdrop) moves it back and returns focus to
 * the zoom button. The zoom button is hidden when the browser has no
 * `<dialog>.showModal` support.
 */
export const X_MIN = 40;
export const X_MAX = 620;
const Y_MIN = 4;
const Y_MAX = 82;
const WL_MIN = 380;
const WL_MAX = 780;
const BLUE_END = 438;
const RED_END = 444;
const SAMPLE_STEP = 2;

/**
 * @param {{ getTotalLength(): number, getPointAtLength(s: number): {x: number, y: number} }} path
 * @returns {Float64Array} y for every integer x in [X_MIN, X_MAX]
 */
export function sampleCurve(path) {
    const length = path.getTotalLength();
    const points = [];
    for (let s = 0; s < length; s += SAMPLE_STEP) {
        points.push(path.getPointAtLength(s));
    }
    points.push(path.getPointAtLength(length));
    const first = points[0];
    const last = points[points.length - 1];
    const table = new Float64Array(X_MAX - X_MIN + 1);
    let j = 0;
    for (let x = X_MIN; x <= X_MAX; x++) {
        if (x <= first.x) {
            table[x - X_MIN] = first.y;
            continue;
        }
        if (x >= last.x) {
            table[x - X_MIN] = last.y;
            continue;
        }
        while (j < points.length - 2 && points[j + 1].x < x) {
            j++;
        }
        const a = points[j];
        const b = points[j + 1];
        table[x - X_MIN] = b.x === a.x ? a.y : a.y + ((x - a.x) / (b.x - a.x)) * (b.y - a.y);
    }
    return table;
}

/** @returns {number} y at a fractional x, interpolated between table entries */
export function readTable(table, x) {
    const i = Math.max(0, Math.min(table.length - 1, x - X_MIN));
    const lo = Math.floor(i);
    const hi = Math.min(lo + 1, table.length - 1);
    return table[lo] + (i - lo) * (table[hi] - table[lo]);
}

export const toIntensity = (y) => Math.max(0, Math.min(1, (Y_MAX - y) / (Y_MAX - Y_MIN)));
export const toWavelength = (x) => WL_MIN + ((x - X_MIN) / (X_MAX - X_MIN)) * (WL_MAX - WL_MIN);

const setAttrs = (el, attrs) => Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));

function initCrosshair(svg) {
    const byId = (id) => svg.querySelector(`#${id}`);
    const curveBlue = byId("curve-blue");
    const curveRed = byId("curve-red");
    const crosshair = byId("ms-logo-crosshair");
    const tooltip = byId("ms-logo-tooltip");
    if (!curveBlue || !curveRed || !crosshair || !tooltip) {
        return () => {};
    }
    const crossV = byId("ms-cross-v");
    const crossHB = byId("ms-cross-h-blue");
    const crossHR = byId("ms-cross-h-red");
    const dotBlue = byId("ms-dot-blue");
    const dotRed = byId("ms-dot-red");
    const ttBg = byId("ms-tt-bg");
    const ttWl = byId("ms-tt-wl");
    const ttBlue = byId("ms-tt-blue");
    const ttRed = byId("ms-tt-red");
    let tables = null;
    let frame = 0;
    let x = null;

    const show = (on) => {
        crosshair.setAttribute("display", on ? "inline" : "none");
        tooltip.setAttribute("display", on ? "inline" : "none");
    };
    const hide = () => {
        x = null;
        if (frame) {
            cancelAnimationFrame(frame);
            frame = 0;
        }
        show(false);
    };
    const render = () => {
        frame = 0;
        if (x === null) {
            return;
        }
        const yB = readTable(tables.blue, x);
        const yR = readTable(tables.red, x);
        const showBlue = x <= BLUE_END;
        const showRed = x <= RED_END;
        setAttrs(crossV, { x1: x, x2: x });
        setAttrs(dotBlue, { cx: x, cy: yB, opacity: showBlue ? "0.9" : "0" });
        setAttrs(crossHB, { y1: yB, y2: yB, x2: x, opacity: showBlue ? "0.35" : "0" });
        setAttrs(dotRed, { cx: x, cy: yR, opacity: showRed ? "0.9" : "0" });
        setAttrs(crossHR, { y1: yR, y2: yR, x2: x, opacity: showRed ? "0.35" : "0" });
        let tx = x + 8;
        let ty = Math.min(yB, yR) - 48;
        if (tx + 125 > X_MAX) {
            tx = x - 130;
        }
        if (ty < 0) {
            ty = 4;
        }
        setAttrs(ttBg, { x: tx, y: ty });
        setAttrs(ttWl, { x: tx + 6, y: ty + 12 });
        ttWl.textContent = `λ = ${Math.round(toWavelength(x))} nm`;
        setAttrs(ttBlue, { x: tx + 6, y: ty + 24 });
        ttBlue.textContent = showBlue ? `● I₁ = ${toIntensity(yB).toFixed(3)}` : "";
        setAttrs(ttRed, { x: tx + 6, y: ty + 35 });
        ttRed.textContent = showRed ? `● I₂ = ${toIntensity(yR).toFixed(3)}` : "";
        show(true);
    };
    const onMove = (event) => {
        const pt = svg.createSVGPoint();
        pt.x = event.clientX;
        pt.y = event.clientY;
        const px = pt.matrixTransform(svg.getScreenCTM().inverse()).x;
        if (px < X_MIN || px > X_MAX) {
            hide();
            return;
        }
        if (!tables) {
            tables = { blue: sampleCurve(curveBlue), red: sampleCurve(curveRed) };
        }
        x = px;
        if (!frame) {
            frame = requestAnimationFrame(render);
        }
    };

    svg.addEventListener("pointermove", onMove);
    svg.addEventListener("pointerleave", hide);
    svg.addEventListener("pointercancel", hide);
    return () => {
        hide();
        svg.removeEventListener("pointermove", onMove);
        svg.removeEventListener("pointerleave", hide);
        svg.removeEventListener("pointercancel", hide);
    };
}

function initZoom(root, svg) {
    const dialog = root.querySelector("#ms-logo-dialog");
    const zoom = root.querySelector("#ms-logo-zoom");
    const closeButton = root.querySelector("#ms-logo-close");
    const target = root.querySelector("#ms-logo-zoom-target");
    const home = root.querySelector("#ms-logo-wrap");
    if (!dialog || !zoom || !target || !home) {
        return () => {};
    }
    if (typeof dialog.showModal !== "function") {
        zoom.hidden = true;
        return () => {};
    }
    let downOnBackdrop = false;
    const open = () => {
        svg.classList.add("is-drawn");
        target.append(svg);
        dialog.showModal();
    };
    const onClose = () => {
        home.prepend(svg);
        zoom.focus();
    };
    const onCloseButton = () => dialog.close();
    const onDown = (event) => {
        downOnBackdrop = event.target === dialog;
    };
    const onClick = (event) => {
        if (downOnBackdrop && event.target === dialog) {
            dialog.close();
        }
        downOnBackdrop = false;
    };

    zoom.addEventListener("click", open);
    if (closeButton) {
        closeButton.addEventListener("click", onCloseButton);
    }
    dialog.addEventListener("pointerdown", onDown);
    dialog.addEventListener("click", onClick);
    dialog.addEventListener("close", onClose);
    return () => {
        zoom.removeEventListener("click", open);
        if (closeButton) {
            closeButton.removeEventListener("click", onCloseButton);
        }
        dialog.removeEventListener("pointerdown", onDown);
        dialog.removeEventListener("click", onClick);
        dialog.removeEventListener("close", onClose);
    };
}

/**
 * @param {ParentNode} [root=document]
 * @returns {() => void} removes the listeners
 */
export default function initSpectralLogo(root = document) {
    const svg = root.querySelector("#ms-logo-svg");
    if (!svg) {
        return () => {};
    }
    const stopCrosshair = initCrosshair(svg);
    const stopZoom = initZoom(root, svg);
    return () => {
        stopCrosshair();
        stopZoom();
    };
}
