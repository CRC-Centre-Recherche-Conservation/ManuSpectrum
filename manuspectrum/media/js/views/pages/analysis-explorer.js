import initMsNav from "utils/ms-nav";

// Loaded with import() so the Vue application stays in its own chunk: a
// static import from media/js is pulled into every admin entry.
function showFallback() {
    document.getElementById("ms-explorer-fallback")?.removeAttribute("hidden");
    document
        .getElementById("ms-explorer-app")
        ?.setAttribute("aria-busy", "false");
}

initMsNav();

import(
    /* webpackChunkName: "analysis-explorer" */ "@/manuspectrum/pages/AnalysisExplorer/bootstrap.ts"
)
    .then(({ startAnalysisExplorer }) => startAnalysisExplorer())
    .catch((error) => {
        console.error("The analysis explorer could not start", error);
        showFallback();
    });
