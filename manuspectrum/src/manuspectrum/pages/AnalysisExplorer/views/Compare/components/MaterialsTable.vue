<script setup lang="ts">
import { useGettext } from "vue3-gettext";

import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";

import type {
    CharacterizationSummary,
    ValueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { MaterialRow } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

type Elements = CharacterizationSummary["elements"][number];

/** The identified materials of the Selection, one row each, in slot order. */
const props = defineProps<{ rows: readonly MaterialRow[] }>();

const { $gettext, interpolate } = useGettext();

function labels(values: readonly ValueRef[]): string {
    return values.map((value) => value.label.value).join(", ");
}

function elementsText(group: Elements): string {
    return group.level
        ? interpolate(
              $gettext("%{level}: %{elements}"),
              {
                  level: group.level.label.value,
                  elements: labels(group.values),
              },
              true,
          )
        : labels(group.values);
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
                >
                    <td class="slot">
                        <span>{{ slotLabel(row.slot) }}</span>
                    </td>
                    <th
                        scope="row"
                        class="name"
                    >
                        <span :lang="row.characterization.name.lang">{{
                            row.characterization.name.value
                        }}</span>
                        <span
                            v-if="row.characterization.unpublished"
                            class="badge"
                        >
                            {{ $gettext("Draft") }}
                        </span>
                    </th>
                    <td>
                        <span v-if="row.characterization.colours.length > 0">{{
                            labels(row.characterization.colours)
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
                        <ul v-if="row.characterization.materials.length > 0">
                            <li
                                v-for="entry in row.characterization.materials"
                                :key="entry.value.uri"
                            >
                                <span :lang="entry.value.label.lang">{{
                                    entry.value.label.value
                                }}</span>
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
                            >
                                <span>{{ elementsText(group) }}</span>
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
                        <ul v-if="row.characterization.evidence.length > 0">
                            <li
                                v-for="entry in row.characterization.evidence"
                                :key="entry.id"
                                :lang="entry.name.lang"
                            >
                                <span>{{ entry.name.value }}</span>
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
