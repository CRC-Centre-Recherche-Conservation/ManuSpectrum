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

import { MAX_VALUES } from "@/manuspectrum/functions/summary-config-api.ts";

import type {
    FieldStyle,
    LabeledChoice,
    RelatableField,
} from "@/manuspectrum/functions/types.ts";

const UPDATE_ALIAS_EVENT = "update:alias" as const;
const UPDATE_STYLE_EVENT = "update:style" as const;
const UPDATE_LABEL_EN_EVENT = "update:label-en" as const;
const UPDATE_LABEL_FR_EVENT = "update:label-fr" as const;
const UPDATE_MAX_VALUES_EVENT = "update:max-values" as const;
const REMOVE_EVENT = "remove" as const;
const MOVE_UP_EVENT = "move-up" as const;
const MOVE_DOWN_EVENT = "move-down" as const;

const props = defineProps<{
    alias: string;
    style: FieldStyle;
    labelEn: string;
    labelFr: string;
    maxValues: number | null;
    aliasOptions: RelatableField[];
    canMoveUp: boolean;
    canMoveDown: boolean;
}>();

const emit = defineEmits<{
    (event: typeof UPDATE_ALIAS_EVENT, alias: string): void;
    (event: typeof UPDATE_STYLE_EVENT, style: FieldStyle): void;
    (event: typeof UPDATE_LABEL_EN_EVENT, label: string): void;
    (event: typeof UPDATE_LABEL_FR_EVENT, label: string): void;
    (event: typeof UPDATE_MAX_VALUES_EVENT, maxValues: number | null): void;
    (event: typeof REMOVE_EVENT): void;
    (event: typeof MOVE_UP_EVENT): void;
    (event: typeof MOVE_DOWN_EVENT): void;
}>();

const { $gettext } = useGettext();

const styleChoices = computed<LabeledChoice<FieldStyle>[]>(() => [
    { value: "text", label: $gettext("Text") },
    { value: "date", label: $gettext("Date") },
    { value: "chip", label: $gettext("Chips") },
    { value: "number", label: $gettext("Number") },
    { value: "link", label: $gettext("Link to the report") },
    { value: "image", label: $gettext("Spectrum thumbnail") },
]);

const aliasIsKnown = computed((): boolean =>
    props.aliasOptions.some((option) => option.alias === props.alias),
);

// A renamed node leaves its old alias behind in the configuration. Keeping it
// in the list is what lets the editor see, and replace, what is stored.
const aliasChoices = computed((): LabeledChoice<string>[] => {
    const choices = props.aliasOptions.map((option) => ({
        value: option.alias,
        label: `${option.label} (${option.alias})`,
    }));
    if (!aliasIsKnown.value) {
        choices.unshift({ value: props.alias, label: props.alias });
    }
    return choices;
});

function onAliasChange(alias: string): void {
    emit(UPDATE_ALIAS_EVENT, alias);
}

function onStyleChange(style: FieldStyle): void {
    emit(UPDATE_STYLE_EVENT, style);
}

function onMaxValuesChange(maxValues: number | null): void {
    emit(UPDATE_MAX_VALUES_EVENT, maxValues);
}
</script>

<template>
    <div class="field-row">
        <div class="cell alias">
            <PrimeSelect
                data-testid="field-alias"
                option-label="label"
                option-value="value"
                :aria-label="$gettext('Field')"
                :invalid="!aliasIsKnown"
                :model-value="alias"
                :options="aliasChoices"
                @update:model-value="onAliasChange"
            />
            <small
                v-if="!aliasIsKnown"
                class="unknown-alias"
            >
                {{ $gettext("This node no longer exists in the model.") }}
            </small>
        </div>
        <div class="cell">
            <PrimeSelect
                data-testid="field-style"
                option-label="label"
                option-value="value"
                :aria-label="$gettext('Display style')"
                :model-value="style"
                :options="styleChoices"
                @update:model-value="onStyleChange"
            />
        </div>
        <div class="cell">
            <InputText
                data-testid="field-label-en"
                :aria-label="$gettext('English label override')"
                :model-value="labelEn"
                :placeholder="$gettext('English label')"
                @update:model-value="emit(UPDATE_LABEL_EN_EVENT, $event ?? '')"
            />
        </div>
        <div class="cell">
            <InputText
                data-testid="field-label-fr"
                :aria-label="$gettext('French label override')"
                :model-value="labelFr"
                :placeholder="$gettext('French label')"
                @update:model-value="emit(UPDATE_LABEL_FR_EVENT, $event ?? '')"
            />
        </div>
        <div class="cell narrow">
            <InputNumber
                data-testid="field-max-values"
                :aria-label="$gettext('Maximum number of values')"
                :max="MAX_VALUES"
                :min="1"
                :model-value="maxValues"
                :placeholder="$gettext('All')"
                @update:model-value="onMaxValuesChange"
            />
        </div>
        <div class="cell actions">
            <Button
                data-testid="move-field-up"
                icon="fa fa-arrow-up"
                :aria-label="$gettext('Move up')"
                :disabled="!canMoveUp"
                :text="true"
                @click="emit(MOVE_UP_EVENT)"
            />
            <Button
                data-testid="move-field-down"
                icon="fa fa-arrow-down"
                :aria-label="$gettext('Move down')"
                :disabled="!canMoveDown"
                :text="true"
                @click="emit(MOVE_DOWN_EVENT)"
            />
            <Button
                data-testid="remove-field"
                icon="fa fa-trash"
                severity="danger"
                :aria-label="$gettext('Remove this field')"
                :text="true"
                @click="emit(REMOVE_EVENT)"
            />
        </div>
    </div>
</template>

<style scoped>
.field-row {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr 1fr 6rem auto;
    gap: 0.5rem;
    align-items: start;
    padding-block: 0.375rem;
    border-block-end: 0.0625rem solid var(--p-content-border-color);
}

.field-row .cell {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    min-inline-size: 0;
}

.field-row .cell.actions {
    flex-direction: row;
    align-items: center;
}

.field-row .unknown-alias {
    color: var(--p-red-500);
}
</style>
