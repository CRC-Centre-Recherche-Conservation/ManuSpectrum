<script setup lang="ts">
import { useId } from "vue";
import { useGettext } from "vue3-gettext";

import {
    dashArray,
    isColoured,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";

import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type { RelationLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";
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
}

/**
 * The legend of an XY window, the only one on screen: one entry per slot,
 * its files under it when it holds several, each a toggle of its node in
 * the linked selection (`aria-pressed` while selected). While something is
 * selected, an entry it links carries its level in `data-rel` and a bar;
 * an entry it does not link stays listed, its swatch faded, with a « + »
 * and a description saying a press adds it. A mouse or pen resting on an
 * entry previews it.
 */
const props = defineProps<{
    groups: readonly LegendGroup[];
    selecting: boolean;
}>();

const emit = defineEmits<{
    (event: typeof TOGGLE_EVENT, payload: LegendToggleEvent): void;
    (event: typeof PREVIEW_EVENT, payload: LegendPreviewEvent): void;
}>();

const { $gettext } = useGettext();
const hintId = useId();

function unrelated(relation: RelationLevel | null): boolean {
    return props.selecting && relation === null;
}

function relationOf(relation: RelationLevel | null): string | undefined {
    if (!props.selecting) return undefined;
    return relation ?? "none";
}

/** The swatch of a line: its slot colour, a grey context slot in ink while the selection links it, as the chart draws it. */
function strokeOf(
    slot: number,
    dash: Dash,
    relation: RelationLevel | null,
): Record<string, string> {
    let stroke = "var(--series-context)";
    if (isColoured(slot)) stroke = `var(--series-${slot + 1})`;
    else if (props.selecting && relation !== null) stroke = "var(--ink)";
    return { stroke, strokeDasharray: dashArray(dash) };
}

function toggle(node: NodeId): void {
    emit(TOGGLE_EVENT, { node });
}

function enter(node: NodeId, event: PointerEvent): void {
    emit(PREVIEW_EVENT, { node, pointerType: event.pointerType });
}

function leave(event: PointerEvent): void {
    emit(PREVIEW_EVENT, { node: null, pointerType: event.pointerType });
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
                    class="entry"
                    :class="{ unrelated: unrelated(group.relation) }"
                    :data-node="group.node"
                    :data-rel="relationOf(group.relation)"
                    :aria-pressed="group.pressed ? 'true' : 'false'"
                    :aria-describedby="
                        unrelated(group.relation) ? hintId : undefined
                    "
                    @click="toggle(group.node)"
                    @pointerenter="enter(group.node, $event)"
                    @pointerleave="leave"
                >
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
                                strokeOf(group.slot, 'solid', group.relation)
                            "
                        />
                    </svg>
                    <span class="slot">{{ group.label }}</span>
                    <span
                        class="name"
                        :lang="group.analysis.lang"
                        :title="group.analysis.value"
                        >{{ group.analysis.value }}</span
                    >
                    <span
                        v-if="group.entries.length === 1"
                        class="file"
                        :title="group.entries[0].name"
                        >{{ group.entries[0].name }}</span
                    >
                    <span
                        v-if="unrelated(group.relation)"
                        class="add"
                        aria-hidden="true"
                        >+</span
                    >
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
                            class="entry"
                            :class="{ unrelated: unrelated(entry.relation) }"
                            :data-node="entry.node"
                            :data-rel="relationOf(entry.relation)"
                            :aria-pressed="entry.pressed ? 'true' : 'false'"
                            :aria-describedby="
                                unrelated(entry.relation) ? hintId : undefined
                            "
                            @click="toggle(entry.node)"
                            @pointerenter="enter(entry.node, $event)"
                            @pointerleave="leave"
                        >
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
                                            entry.relation,
                                        )
                                    "
                                />
                            </svg>
                            <span
                                class="file"
                                :title="entry.name"
                                >{{ entry.name }}</span
                            >
                            <span
                                v-if="unrelated(entry.relation)"
                                class="add"
                                aria-hidden="true"
                                >+</span
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
    display: grid;
    grid-template-columns: 1.5rem auto minmax(0, 1fr) auto;
    align-items: baseline;
    gap: 0 0.375rem;
    inline-size: 100%;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-block: 0.25rem;
    padding-inline: 0.375rem;
    border: 0.0625rem solid transparent;
    border-inline-start: 0.1875rem solid transparent;
    border-radius: 0.25rem;
    background: transparent;
    color: var(--ink);
    font: inherit;
    text-align: start;
    cursor: pointer;
}

.xy-legend .files .entry {
    grid-template-columns: 1.5rem minmax(0, 1fr) auto;
}

.xy-legend .entry:hover {
    background: var(--bg-alt);
}

.xy-legend .entry:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.0625rem;
}

.xy-legend .entry[aria-pressed="true"] {
    border-color: var(--ink);
    font-weight: 600;
}

.xy-legend .entry[data-rel="self"],
.xy-legend .entry[data-rel="direct"],
.xy-legend .entry[data-rel="evidence"] {
    border-inline-start-color: var(--blue-text);
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

.xy-legend .slot {
    font-family: var(--font-mono);
}

.xy-legend .name,
.xy-legend .file {
    min-inline-size: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.xy-legend .group > .entry .file {
    grid-column: 3;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.75rem;
}

.xy-legend .files .file {
    font-family: var(--font-mono);
}

.xy-legend .add {
    grid-row: 1;
    grid-column: -2;
    font-family: var(--font-mono);
    font-weight: 600;
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
