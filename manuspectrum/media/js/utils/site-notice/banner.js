/*
 * Site notice banner, served as a native ES module (no webpack) by
 * templates/includes/ms_site_notice.htm. Reads `GET /api/site-notice`, picks
 * the announcement to show at the server's time (core.js), and renders it as
 * the first child of <body>. Every visible string comes from the payload;
 * payload text goes in through textContent only.
 */
import {
    STORAGE_KEY,
    pickLanguage,
    pickNotice,
    stageOf,
    dismissKey,
    shouldShow,
    serverSkew,
    formatWhen,
    safeHref,
    readDismissed,
    rememberDismissal,
} from "./core.js";

const TICK_MS = 30 * 1000;
const REFETCH_MS = 5 * 60 * 1000;
const SVG_NS = "http://www.w3.org/2000/svg";

const ICONS = {
    info: ["circle", "M12 8h.01", "M11 12h1v5"],
    maintenance: [
        "M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.4 2.4-2.6-.6-.6-2.6z",
    ],
    important: ["M12 3 2 20h20z", "M12 10v4", "M12 17h.01"],
    dismiss: ["M6 6l12 12", "M18 6 6 18"],
};

function svgIcon(name) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", "16");
    svg.setAttribute("height", "16");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("focusable", "false");
    for (const d of ICONS[name]) {
        if (d === "circle") {
            const circle = document.createElementNS(SVG_NS, "circle");
            circle.setAttribute("cx", "12");
            circle.setAttribute("cy", "12");
            circle.setAttribute("r", "9");
            svg.appendChild(circle);
        } else {
            const path = document.createElementNS(SVG_NS, "path");
            path.setAttribute("d", d);
            svg.appendChild(path);
        }
    }
    return svg;
}

function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

/**
 * Starts the banner for the `<script>` element carrying `data-url`.
 * Returns `destroy()`.
 */
