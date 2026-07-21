import initMsNav from "utils/ms-nav";
import { tv as trv } from "utils/i18n";
import revealOnScroll from "utils/reveal-on-scroll";

function countUp() {
    const reduce = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
    ).matches;
    const locale = document.documentElement.lang || "en";
    document.querySelectorAll(".ms-cm-stat-value[data-count]").forEach((el) => {
        const target = parseInt(el.dataset.count, 10);
        // WAVE 4b: the tiles now carry affixes ("41%", "~20,000"). Writing a bare
        // Number here used to erase them, so the animation ended on a figure that
        // said something different from the markup it replaced. Grouping comes
        // from the page language, so FR renders "~20 000".
        const prefix = el.dataset.prefix || "";
        const suffix = el.dataset.suffix || "";
        const fmt = (n) => `${prefix}${n.toLocaleString(locale)}${suffix}`;
        if (reduce) {
            el.textContent = fmt(target);
            return;
        }
        let n = 0;
        const step = Math.max(1, Math.round(target / 40));
        const tick = () => {
            n = Math.min(target, n + step);
            el.textContent = fmt(n);
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

// Live figures. Every number on this page is derivable from /api/model-graph, and
// a hardcoded figure is a figure that will eventually be wrong — this section
// already published "84 relationships" for a while when the live answer was 70.
// The markup ships today's values so the page is correct without JS; this
// upgrades them in place before the count-up animation reads `data-count`.
// textContent only — nothing here is interpolated into innerHTML.
function setStat(box, stat, count, opts) {
    const tile = box.querySelector(`[data-stat="${stat}"]`);
    if (!tile) return;
    const value = tile.querySelector(".ms-cm-stat-value");
    const label = tile.querySelector(".ms-cm-stat-label");
    if (value && Number.isFinite(count)) value.dataset.count = String(count);
    if (label && opts && opts.label) label.textContent = opts.label;
}

async function liveFigures() {
    const box = document.getElementById("ms-cm-stats");
    if (!box || !box.dataset.api) return;
    let s;
    try {
        const res = await fetch(box.dataset.api, {
            headers: { Accept: "application/json" },
        });
        if (!res.ok) return; // keep the server-rendered fallback figures
        s = (await res.json()).stats;
    } catch {
        return;
    }
    if (!s || s.nodes === undefined) return;

    setStat(box, "thesaurus", s.thesaurus_pct, {
        label: trv(
            "msCmThesaurusLabel",
            "of fields draw on a published thesaurus, not free text — {n} of {total}",
            { n: s.thesaurus_nodes, total: s.nodes },
        ),
    });
    setStat(box, "cidoc", s.cidoc_classes);
    setStat(box, "relations", s.relations, {
        label: trv(
            "msCmRelationsLabel",
            "typed relationships across {models} interconnected models",
            {
                models: s.models,
            },
        ),
    });
    setStat(box, "concepts", s.concepts);

    const models = document.getElementById("ms-cm-models-line");
    if (models) {
        models.textContent = trv(
            "msCmModelsLine",
            "{models} independent models linked by {relations} typed CIDOC relationships — so a person recorded once as an analyst is the same record when they reappear as a manuscript's owner.",
            { models: s.models, relations: s.relations },
        );
    }
    const tech = document.getElementById("ms-cm-technical-line");
    if (tech) {
        // "32 controlled lists" is deliberately absent: arches_controlled_lists is
        // not installed, so no code here can verify that figure.
        tech.textContent = trv(
            "msCmTechnical",
            "{nodegroups} field groups · {total} nodes ({data} of them data) · {properties} ontology properties · {thesauri} thesauri.",
            {
                nodegroups: s.nodegroups,
                total: s.total_nodes,
                data: s.nodes,
                properties: s.properties,
                thesauri: s.thesauri,
            },
        );
    }
}

document.addEventListener("DOMContentLoaded", () => {
    initMsNav();
    revealOnScroll();
    // Patch the figures first, then animate — countUp reads `data-count`, so
    // running it before the fetch would count up to the stale number.
    liveFigures().finally(countUp);
});
