import { onBeforeUnmount, onMounted, watch } from "vue";

export type HistoryMode = "push" | "replace" | "none";

export interface UrlStateBinding<S> {
    snapshot: () => S;
    toQuery: (state: S) => URLSearchParams;
    apply: (query: URLSearchParams) => void;
    historyMode: (previous: S, next: S) => HistoryMode;
}

const LANGUAGE_LINKS = ".ms-lang-switch a[hreflang]";
const NEXT_LINKS =
    "#ms-header a[href*='next='], #ms-mobile-nav a[href*='next=']";
const NEXT_PARAM = "next";

function searchOf(query: URLSearchParams): string {
    const serialized = query.toString();
    return serialized ? `?${serialized}` : "";
}

/**
 * Point the server-rendered header at the current state of a public application.
 *
 * Language links keep their server-built origin and path and take the current
 * query. `next=` links take the current path and query, only when the path is
 * a same-origin absolute path (it starts with one "/"); otherwise "/".
 */
export function rewriteHeaderLinks(
    location: Pick<Location, "pathname" | "search">,
    root: ParentNode = document,
): void {
    for (const link of root.querySelectorAll<HTMLAnchorElement>(
        LANGUAGE_LINKS,
    )) {
        const target = new URL(link.href);
        target.search = location.search;
        link.setAttribute("href", target.toString());
    }
    const sameOrigin =
        location.pathname.startsWith("/") &&
        !location.pathname.startsWith("//");
    const next = sameOrigin ? `${location.pathname}${location.search}` : "/";
    for (const link of root.querySelectorAll<HTMLAnchorElement>(NEXT_LINKS)) {
        const target = new URL(link.href);
        target.searchParams.set(NEXT_PARAM, next);
        link.setAttribute(
            "href",
            `${target.pathname}${target.search}${target.hash}`,
        );
    }
}

/**
 * Keep the page URL and a piece of reactive state in step.
 *
 * On setup the current location is applied, then rewritten canonically with
 * replaceState. A state change writes history in the mode the binding
 * chooses, and only when the canonical query differs from the location, so
 * applying a popstate never writes history. The header links follow every
 * change.
 */
export function useUrlState<S>(binding: UrlStateBinding<S>): void {
    function write(mode: "push" | "replace"): void {
        const search = searchOf(binding.toQuery(binding.snapshot()));
        if (search !== window.location.search) {
            const url = `${window.location.pathname}${search}${window.location.hash}`;
            if (mode === "push") {
                window.history.pushState(null, "", url);
            } else {
                window.history.replaceState(null, "", url);
            }
        }
        rewriteHeaderLinks(window.location);
    }

    function adoptLocation(): void {
        binding.apply(new URLSearchParams(window.location.search));
        write("replace");
    }

    adoptLocation();

    watch(binding.snapshot, (next, previous) => {
        const mode = binding.historyMode(previous, next);
        if (mode !== "none") {
            write(mode);
        }
    });

    onMounted(() => window.addEventListener("popstate", adoptLocation));
    onBeforeUnmount(() =>
        window.removeEventListener("popstate", adoptLocation),
    );
}
