<script setup lang="ts">
import { useId } from "vue";
import { useGettext } from "vue3-gettext";

import FocusPip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusPip.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import {
    dashArray,
    isColoured,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";

import type { LinkedMark } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type {
    Dash,
    LegendGroup,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";

const TOGGLE_EVENT = "toggle" as const;
const PREVIEW_EVENT = "preview" as const;

export interface LegendToggleEvent {
    node: NodeId;
}

export interface LegendPreviewEvent {
    node: NodeId | null;
    pointerType: string;
    /** The entry under the pointer, which the trail of the focus follows. */
    anchor: Element | null;
}

/**
 * The legend of an XY window, the only one on screen: one entry per slot
 * on two lines (its label, analysis and technique code, then the
 * component and folio of its analysis and its file when it holds one),
 * its files under it when it holds several, each a toggle of its node in
 * the focus (`aria-pressed` while pinned). While something is pinned, an
 * entry carries the focus marks of the nodes its curves stand for
 * (`useLinkedMarks().focus`: ring, pip, bloom, `data-rel`), shown pinned
 * only while its own node is; an entry the focus does not light stays
 * listed, its swatch faded, its pip a « + »
 * under the pointer, and a description saying a press adds it. A mouse or
 * pen resting on an entry previews it.
 */
const props = defineProps<{
    groups: readonly LegendGroup[];
}>();

const emit = defineEmits<{
    (event: typeof TOGGLE_EVENT, payload: LegendToggleEvent): void;
    (event: typeof PREVIEW_EVENT, payload: LegendPreviewEvent): void;
}>();

const { $gettext } = useGettext();
const marks = useLinkedMarks();
const hintId = useId();

/** The `data-rel` of an entry: `self` only while its own node is pinned, else the strongest level of the other nodes its curves stand for. */
function entryRel(
    own: NodeId,
    nodes: readonly NodeId[],
): LinkedMark | undefined {
    const level = marks.rel(nodes);
    if (level !== "self" || marks.pressed(own) === "true") return level;
    return marks.rel(nodes.filter((id) => marks.pressed(id) === "false"));
}

/** Whether something is pinned and links none of the curves `nodes` stand for. */
function unrelated(nodes: readonly NodeId[]): boolean {
    return marks.rel(nodes) === "none";
}

/** The swatch of a line: its slot colour, a grey context slot in ink while the selection links it, as the chart draws it. */
function strokeOf(
    slot: number,
    dash: Dash,
    nodes: readonly NodeId[],
): Record<string, string> {
    const level = marks.rel(nodes);
    let stroke = "var(--series-context)";
    if (isColoured(slot)) stroke = `var(--series-${slot + 1})`;
    else if (level !== undefined && level !== "none") stroke = "var(--ink)";
    return { stroke, strokeDasharray: dashArray(dash) };
}

/** Whether a slot's entry has a second line: its component, its folio or its one file. */
function hasContext(group: LegendGroup): boolean {
    return (
        group.component !== null ||
        group.folio !== null ||
        group.entries.length === 1
    );
}

function toggle(node: NodeId): void {
    emit(TOGGLE_EVENT, { node });
}

function enter(node: NodeId, event: PointerEvent): void {
    const anchor =
        event.currentTarget instanceof Element ? event.currentTarget : null;
    emit(PREVIEW_EVENT, { node, pointerType: event.pointerType, anchor });
}

function leave(event: PointerEvent): void {
    emit(PREVIEW_EVENT, {
        node: null,
        pointerType: event.pointerType,
        anchor: null,
    });
}
</script>

<template>
    <div class="xy-legend">
        <ul
            class="groups"
            :aria-label="$gettext('Curves, by slot')"
        >
            <li
                v-for="group in props.groups"
                :key="group.slot"
                class="group"
            >
                <button
                    type="button"
                    class="entry ms-focus"
                    :class="{ unrelated: unrelated(group.nodes) }"
                    v-bind="marks.focus(group.nodes)"
                    :data-node="group.node"
                    :data-rel="entryRel(group.node, group.nodes)"
                    :aria-pressed="group.pressed ? 'true' : 'false'"
                    :aria-describedby="
                        unrelated(group.nodes) ? hintId : undefined
                    "
                    @click="toggle(group.node)"
                    @pointerenter="enter(group.node, $event)"
                    @pointerleave="leave"
                >
                    <FocusPip :node="group.nodes" />
                    <svg
                        class="swatch"
                        viewBox="0 0 24 8"
                        aria-hidden="true"
                    >
                        <line
                            x1="0"
                            y1="4"
                            x2="24"
                            y2="4"
                            :style="strokeOf(group.slot, 'solid', group.nodes)"
                        />
                    </svg>
                    <span class="id">
                        <span class="slot">{{ group.label }}</span>
                        <span
                            class="name"
                            :lang="group.analysis.lang"
                            :title="group.analysis.value"
                            >{{ group.analysis.value }}</span
                        >
                        <small
                            v-if="group.technique"
                            class="technique"
                            >{{ group.technique }}</small
                        >
                    </span>
                    <span
                        v-if="hasContext(group)"
                        class="ctx"
                    >
                        <template v-if="group.component">
                            <span
                                class="glyph"
                                aria-hidden="true"
                            ></span>
                            <span
                                class="component"
                                :lang="group.component.lang"
                                :title="group.component.value"
                                >{{ group.component.value }}</span
                            >
                        </template>
                        <span
                            v-if="group.component && group.folio"
                            aria-hidden="true"
                            >·</span
                        >
                        <span
                            v-if="group.folio"
                            class="folio"
                            >{{ group.folio }}</span
                        >
                        <span
                            v-if="
                                (group.component || group.folio) &&
                                group.entries.length === 1
                            "
                            aria-hidden="true"
                            >·</span
                        >
                        <span
                            v-if="group.entries.length === 1"
                            class="file"
                            :title="group.entries[0].name"
                            >{{ group.entries[0].name }}</span
                        >
                    </span>
                </button>
                <ul
                    v-if="group.entries.length > 1"
                    class="files"
                >
                    <li
                        v-for="entry in group.entries"
                        :key="entry.id"
                    >
                        <button
                            type="button"
                            class="entry ms-focus"
                            :class="{ unrelated: unrelated(entry.nodes) }"
                            v-bind="marks.focus(entry.nodes)"
                            :data-node="entry.node"
                            :data-rel="entryRel(entry.node, entry.nodes)"
                            :aria-pressed="entry.pressed ? 'true' : 'false'"
                            :aria-describedby="
                                unrelated(entry.nodes) ? hintId : undefined
                            "
                            @click="toggle(entry.node)"
                            @pointerenter="enter(entry.node, $event)"
                            @pointerleave="leave"
                        >
                            <FocusPip :node="entry.nodes" />
                            <svg
                                class="swatch"
                                viewBox="0 0 24 8"
                                aria-hidden="true"
                            >
                                <line
                                    x1="0"
                                    y1="4"
                                    x2="24"
                                    y2="4"
                                    :style="
                                        strokeOf(
                                            entry.slot,
                                            entry.dash,
                                            entry.nodes,
                                        )
                                    "
                                />
                            </svg>
                            <span
                                class="file"
                                :title="entry.name"
                                >{{ entry.name }}</span
                            >
                        </button>
                    </li>
                </ul>
            </li>
        </ul>
        <span
            :id="hintId"
            class="visually-hidden"
            >{{
                $gettext("Not linked to the selection: press to add it.")
            }}</span
        >
    </div>
</template>

<style scoped>
.xy-legend {
    min-inline-size: 0;
    font-size: 0.8125rem;
}

.xy-legend .groups,
.xy-legend .files {
    display: grid;
    gap: 0.125rem;
    list-style: none;
}

.xy-legend .files {
    padding-inline-start: 1rem;
}

.xy-legend .entry {
    --r: 0.5rem;
    --link-pip: 0.8125rem;
    display: grid;
    grid-template-columns: 1.5rem minmax(0, 1fr);
    align-items: center;
    gap: 0 0.5rem;
    inline-size: 100%;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-block: 0.25rem;
    padding-inline: 0.375rem;
    border: 0.0625rem solid transparent;
    border-radius: 0.5rem;
    background: transparent;
    color: var(--ink);
    font: inherit;
    text-align: start;
    cursor: pointer;
}

.xy-legend .group > .entry .swatch {
    grid-row: 1 / 3;
}

.xy-legend .entry:hover {
    background: var(--bg-alt);
}

.xy-legend .entry:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.0625rem;
}

.xy-legend
    .entry:is([data-rel="self"], [data-rel="direct"], [data-rel="evidence"]) {
    background: color-mix(
        in srgb,
        var(--h1, var(--focus-1)) 7%,
        var(--surface)
    );
}

.xy-legend .entry[data-preview] {
    background: color-mix(
        in srgb,
        var(--hp, var(--focus-1)) 5%,
        var(--surface)
    );
}

.xy-legend .entry[data-preview="evidence"] {
    background: color-mix(
        in srgb,
        var(--hp, var(--focus-1)) 3%,
        var(--surface)
    );
}

.xy-legend .entry.unrelated {
    color: var(--ink-muted);
}

.xy-legend .entry.unrelated .swatch {
    opacity: 0.35;
}

.xy-legend .swatch {
    inline-size: 1.5rem;
    block-size: 0.5rem;
    align-self: center;
    fill: none;
    stroke-width: 0.1875rem;
}

.xy-legend .id,
.xy-legend .ctx {
    display: flex;
    grid-column: 2;
    align-items: baseline;
    gap: 0.375rem;
    min-inline-size: 0;
    white-space: nowrap;
}

.xy-legend .ctx {
    align-items: center;
    gap: 0.25rem;
    color: var(--ink-muted);
    font-size: 0.6875rem;
}

.xy-legend .slot {
    font-family: var(--font-mono);
    font-weight: 600;
}

.xy-legend .technique {
    color: var(--ink-muted);
    font-size: 0.6875rem;
}

.xy-legend .glyph {
    flex: none;
    inline-size: 0.5625rem;
    block-size: 0.5625rem;
    border: 0.09375rem dashed var(--ink-dim);
    border-radius: 0.125rem;
}

.xy-legend .folio {
    font-family: var(--font-mono);
}

.xy-legend .name,
.xy-legend .component,
.xy-legend .file {
    min-inline-size: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.xy-legend .group > .entry .file {
    font-family: var(--font-mono);
}

.xy-legend .files .file {
    font-family: var(--font-mono);
}

.xy-legend .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}
</style>
