// Transport and pure helpers of the summary configuration form. No user-facing
// string lives here: a failure is thrown and the component words it.

import { generateArchesURL } from "@/arches/utils/generate-arches-url.ts";

import type {
    EditableConfig,
    FieldStyle,
    InvolvedGraph,
    RelatableNodes,
    SummaryConfig,
    SummaryConfigResponse,
    SummaryHop,
} from "@/manuspectrum/functions/types.ts";

export const CONFIG_VERSION = 1;
export const MAX_HOPS = 2;
export const MAX_VALUES = 10;
export const MAX_DISTINCT_LIMIT = 10;
export const MAX_RELATED = 500;
export const DEFAULT_DISTINCT_LIMIT = 5;

const CONFIG_ROUTE = "manuspectrum:summary-config";
const RELATIONS_ROUTE = "manuspectrum:relatable-nodes";
const CSRF_COOKIE = "csrftoken";

// Datatypes whose values the popup renders as something other than plain text.
// Anything absent falls back to "text", which every datatype can be shown as.
const STYLE_BY_DATATYPE: Record<string, FieldStyle> = {
    date: "date",
    edtf: "date",
    reference: "chip",
    concept: "chip",
    "concept-list": "chip",
    "domain-value": "chip",
    "domain-value-list": "chip",
    number: "number",
    "resource-instance": "link",
    "resource-instance-list": "link",
    "file-list": "image",
};

export function emptyConfig(): SummaryConfig {
    return { config_version: CONFIG_VERSION, fields: [], rollups: [] };
}

export function defaultStyleFor(datatype: string): FieldStyle {
    return STYLE_BY_DATATYPE[datatype] ?? "text";
}

let rowsCreated = 0;

/**
 * The identity one editor row is keyed on.
 *
 * A counter rather than a UUID: the value never leaves the page, and it only
 * has to tell the rows of one form apart.
 */
export function newRowUid(): string {
    rowsCreated += 1;
    return `row-${rowsCreated}`;
}

/** Take a stored configuration into the form, one identity per row. */
export function withRowUids(config: SummaryConfig): EditableConfig {
    return {
        ...config,
        fields: config.fields.map((field) => ({ ...field, uid: newRowUid() })),
        rollups: config.rollups.map((rollup) => ({
            ...rollup,
            uid: newRowUid(),
        })),
    };
}

/** One row as the endpoint stores it: the identity of a row never leaves. */
function withoutUid<T extends object>(row: T): T {
    const stored = { ...row } as T & { uid?: string };
    delete stored.uid;
    return stored;
}

/**
 * Models a hop of this graph may name, the graph being configured first.
 *
 * A hop names the node that records the link and the graph that node belongs
 * to, so the choices are this graph (for an outgoing hop) and every graph
 * either end of a relation reaches.
 */
export function involvedGraphs(
    relations: RelatableNodes | null,
): InvolvedGraph[] {
    if (!relations) {
        return [];
    }
    const choices: InvolvedGraph[] = [
        { slug: relations.graph.slug, name: relations.graph.name },
    ];
    const seen = new Set([relations.graph.slug]);
    const add = (slug: string, name: string) => {
        if (!seen.has(slug)) {
            seen.add(slug);
            choices.push({ slug, name });
        }
    };
    relations.incoming.forEach((relation) =>
        add(relation.graph_slug, relation.graph_name),
    );
    relations.outgoing.forEach((relation) =>
        relation.targets.forEach((target) => add(target.slug, target.name)),
    );
    return choices;
}

/**
 * Relation aliases known to be carried by one graph, towards the configured one.
 *
 * Complete for a first hop only: the endpoint reports the relations that touch
 * the configured model, not those between two other models.
 */
export function knownAliases(
    relations: RelatableNodes | null,
    graphSlug: string,
): string[] {
    if (!relations) {
        return [];
    }
    if (graphSlug === relations.graph.slug) {
        return relations.outgoing.map((relation) => relation.alias);
    }
    return relations.incoming
        .filter((relation) => relation.graph_slug === graphSlug)
        .map((relation) => relation.alias);
}

/** First hop of a new rollup: a relation that already exists, when there is one. */
export function blankHop(relations: RelatableNodes | null): SummaryHop {
    if (!relations) {
        return { graph_slug: "", alias: "", direction: "incoming" };
    }
    const [incoming] = relations.incoming;
    if (incoming) {
        return {
            graph_slug: incoming.graph_slug,
            alias: incoming.alias,
            direction: "incoming",
        };
    }
    const [outgoing] = relations.outgoing;
    return {
        graph_slug: relations.graph.slug,
        alias: outgoing ? outgoing.alias : "",
        direction: outgoing ? "outgoing" : "incoming",
    };
}

/** Value of Django's CSRF cookie, empty when the browser carries none. */
export function csrfToken(): string {
    const match = document.cookie.match(
        new RegExp(`(?:^|;\\s*)${CSRF_COOKIE}=([^;]*)`),
    );
    return match ? decodeURIComponent(match[1]) : "";
}

async function readJson<T>(response: Response): Promise<T> {
    if (!response.ok) {
        throw new Error(String(response.status));
    }
    return (await response.json()) as T;
}

export async function fetchConfig(
    graphid: string,
): Promise<SummaryConfigResponse> {
    const response = await fetch(generateArchesURL(CONFIG_ROUTE, { graphid }), {
        credentials: "same-origin",
    });
    return readJson<SummaryConfigResponse>(response);
}

export async function saveConfig(
    graphid: string,
    config: SummaryConfig,
): Promise<SummaryConfigResponse> {
    const response = await fetch(generateArchesURL(CONFIG_ROUTE, { graphid }), {
        method: "PUT",
        credentials: "same-origin",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": csrfToken(),
        },
        body: JSON.stringify({
            config: {
                ...config,
                fields: config.fields.map(withoutUid),
                rollups: config.rollups.map(withoutUid),
            },
        }),
    });
    return readJson<SummaryConfigResponse>(response);
}

export async function fetchRelations(graphid: string): Promise<RelatableNodes> {
    const response = await fetch(
        generateArchesURL(RELATIONS_ROUTE, { graphid }),
        {
            credentials: "same-origin",
        },
    );
    return readJson<RelatableNodes>(response);
}
