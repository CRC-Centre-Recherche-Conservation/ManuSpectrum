<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import Button from "primevue/button";
import InputNumber from "primevue/inputnumber";
import InputText from "primevue/inputtext";
// PrimeVue's Select is imported under a name that is not an HTML element.
// `vue-gettext-extract` parses this template with parse5, which lowercases the
// tag to `select` and ignores the XML self-closing slash; the parser then
// enters its "in select" insertion mode and drops every following start tag —
// with all its translatable strings — until the next one.
import PrimeSelect from "primevue/select";

import {
    DEFAULT_DISTINCT_LIMIT,
    MAX_DISTINCT_LIMIT,
    MAX_HOPS,
    MAX_RELATED,
    blankHop,
    involvedGraphs,
    knownAliases,
} from "@/manuspectrum/functions/summary-config-api.ts";

import type {
    HopDirection,
    LabeledChoice,
    RelatableNodes,
    SummaryAggregate,
    SummaryHop,
} from "@/manuspectrum/functions/types.ts";

const UPDATE_KEY_EVENT = "update:rollup-key" as const;
const UPDATE_LABEL_EN_EVENT = "update:label-en" as const;
const UPDATE_LABEL_FR_EVENT = "update:label-fr" as const;
const UPDATE_PATH_EVENT = "update:path" as const;
const UPDATE_AGGREGATE_EVENT = "update:aggregate" as const;
const UPDATE_MAX_RELATED_EVENT = "update:max-related" as const;
const REMOVE_EVENT = "remove" as const;

const { path, aggregate, relations } = defineProps<{
    rollupKey: string;
    labelEn: string;
    labelFr: string;
    path: SummaryHop[];
    aggregate: SummaryAggregate[];
    maxRelated: number;
    relations: RelatableNodes | null;
}>();

const emit = defineEmits<{
    (event: typeof UPDATE_KEY_EVENT, value: string): void;
    (event: typeof UPDATE_LABEL_EN_EVENT, value: string): void;
    (event: typeof UPDATE_LABEL_FR_EVENT, value: string): void;
    (event: typeof UPDATE_PATH_EVENT, value: SummaryHop[]): void;
    (event: typeof UPDATE_AGGREGATE_EVENT, value: SummaryAggregate[]): void;
    (event: typeof UPDATE_MAX_RELATED_EVENT, value: number): void;
    (event: typeof REMOVE_EVENT): void;
}>();

const { $gettext } = useGettext();

const graphChoices = computed(() => involvedGraphs(relations));

const directionChoices = computed<LabeledChoice<HopDirection>[]>(() => [
    {
        value: "incoming",
        label: $gettext("Incoming — that model carries the link"),
    },
    {
        value: "outgoing",
        label: $gettext("Outgoing — this model carries the link"),
    },
]);

// The endpoint reports the relations that touch the model being configured, so
// a second hop leaves its own model's relations unlisted. The alias box stays
// editable for that reason: the suggestions help, they do not constrain.
const aliasSuggestions = computed(() =>
    path.map((hop) => knownAliases(relations, hop.graph_slug)),
);

const canAddHop = computed(() => path.length < MAX_HOPS);

const canRemoveHop = computed(() => path.length > 1);

const distinctAggregate = computed(() =>
    aggregate.find((entry) => entry.op === "distinct"),
);

// A distinct aggregate counts the values of an alias of the LAST model of the
// path — the one whose resources are being counted.
const distinctAliasChoices = computed(() => {
    const lastHop = path[path.length - 1];
    const aggregatable = relations?.aggregatable ?? {};
    return (aggregatable[lastHop?.graph_slug] ?? []).map(
        (entry) => entry.alias,
    );
});

function updateHop(index: number, patch: Partial<SummaryHop>): void {
    emit(
        UPDATE_PATH_EVENT,
        path.map((hop, position) =>
            position === index ? { ...hop, ...patch } : hop,
        ),
    );
}

function addHop(): void {
    emit(UPDATE_PATH_EVENT, [...path, blankHop(relations)]);
}

function removeHop(index: number): void {
    emit(
        UPDATE_PATH_EVENT,
        path.filter((_hop, position) => position !== index),
    );
}

function toggleDistinct(): void {
    const withoutDistinct = aggregate.filter(
        (entry) => entry.op !== "distinct",
    );
    if (distinctAggregate.value) {
        emit(UPDATE_AGGREGATE_EVENT, withoutDistinct);
        return;
    }
    emit(UPDATE_AGGREGATE_EVENT, [
        ...withoutDistinct,
        {
            op: "distinct",
            alias: distinctAliasChoices.value[0] ?? "",
            style: "chip",
            limit: DEFAULT_DISTINCT_LIMIT,
        },
    ]);
}

function patchDistinct(patch: Partial<SummaryAggregate>): void {
    emit(
        UPDATE_AGGREGATE_EVENT,
        aggregate.map((entry) =>
            entry.op === "distinct" ? { ...entry, ...patch } : entry,
        ),
    );
}
</script>