export function init(script, options = {}) {
    const fetchImpl = options.fetch || ((...args) => window.fetch(...args));
    const kinds = Object.keys(ICONS).filter((kind) => kind !== "dismiss");
    const previewId = new URLSearchParams(window.location.search).get(
        "ms-notice-preview",
    );
    const state = {
        payload: null,
        skew: 0,
        section: null,
        signature: null,
        observer: null,
        previewClosed: false,
    };
    const timers = [];
    let destroyed = false;

    function endpoint() {
        const url = script.dataset.url;
        return previewId && /^\d+$/.test(previewId)
            ? `${url}?preview=${previewId}`
            : url;
    }

    function setHeight(height) {
        const root = document.documentElement;
        if (height > 0) {
            root.style.setProperty("--ms-notice-h", `${height}px`);
            document.body.classList.add("ms-has-notice");
        } else {
            root.style.removeProperty("--ms-notice-h");
            document.body.classList.remove("ms-has-notice");
        }
    }

    function measure() {
        if (state.section)
            setHeight(Math.ceil(state.section.getBoundingClientRect().height));
    }

    function remove() {
        if (state.observer) {
            state.observer.disconnect();
            state.observer = null;
        }
        window.removeEventListener("resize", measure);
        if (state.section) state.section.remove();
        state.section = null;
        state.signature = null;
        setHeight(0);
    }

    function dismiss(notice, key, preview) {
        if (preview) state.previewClosed = true;
        else {
            rememberDismissal(
                notice.id,
                key,
                (state.payload.notices || []).map((item) => item.id),
            );
        }
        if (state.section && state.section.contains(document.activeElement))
            document.activeElement.blur();
        remove();
    }

    function build(notice, stage, labels, lang, preview, key) {
        const kind = kinds.includes(notice.kind) ? notice.kind : "info";
        const live = stage.phase === "live";
        const section = element(
            "section",
            `ms-notice ms-notice--${kind}${live ? " ms-notice--live" : ""}`,
        );
        section.setAttribute("role", "region");
        section.setAttribute("aria-label", labels.region || "");
        section.dataset.kind = kind;

        const inner = element("div", "ms-notice__inner");
        const icon = element("span", "ms-notice__icon");
        icon.setAttribute("aria-hidden", "true");
        icon.appendChild(
            live ? element("span", "ms-notice__pulse") : svgIcon(kind),
        );
        inner.appendChild(icon);

        const body = element("p", "ms-notice__body");
        const kindName = (labels.kind && labels.kind[kind]) || "";
        const kindLabel =
            live && labels.live ? `${kindName} · ${labels.live}` : kindName;
        body.appendChild(element("span", "ms-notice__kind", kindLabel));
        body.appendChild(document.createTextNode(" "));
        if (notice.display !== "once") {
            const when = formatWhen(
                notice,
                stage,
                lang,
                state.payload.timeZone,
                labels,
            );
            body.appendChild(element("strong", "ms-notice__when", when));
            body.appendChild(document.createTextNode(" "));
        }
        const text = notice.text || {};
        body.appendChild(
            element("span", "ms-notice__text", text[lang] || text.en || ""),
        );
        const href = notice.link && safeHref(notice.link.url);
        if (href) {
            const label = notice.link.label || {};
            const link = element(
                "a",
                "ms-notice__link",
                label[lang] || label.en || href,
            );
            link.href = href;
            body.appendChild(document.createTextNode(" "));
            body.appendChild(link);
        }
        inner.appendChild(body);

        const button = element("button", "ms-notice__dismiss");
        button.type = "button";
        button.setAttribute("aria-label", labels.dismiss || "");
        button.appendChild(svgIcon("dismiss"));
        button.addEventListener("click", () => dismiss(notice, key, preview));
        inner.appendChild(button);
        section.appendChild(inner);
        section.addEventListener("keydown", (event) => {
            if (event.key === "Escape") dismiss(notice, key, preview);
        });
        return section;
    }

    function evaluate() {
        if (destroyed || !state.payload) return;
        const preview = Boolean(state.payload.preview);
        if (preview && state.previewClosed) return;
        const now = Date.now() + state.skew;
        const dismissed = readDismissed();
        const notice =
            pickNotice(state.payload.notices, now, dismissed) ||
            (preview ? (state.payload.notices || [])[0] : null);
        if (!notice) return remove();
        let stage = stageOf(notice, now);
        if (preview && !["live", "shown"].includes(stage.phase)) {
            stage =
                notice.display === "once"
                    ? { phase: "shown", reminder: null }
                    : { phase: "upcoming", reminder: stage.reminder };
        }
        const key = dismissKey(notice, stage);
        if (!preview && !shouldShow(stage, dismissed[notice.id], key))
            return remove();
        const signature = `${key}:${stage.phase}`;
        if (state.section && state.signature === signature) return;

        const lang = pickLanguage(document.documentElement.lang);
        const all = state.payload.labels || {};
        const labels = all[lang] || all.en || {};
        remove();
        state.section = build(notice, stage, labels, lang, preview, key);
        state.signature = signature;
        document.body.insertBefore(state.section, document.body.firstChild);
        measure();
        if (typeof window.ResizeObserver === "function") {
            state.observer = new window.ResizeObserver(measure);
            state.observer.observe(state.section);
        } else {
            window.addEventListener("resize", measure);
        }
    }

    async function load() {
        try {
            const response = await fetchImpl(endpoint(), {
                headers: { Accept: "application/json" },
                cache: "no-cache",
            });
            if (!response.ok) return;
            const payload = await response.json();
            if (!payload || !Array.isArray(payload.notices)) return;
            state.payload = payload;
            state.skew = serverSkew(response.headers.get("Date"), Date.now());
            evaluate();
        } catch {
            // The banner is optional: a failed fetch leaves the page as it is.
        }
    }

    function onStorage(event) {
        if (event.key === STORAGE_KEY || event.key === null) evaluate();
    }

    function onVisible() {
        if (document.visibilityState === "visible") load();
    }

    window.addEventListener("storage", onStorage);
    document.addEventListener("visibilitychange", onVisible);
    timers.push(setInterval(evaluate, TICK_MS), setInterval(load, REFETCH_MS));
    const ready = load();

    return {
        ready,
        destroy() {
            destroyed = true;
            timers.forEach(clearInterval);
            window.removeEventListener("storage", onStorage);
            document.removeEventListener("visibilitychange", onVisible);
            remove();
        },
    };
}

const script =
    typeof document !== "undefined"
        ? document.getElementById("ms-site-notice")
        : null;
if (script && script.dataset.url) init(script);
