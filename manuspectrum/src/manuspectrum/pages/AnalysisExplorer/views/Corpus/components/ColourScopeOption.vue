<script setup lang="ts">
import { ref, useId } from "vue";
import { useGettext } from "vue3-gettext";

import HelpTip from "@/manuspectrum/pages/AnalysisExplorer/components/HelpTip.vue";

import { useVocabulary } from "@/manuspectrum/pages/AnalysisExplorer/composables/useVocabulary.ts";

import type { ColourScope } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const SCOPES: readonly ColourScope[] = ["all", "part", "material"];

/**
 * Where the colour filter reads a colour: on the studied component or on an
 * identified material (`all`, the default), on the component alone, or on the
 * material alone. Folded to its disclosure button; each choice has a help tip
 * the radio is described by.
 */
const props = defineProps<{ scope: ColourScope }>();
const emit = defineEmits<{ change: [scope: ColourScope] }>();

const { $gettext } = useGettext();
const { colourScopeLabel, colourScopeHint } = useVocabulary();
const baseId = useId();

const open = ref(false);

function toggle(): void {
    open.value = !open.value;
}

function onChoose(scope: ColourScope): void {
    emit("change", scope);
}
</script>

<template>
    <div class="colour-scope">
        <button
            type="button"
            class="disclosure"
            :aria-expanded="open ? 'true' : 'false'"
            :aria-controls="`${baseId}-options`"
            @click="toggle"
        >
            <span
                class="chevron"
                aria-hidden="true"
                >{{ open ? "▾" : "▸" }}</span
            >
            <span>{{ $gettext("Where the colour is recorded") }}</span>
        </button>
        <fieldset
            v-show="open"
            :id="`${baseId}-options`"
            class="options"
        >
            <legend class="visually-hidden">
                {{ $gettext("Where the colour is recorded") }}
            </legend>
            <HelpTip
                v-for="choice in SCOPES"
                :key="choice"
                v-slot="{ describedby }"
                class="option-tip"
                :text="colourScopeHint(choice)"
            >
                <label class="option">
                    <input
                        type="radio"
                        :name="`${baseId}-scope`"
                        :value="choice"
                        :checked="props.scope === choice"
                        :aria-describedby="describedby"
                        @change="onChoose(choice)"
                    />
                    <span class="text">{{ colourScopeLabel(choice) }}</span>
                </label>
            </HelpTip>
        </fieldset>
    </div>
</template>

<style scoped>
.colour-scope {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.25rem;
    padding-block-start: 0.5rem;
    border-block-start: 0.0625rem solid var(--border);
}

.colour-scope .disclosure {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    justify-self: start;
    min-block-size: var(--explorer-target, 2.75rem);
    padding: 0;
    border: none;
    background: transparent;
    color: var(--blue-text);
    font: inherit;
    font-size: 0.75rem;
    cursor: pointer;
}

.colour-scope .options {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    min-inline-size: 0;
    border: none;
}

.colour-scope .option-tip {
    display: flex;
}

.colour-scope .option {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: var(--explorer-target, 2.75rem);
    font-size: 0.8125rem;
    cursor: pointer;
}

.colour-scope .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}

.colour-scope input:focus-visible,
.colour-scope .disclosure:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