<template>
    <fieldset class="rollup-editor">
        <legend>{{ $gettext("Related count") }}</legend>
        <div class="identity">
            <InputText
                class="rollup-key"
                data-testid="rollup-key"
                :model-value="rollupKey"
                :aria-label="$gettext('Key of this related count')"
                :placeholder="$gettext('Key, e.g. analyses')"
                @update:model-value="emit(UPDATE_KEY_EVENT, $event ?? '')"
            />
            <InputText
                class="label-en"
                data-testid="rollup-label-en"
                :model-value="labelEn"
                :aria-label="$gettext('English label of this related count')"
                :placeholder="$gettext('Label (EN)')"
                @update:model-value="emit(UPDATE_LABEL_EN_EVENT, $event ?? '')"
            />
            <InputText
                class="label-fr"
                data-testid="rollup-label-fr"
                :model-value="labelFr"
                :aria-label="$gettext('French label of this related count')"
                :placeholder="$gettext('Label (FR)')"
                @update:model-value="emit(UPDATE_LABEL_FR_EVENT, $event ?? '')"
            />
            <Button
                class="remove"
                data-testid="remove-rollup"
                icon="fa fa-trash"
                severity="danger"
                :aria-label="$gettext('Remove this related count')"
                @click="emit(REMOVE_EVENT)"
            />
        </div>

        <div
            v-for="(hop, index) in path"
            :key="index"
            class="hop-row"
        >
            <PrimeSelect
                class="hop-graph"
                data-testid="hop-graph"
                option-label="name"
                option-value="slug"
                :options="graphChoices"
                :model-value="hop.graph_slug"
                :aria-label="$gettext('Model carrying the relation')"
                :placeholder="$gettext('Model')"
                @update:model-value="updateHop(index, { graph_slug: $event })"
            />
            <PrimeSelect
                class="hop-alias"
                data-testid="hop-alias"
                :editable="true"
                :options="aliasSuggestions[index]"
                :model-value="hop.alias"
                :aria-label="
                    $gettext('Alias of the node carrying the relation')
                "
                :placeholder="$gettext('Relation alias')"
                @update:model-value="updateHop(index, { alias: $event ?? '' })"
            />
            <PrimeSelect
                class="hop-direction"
                data-testid="hop-direction"
                option-label="label"
                option-value="value"
                :options="directionChoices"
                :model-value="hop.direction"
                :aria-label="$gettext('Direction of the relation')"
                @update:model-value="updateHop(index, { direction: $event })"
            />
            <Button
                v-if="canRemoveHop"
                class="remove-hop"
                data-testid="remove-hop"
                icon="fa fa-times"
                severity="secondary"
                :aria-label="$gettext('Remove this hop')"
                @click="removeHop(index)"
            />
        </div>

        <div class="controls">
            <Button
                class="add-hop"
                data-testid="add-hop"
                icon="fa fa-plus"
                severity="secondary"
                :label="$gettext('Add a hop')"
                :disabled="!canAddHop"
                @click="addHop"
            />
            <Button
                class="toggle-distinct"
                data-testid="toggle-distinct"
                severity="secondary"
                :label="
                    distinctAggregate
                        ? $gettext('Stop listing distinct values')
                        : $gettext('List distinct values')
                "
                @click="toggleDistinct"
            />
            <InputNumber
                class="max-related"
                data-testid="rollup-max-related"
                :model-value="maxRelated"
                :min="1"
                :max="MAX_RELATED"
                :aria-label="
                    $gettext('Maximum number of intermediate resources')
                "
                @update:model-value="
                    emit(UPDATE_MAX_RELATED_EVENT, $event ?? MAX_RELATED)
                "
            />
        </div>

        <div
            v-if="distinctAggregate"
            class="distinct-row"
        >
            <PrimeSelect
                class="distinct-alias"
                data-testid="distinct-alias"
                :editable="true"
                :options="distinctAliasChoices"
                :model-value="distinctAggregate.alias"
                :aria-label="$gettext('Alias whose distinct values are listed')"
                :placeholder="$gettext('Alias to list')"
                @update:model-value="patchDistinct({ alias: $event ?? '' })"
            />
            <InputNumber
                class="distinct-limit"
                data-testid="distinct-limit"
                :model-value="distinctAggregate.limit ?? DEFAULT_DISTINCT_LIMIT"
                :min="1"
                :max="MAX_DISTINCT_LIMIT"
                :aria-label="$gettext('How many distinct values to show')"
                @update:model-value="
                    patchDistinct({ limit: $event ?? DEFAULT_DISTINCT_LIMIT })
                "
            />
        </div>
    </fieldset>
</template>

<style scoped>
.rollup-editor {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    padding: 0.75rem;
    margin-block-end: 0.75rem;
    border: 0.0625rem solid var(--p-content-border-color);
    border-radius: 0.25rem;
}

.rollup-editor legend {
    font-size: 1.2rem;
    font-weight: 600;
    inline-size: auto;
    border: none;
    margin: 0;
}

.rollup-editor .identity,
.rollup-editor .hop-row,
.rollup-editor .controls,
.rollup-editor .distinct-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
}

.rollup-editor .hop-graph,
.rollup-editor .hop-alias,
.rollup-editor .hop-direction,
.rollup-editor .distinct-alias {
    min-inline-size: 11rem;
}

.rollup-editor .max-related,
.rollup-editor .distinct-limit {
    inline-size: 6rem;
}
</style>
