<script setup lang="ts">
import { nextTick, useId, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";
import FocusPip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusPip.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import {
    curveColourVar,
    dashArray,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";

import type { IconName } from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";
import type { LinkedMark } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type {
    CurveLook,
    LegendGroup,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";

const TOGGLE_EVENT = "toggle" as const;
const PREVIEW_EVENT = "preview" as const;
const TOGGLE_EYE_EVENT = "toggle-eye" as const;
const SHOW_ALL_EVENT = "show-all" as const;

export interface LegendToggleEvent {
    node: NodeId;
}

export interface LegendPreviewEvent {
    node: NodeId | null;
    pointerType: string;
    /** The entry under the pointer, which the trail of the focus follows. */
    anchor: Element | null;
}

export interface LegendEyeEvent {
    /** The `LegendEntry.id` of the curve the eye toggles. */
    id: string;
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
 * pen resting on an entry previews it. A swatch (`strokeOf`, `group.look`/
 * `entry.look`) always matches the chart's current line exactly: its own
 * per-window hue (`CurveLook`), never recoloured by the focus.
 *
 * A row that draws exactly one curve (a slot with a single file, or a file
 * row under a slot with several) carries a sibling eye button before its
 * focus toggle — two buttons, never one nested in the other. The eye shows
 * or hides that curve regardless of the focus (`hiddenIds`, emits
 * `toggle-eye`); a hidden entry dims and its swatch turns hollow but keeps
 * its focus marks. `show-all` fires from the header's « Show all spectra »,
 * shown only while `hiddenIds` holds something.
 */
const props = defineProps<{
    groups: readonly LegendGroup[];
    hiddenIds: ReadonlySet<string>;
}>();

const emit = defineEmits<{
    (event: typeof TOGGLE_EVENT, payload: LegendToggleEvent): void;
    (event: typeof PREVIEW_EVENT, payload: LegendPreviewEvent): void;
    (event: typeof TOGGLE_EYE_EVENT, payload: LegendEyeEvent): void;
    (event: typeof SHOW_ALL_EVENT): void;
}>();

const { $gettext, interpolate } = useGettext();
const marks = useLinkedMarks();
const hintId = useId();
const root = useTemplateRef<HTMLElement>("root");

function isHidden(id: string): boolean {
    return props.hiddenIds.has(id);
}

function eyeIcon(id: string): IconName {
    return isHidden(id) ? "eye-slash" : "eye";
}

/** « Hide A1 · S1.csv »: the curve named as its entry already shows it; `aria-pressed` says whether it is hidden. */
function eyeLabel(label: string, name: string): string {
    return interpolate(
        $gettext("Hide %{name}"),
        { name: `${label} · ${name}` },
        true,
    );
}

function toggleEye(id: string): void {
    emit(TOGGLE_EYE_EVENT, { id });
}

/** « Show all spectra » unmounts itself: the focus moves to the first eye button. */
async function showAll(): Promise<void> {
    emit(SHOW_ALL_EVENT);
    await nextTick();
    root.value?.querySelector<HTMLElement>('[data-action="eye"]')?.focus();
}

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

/** The swatch of a line: its current colour and dash, exactly as the chart draws it. */
function strokeOf(look: CurveLook): Record<string, string> {
    return {
        stroke: curveColourVar(look),
        strokeDasharray: dashArray(look.dash),
    };
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
    <div
        ref="root"
        class="xy-legend"
    >
        <div
            v-if="props.hiddenIds.size > 0"
            class="header"
        >
            <button
                type="button"
                class="show-all"
                @click="showAll"
            >
                {{ $gettext("Show all spectra") }}
            </button>
        </div>
        <ul
            class="groups"
            :aria-label="$gettext('Curves, by slot')"
        >
            <li
                v-for="group in props.groups"
                :key="group.slot"
                class="group"
            >
                <div class="row">
                    <IconButton
                        v-if="group.entries.length === 1"
                        data-action="eye"
                        :data-curve="group.entries[0].id"
                        :icon="eyeIcon(group.entries[0].id)"
                        :label="eyeLabel(group.label, group.entries[0].name)"
                        :pressed="isHidden(group.entries[0].id)"
                        tip-placement="below"
                        tip-align="start"
                        @click="toggleEye(group.entries[0].id)"
                    />
                    <button
                        type="button"
                        class="entry ms-focus"
                        :class="{
                            unrelated: unrelated(group.nodes),
                            'eye-hidden':
                                group.entries.length === 1 &&
                                isHidden(group.entries[0].id),
                        }"
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
                                :style="strokeOf(group.look)"
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
                </div>
                <ul
                    v-if="group.entries.length > 1"
                    class="files"
                >
                    <li
                        v-for="entry in group.entries"
                        :key="entry.id"
                    >
                        <div class="row">
                            <IconButton
                                data-action="eye"
                                :data-curve="entry.id"
                                :icon="eyeIcon(entry.id)"
                                :label="eyeLabel(group.label, entry.name)"
                                :pressed="isHidden(entry.id)"
                                tip-placement="below"
                                tip-align="start"
                                @click="toggleEye(entry.id)"
                            />
                            <button
                                type="button"
                                class="entry ms-focus"
                                :class="{
                                    unrelated: unrelated(entry.nodes),
                                    'eye-hidden': isHidden(entry.id),
                                }"
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
                                        :style="strokeOf(entry.look)"
                                    />
                                </svg>
                                <span
                                    class="file"
                                    :title="entry.name"
                                    >{{ entry.name }}</span
                                >
                            </button>
                        </div>
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
    padding-block-start: var(--focus-room);
    font-size: 0.8125rem;
}

.xy-legend .groups,
.xy-legend .group,
.xy-legend .files {
    display: grid;
    gap: var(--focus-room);
    list-style: none;
}

.xy-legend .files {
    padding-inline-start: 1rem;
}

.xy-legend .header {
    display: flex;
    justify-content: flex-end;
}

.xy-legend .show-all {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: 0.0625rem solid transparent;
    border-radius: 0.375rem;
    background: transparent;
    color: var(--blue-text);
    font: inherit;
    font-size: 0.75rem;
    cursor: pointer;
}

.xy-legend .show-all:hover {
    background: var(--bg-alt);
}

.xy-legend .show-all:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.0625rem;
}

.xy-legend .row {
    display: flex;
    align-items: center;
    gap: 0.125rem;
}

.xy-legend .row > :first-child {
    flex: none;
}

.xy-legend .row > .entry {
    flex: 1 1 auto;
    min-inline-size: 0;
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

.xy-legend .group > .row > .entry .swatch {
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

.xy-legend .group > .row > .entry .file {
    font-family: var(--font-mono);
}

.xy-legend .files .file {
    font-family: var(--font-mono);
}

.xy-legend .entry.eye-hidden {
    color: var(--ink-muted);
}

.xy-legend .entry.eye-hidden .swatch {
    opacity: 0.35;
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
