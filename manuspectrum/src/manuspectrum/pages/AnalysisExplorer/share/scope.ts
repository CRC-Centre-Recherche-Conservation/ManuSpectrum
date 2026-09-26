import { hasActiveFilters } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type {
    BasketItem,
    CorpusScreen,
    DocumentState,
    ExplorerView,
    Filters,
    ItemKey,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

/** What « Share and export » can export, as the share route names it. */
export type OfferedScope =
    | { kind: "document"; id: string }
    | { kind: "ids"; keys: ItemKey[] }
    | { kind: "project"; id: string };

/** The part of the Explorer state the offered scopes read. */
export interface ScopeState {
    view: ExplorerView;
    screen: CorpusScreen;
    document: DocumentState | null;
    basket: readonly BasketItem[];
    filters: Filters;
}

/**
 * The scopes the current view offers, most specific first: the open
 * document, the Selection when it holds items, a project filtered alone on
 * the Corpus results (one project filter and no other filter, text included).
 */
export function offeredScopes(state: ScopeState): OfferedScope[] {
    const scopes: OfferedScope[] = [];
    if (state.view !== "corpus") return scopes;
    if (state.screen === "document" && state.document) {
        scopes.push({ kind: "document", id: state.document.id });
    }
    if (state.basket.length > 0) {
        scopes.push({
            kind: "ids",
            keys: state.basket.map((item) => item.key).sort(),
        });
    }
    const projects = state.filters.project;
    if (
        state.screen === "results" &&
        projects.length === 1 &&
        !hasActiveFilters({ ...state.filters, project: [] })
    ) {
        scopes.push({ kind: "project", id: projects[0] });
    }
    return scopes;
}

/** The query of the share route and of the products for `scope`, keys sorted. */
export function shareQuery(scope: OfferedScope): URLSearchParams {
    return scope.kind === "ids"
        ? new URLSearchParams([...scope.keys].sort().map((key) => ["ids", key]))
        : new URLSearchParams([[scope.kind, scope.id]]);
}
