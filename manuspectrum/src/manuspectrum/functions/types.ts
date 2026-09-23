// Shapes of the two endpoints the summary configuration form talks to:
// `manuspectrum:summary-config` (read, write and remove) and
// `manuspectrum:relatable-nodes` (read). The configuration types mirror
// `manuspectrum/functions/resource_summary.py`, so the snake_case keys are the
// ones stored in `functions_x_graphs.config` and must not be renamed here.

export type FieldStyle = "text" | "date" | "chip" | "number" | "link" | "image";
export type AggregateOp = "count" | "distinct";
export type HopDirection = "incoming" | "outgoing";

export interface LocalizedLabel {
    en?: string;
    fr?: string;
}

export interface SummaryField {
    alias: string;
    style: FieldStyle;
    max_values?: number;
    label?: LocalizedLabel;
}

export interface SummaryHop {
    graph_slug: string;
    alias: string;
    direction: HopDirection;
}

export interface SummaryAggregate {
    op: AggregateOp;
    alias?: string;
    style?: FieldStyle;
    limit?: number;
}

export interface SummaryRollup {
    key: string;
    label?: LocalizedLabel;
    path: SummaryHop[];
    aggregate: SummaryAggregate[];
    max_related: number;
}

export interface SummaryConfig {
    config_version: number;
    fields: SummaryField[];
    rollups: SummaryRollup[];
}

// A row as the form holds it. `uid` is what Vue keys the list on, so an edit
// or a reorder follows the row it belongs to rather than its position; it is
// minted client-side and stripped from what `saveConfig` sends.
export type EditableRow<T> = T & { uid: string };

export interface EditableConfig
    extends Omit<SummaryConfig, "fields" | "rollups"> {
    fields: EditableRow<SummaryField>[];
    rollups: EditableRow<SummaryRollup>[];
}

export interface SummaryConfigResponse {
    graphid: string;
    config: SummaryConfig;
    warnings: string[];
    attached: boolean;
}

// A stored state with the ETag it was answered with, echoed as `If-Match` by
// the next write. `null` when the answer carried none: that write is then
// unconditional.
export interface VersionedConfig extends SummaryConfigResponse {
    etag: string | null;
}

export interface NamedGraph {
    graphid: string;
    slug: string;
    name: string;
}

export interface RelatableField {
    alias: string;
    datatype: string;
    label: string;
}

export interface OutgoingRelation {
    alias: string;
    label: string;
    targets: NamedGraph[];
}

export interface IncomingRelation {
    graph_slug: string;
    graph_name: string;
    alias: string;
    label: string;
}

export interface AggregatableAlias {
    alias: string;
    label: string;
}

export interface RelatableNodes {
    graph: NamedGraph;
    fields: RelatableField[];
    outgoing: OutgoingRelation[];
    incoming: IncomingRelation[];
    aggregatable: Record<string, AggregatableAlias[]>;
}

// One option of a select: the value stored in the configuration, and the text
// shown for it. Option texts that are words rather than data are translated
// where they are built, which is why no list of them lives in this file.
export interface LabeledChoice<T extends string> {
    value: T;
    label: string;
}

// A model a hop may name. The slug is what the configuration stores; the name
// is what the curator reads, already localized by the endpoint.
export interface InvolvedGraph {
    slug: string;
    name: string;
}
