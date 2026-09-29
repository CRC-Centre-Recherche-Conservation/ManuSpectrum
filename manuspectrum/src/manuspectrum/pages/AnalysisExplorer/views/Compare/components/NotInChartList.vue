<script setup lang="ts">
import { inject, nextTick, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import FocusPip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusPip.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { safeHref } from "@/manuspectrum/pages/AnalysisExplorer/format.ts";
import { SCREEN_FOCUS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisNode,
    slotNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { AnalysisHit } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type {
    NotInChartEntry,
    NotInChartReason,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

/**
 * The Selection items no Compare window draws, each with the reason and what
 * the reader can do: download a file, open the analysis in its document, or
 * take an item no longer available out of the Selection. Once an item is
 * taken out, the focus goes to the action of the next item, else of the one
 * before; after the last one, to the Compare heading. An item holding an
 * analysis stands for it (`an:`): its title is the analysis's toggle,
 * carrying the focus marks, and the line is tinted by how the analysis
 * stands to the focus (a bar of its slots' hues) and to the node a mouse
 * previews.
 */
const props = defineProps<{ entries: readonly NotInChartEntry[] }>();

const store = useExplorerStore();
const { $gettext, interpolate } = useGettext();
const list = useTemplateRef<HTMLUListElement>("list");
const screenFocus = inject(SCREEN_FOCUS_KEY, null);
const marks = useLinkedMarks();

function recordOf(entry: NotInChartEntry): string[] {
    return entry.analysis ? [analysisNode(entry.analysis.id)] : [];
}

function preview(entry: NotInChartEntry, event: PointerEvent): void {
    if (entry.analysis) marks.enter(analysisNode(entry.analysis.id), event);
}

function reasonText(reason: NotInChartReason): string {
    switch (reason) {
        case "raw-file":
            return $gettext("Instrument file: download only.");
        case "file":
            return $gettext("File with no viewer: download only.");
        case "no-data":
            return $gettext("No data to display.");
        case "missing":
            return $gettext("No longer available.");
    }
}

function titleOf(entry: NotInChartEntry): string {
    const parts = [entry.analysis?.name.value, entry.file?.name].filter(
        (part): part is string => Boolean(part),
    );
    return parts.join(" · ");
}

function downloadOf(entry: NotInChartEntry): string | null {
    return entry.reason === "raw-file" || entry.reason === "file"
        ? safeHref(entry.file?.downloadUrl)
        : null;
}

function downloadLabel(entry: NotInChartEntry): string {
    return interpolate(
        $gettext("Download %{name}"),
        { name: entry.file?.name ?? "" },
        true,
    );
}

function openLabel(analysis: AnalysisHit): string {
    return interpolate(
        $gettext("Open the analysis %{name}"),
        { name: analysis.name.value },
        true,
    );
}

function opensAnalysis(entry: NotInChartEntry): boolean {
    return entry.analysis !== null && entry.reason === "no-data";
}

async function remove(key: string): Promise<void> {
    const index = props.entries.findIndex((entry) => entry.key === key);
    const neighbour =
        props.entries[index + 1]?.key ?? props.entries[index - 1]?.key ?? null;
    if (neighbour === null && screenFocus) screenFocus.value = true;
    store.removeFromBasket(key);
    await nextTick();
    if (neighbour === null) return;
    for (const row of list.value?.children ?? []) {
        if (row instanceof HTMLElement && row.dataset.key === neighbour) {
            row.querySelector<HTMLElement>(".action")?.focus();
        }
    }
}

function openAnalysis(analysis: AnalysisHit): void {
    store.openDocument(analysis.document.id, analysis.canvas);
    store.focusOn({ kind: "analysis", id: analysis.id });
}
</script>

<template>
    <ul
        ref="list"
        class="not-in-chart-list"
    >
        <li
            v-for="entry in props.entries"
            :key="entry.key"
            :data-key="entry.key"
            :data-rel="marks.rel(recordOf(entry))"
            :data-preview="marks.previewRel(recordOf(entry))"
            :style="marks.rowStyle(recordOf(entry))"
            @pointerenter="preview(entry, $event)"
            @pointerleave="marks.leave($event)"
        >
            <span
                class="slot"
                :data-rel="marks.rel(slotNode(entry.slot))"
                >{{ slotLabel(entry.slot) }}</span
            >
            <span class="info">
                <button
                    v-if="entry.analysis"
                    type="button"
                    class="title record ms-focus"
                    v-bind="marks.focus(analysisNode(entry.analysis.id))"
                    :lang="entry.analysis.name.lang"
                    :aria-pressed="
                        marks.pressed(analysisNode(entry.analysis.id))
                    "
                    @click="marks.toggle(analysisNode(entry.analysis.id))"
                >
                    <FocusPip :node="analysisNode(entry.analysis.id)" />
                    <span>{{ titleOf(entry) }}</span>
                </button>
                <span
                    v-else-if="titleOf(entry)"
                    class="title"
                    >{{ titleOf(entry) }}</span
                >
                <span class="reason">{{ reasonText(entry.reason) }}</span>
            </span>
            <a
                v-if="downloadOf(entry)"
                class="action"
                download=""
                :href="downloadOf(entry)!"
                :aria-label="downloadLabel(entry)"
            >
                <span>{{ $gettext("Download") }}</span>
            </a>
            <button
                v-else-if="opensAnalysis(entry)"
                type="button"
                class="action"
                :aria-label="openLabel(entry.analysis!)"
                @click="openAnalysis(entry.analysis!)"
            >
                <span>{{ $gettext("Open the analysis") }}</span>
            </button>
            <button
                v-else-if="entry.reason === 'missing'"
                type="button"
                class="action"
                @click="remove(entry.key)"
            >
                <span>{{ $gettext("Remove from the Selection") }}</span>
            </button>
        </li>
    </ul>
</template>

<style scoped>
.not-in-chart-list {
    display: grid;
    gap: 0.5rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.not-in-chart-list li {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 0 0.5rem;
}

.not-in-chart-list .slot {
    font-family: var(--font-mono);
    font-weight: 600;
}

.not-in-chart-list .info {
    display: grid;
    min-inline-size: 0;
}

.not-in-chart-list .title {
    overflow-wrap: anywhere;
}

.not-in-chart-list .record {
    --r: 0.375rem;
    --link-pip: 0.8125rem;
    justify-self: start;
    min-block-size: 1.5rem;
    padding: 0 0.25rem;
    border: 0.0625rem solid transparent;
    border-radius: 0.375rem;
    background: none;
    color: inherit;
    font: inherit;
    text-align: start;
    cursor: pointer;
}

.not-in-chart-list .record:hover {
    border-color: var(--border-hover);
}

.not-in-chart-list li {
    position: relative;
    padding-block: 0.25rem;
    padding-inline-start: 0.5rem;
    border-radius: 0.375rem;
    transition:
        background-color var(--dur-med, 260ms),
        color var(--dur-med, 260ms);
}

.not-in-chart-list li::before {
    position: absolute;
    inset-block: 0;
    inset-inline-start: 0;
    inline-size: 0;
    background: var(--bar, var(--focus-1));
    content: "";
    transition: inline-size var(--dur-med, 260ms) var(--ease-out-expo);
}

.not-in-chart-list
    li:is([data-rel="self"], [data-rel="direct"], [data-rel="evidence"]) {
    background: color-mix(
        in srgb,
        var(--h1, var(--focus-1)) 6%,
        var(--surface)
    );
}

.not-in-chart-list li[data-rel="self"]::before {
    inline-size: 0.25rem;
}

.not-in-chart-list li[data-rel="direct"]::before {
    inline-size: 0.1875rem;
}

.not-in-chart-list li[data-rel="evidence"]::before {
    inline-size: 0.0625rem;
}

.not-in-chart-list li[data-rel="none"] {
    color: var(--ink-muted);
}

.not-in-chart-list li[data-preview] {
    background: color-mix(
        in srgb,
        var(--hp, var(--focus-1)) 5%,
        var(--surface)
    );
}

.not-in-chart-list .reason {
    color: var(--ink-muted);
    font-size: 0.75rem;
}

.not-in-chart-list .action {
    display: inline-flex;
    align-items: center;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-size: 0.8125rem;
    text-decoration: none;
    cursor: pointer;
}

.not-in-chart-list .action:focus-visible,
.not-in-chart-list .record:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.1875rem;
}
</style>
