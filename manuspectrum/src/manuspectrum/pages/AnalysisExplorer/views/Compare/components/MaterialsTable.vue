<script setup lang="ts">
import { useGettext } from "vue3-gettext";

import LinkedChip from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/LinkedChip.vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import {
    analysisNode,
    colourNode,
    elementNode,
    materialNode,
    materialValueNode,
    slotNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { ValueRef } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { MaterialRow } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

/**
 * The identified materials of the Selection, one row each, in slot order.
 * Each row is its record (`ch:`): its name is the record's toggle, and its
 * colours, materials, elements (those the synthesis gives a symbol) and
 * analyses cited are toggles of their own (`LinkedChip`). A row is marked
 * by how it stands to the linked selection and to the node previewed; a
 * mouse resting on it previews its record.
 */
const props = defineProps<{ rows: readonly MaterialRow[] }>();

const { $gettext, interpolate } = useGettext();
const marks = useLinkedMarks();

function labels(values: readonly ValueRef[]): string {
    return values.map((value) => value.label.value).join(", ");
}

function levelText(level: string): string {
    return interpolate($gettext("%{level}:"), { level }, true);
}

function recordOf(row: MaterialRow): string {
    return materialNode(row.characterization.id);
}

function symbolOf(value: ValueRef): string | null {
    return marks.linked?.graph.value.symbols.get(value.id) ?? null;
}
</script>

<template>
    <div class="materials-table">
        <table>
            <thead>
                <tr>
                    <th scope="col">
                        <span>{{ $gettext("Selection") }}</span>
                    </th>
                    <th scope="col">
                        <span>{{ $gettext("Identified material") }}</span>
                    </th>
                    <th scope="col">
                        <span>{{ $gettext("Colours") }}</span>
                    </th>
                    <th scope="col">
                        <span>{{ $gettext("Materials") }}</span>
                    </th>
                    <th scope="col">
                        <span>{{ $gettext("Layers") }}</span>
                    </th>
                    <th scope="col">
                        <span>{{ $gettext("Elements") }}</span>
                    </th>
                    <th scope="col">
                        <span>{{
                            $gettext("Analyses cited as evidence")
                        }}</span>
                    </th>
                </tr>
            </thead>
            <tbody>
                <tr
                    v-for="row in props.rows"
                    :key="row.key"
                    :data-key="row.key"
                    :data-rel="marks.rel(recordOf(row))"
                    :data-preview="marks.previewRel(recordOf(row))"
                    @pointerenter="marks.enter(recordOf(row), $event)"
                    @pointerleave="marks.leave($event)"
                >
                    <td class="slot">
                        <span :data-rel="marks.rel(slotNode(row.slot))">{{
                            slotLabel(row.slot)
                        }}</span>
                    </td>
                    <th
                        scope="row"
                        class="name"
                    >
                        <button
                            type="button"
                            class="record"
                            :aria-pressed="marks.pressed(recordOf(row))"
                            @click="marks.toggle(recordOf(row))"
                        >
                            <span :lang="row.characterization.name.lang">{{
                                row.characterization.name.value
                            }}</span>
                        </button>
                        <span
                            v-if="row.characterization.unpublished"
                            class="badge"
                        >
                            {{ $gettext("Draft") }}
                        </span>
                    </th>
                    <td>
                        <ul
                            v-if="row.characterization.colours.length > 0"
                            class="chips"
                        >
                            <li
                                v-for="colour in row.characterization.colours"
                                :key="colour.id"
                            >
                                <LinkedChip
                                    :node="colourNode(colour.id)"
                                    :text="colour.label.value"
                                    :lang="colour.label.lang"
                                />
                            </li>
                        </ul>
                        <template v-else>
                            <span
                                class="none"
                                aria-hidden="true"
                                >—</span
                            >
                            <span class="visually-hidden">{{
                                $gettext("Not stated")
                            }}</span>
                        </template>
                    </td>
                    <td>
                        <ul v-if="row.characterization.materials.length > 0">
                            <li
                                v-for="entry in row.characterization.materials"
                                :key="entry.value.uri"
                            >
                                <LinkedChip
                                    :node="materialValueNode(entry.value.id)"
                                    :text="entry.value.label.value"
                                    :lang="entry.value.label.lang"
                                />
                                <span
                                    v-if="entry.confidence"
                                    class="badge certainty"
                                    :lang="entry.confidence.label.lang"
                                >
                                    {{ entry.confidence.label.value }}
                                </span>
                            </li>
                        </ul>
                        <template v-else>
                            <span
                                class="none"
                                aria-hidden="true"
                                >—</span
                            >
                            <span class="visually-hidden">{{
                                $gettext("Not stated")
                            }}</span>
                        </template>
                    </td>
                    <td>
                        <span v-if="row.characterization.layers.length > 0">{{
                            labels(row.characterization.layers)
                        }}</span>
                        <template v-else>
                            <span
                                class="none"
                                aria-hidden="true"
                                >—</span
                            >
                            <span class="visually-hidden">{{
                                $gettext("Not stated")
                            }}</span>
                        </template>
                    </td>
                    <td>
                        <ul v-if="row.characterization.elements.length > 0">
                            <li
                                v-for="(group, index) in row.characterization
                                    .elements"
                                :key="group.level?.uri ?? `none-${index}`"
                                class="chips"
                            >
                                <span
                                    v-if="group.level"
                                    :lang="group.level.label.lang"
                                    >{{
                                        levelText(group.level.label.value)
                                    }}</span
                                >
                                <template
                                    v-for="value in group.values"
                                    :key="value.id"
                                >
                                    <LinkedChip
                                        v-if="symbolOf(value)"
                                        :node="elementNode(symbolOf(value)!)"
                                        :text="value.label.value"
                                        :lang="value.label.lang"
                                    />
                                    <span
                                        v-else
                                        class="plain"
                                        :lang="value.label.lang"
                                        >{{ value.label.value }}</span
                                    >
                                </template>
                            </li>
                        </ul>
                        <template v-else>
                            <span
                                class="none"
                                aria-hidden="true"
                                >—</span
                            >
                            <span class="visually-hidden">{{
                                $gettext("Not stated")
                            }}</span>
                        </template>
                    </td>
                    <td>
                        <ul
                            v-if="row.characterization.evidence.length > 0"
                            class="chips"
                        >
                            <li
                                v-for="entry in row.characterization.evidence"
                                :key="entry.id"
                            >
                                <LinkedChip
                                    :node="analysisNode(entry.id)"
                                    :text="entry.name.value"
                                    :lang="entry.name.lang"
                                />
                            </li>
                        </ul>
                        <template v-else>
                            <span
                                class="none"
                                aria-hidden="true"
                                >—</span
                            >
                            <span class="visually-hidden">{{
                                $gettext("Not stated")
                            }}</span>
                        </template>
                    </td>
                </tr>
            </tbody>
        </table>
    </div>
</template>

<style scoped>
.materials-table {
    overflow-x: auto;
}

.materials-table table {
    inline-size: 100%;
    border-collapse: collapse;
    font-size: 0.8125rem;
}

.materials-table th,
.materials-table td {
    padding: 0.375rem 0.5rem;
    border-block-end: 0.0625rem solid var(--border);
    text-align: start;
    vertical-align: top;
}

.materials-table thead th {
    color: var(--ink-muted);
    font-weight: 600;
    white-space: nowrap;
}

.materials-table .slot {
    font-family: var(--font-mono);
    font-weight: 600;
}

.materials-table .name {
    font-weight: 600;
}

.materials-table ul {
    display: grid;
    gap: 0.125rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.materials-table ul.chips,
.materials-table li.chips,
.materials-table td > ul > li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem;
}

.materials-table .record {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    font-weight: 600;
    text-align: start;
    cursor: pointer;
}

.materials-table .record[aria-pressed="true"] {
    border-color: var(--linked-mark, var(--blue-text));
    outline: 0.125rem solid var(--linked-mark, var(--blue-text));
    outline-offset: 0.0625rem;
}

.materials-table .record:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.materials-table tbody tr > :first-child {
    position: relative;
}

.materials-table tbody tr[data-rel="self"],
.materials-table tbody tr[data-rel="direct"],
.materials-table tbody tr[data-rel="evidence"] {
    background: var(--linked-tint, var(--bg-alt));
}

.materials-table tbody tr[data-rel="self"] > :first-child::before,
.materials-table tbody tr[data-rel="direct"] > :first-child::before,
.materials-table tbody tr[data-rel="evidence"] > :first-child::before {
    position: absolute;
    inset-block: 0;
    inset-inline-start: 0;
    border-inline-start: var(--linked-bar, 0.1875rem) solid
        var(--linked-mark, var(--blue-text));
    content: "";
}

.materials-table tbody tr[data-rel="evidence"] > :first-child::before {
    border-inline-start-style: dashed;
}

.materials-table tbody tr[data-rel="none"] {
    color: var(--ink-muted);
}

.materials-table tbody tr[data-preview] {
    outline: 0.125rem dashed var(--linked-mark, var(--blue-text));
    outline-offset: -0.125rem;
}

.materials-table .plain {
    font-size: 0.75rem;
}

.materials-table .badge {
    padding: 0 0.375rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    font-size: 0.75rem;
    font-weight: 400;
}

.materials-table .certainty {
    background: var(--bg-alt);
    color: var(--ink);
}

.materials-table .none {
    color: var(--ink-muted);
}

.materials-table .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}
</style>
