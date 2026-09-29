<script setup lang="ts">
import { computed } from "vue";

import { useLinkedMarks } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedMarks.ts";
import { focusHue } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";

import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

interface Digit {
    slot: number;
    hue: string;
    evidence: boolean;
    own: boolean;
}

/**
 * The pip of a focus toggle: one digit per slot the thing standing for
 * `node` relates to, each on its slot's hue (solid: linked directly,
 * hollow: cited as evidence, underlined: the pinned node itself), or a
 * « + » when it relates to none (drawn from `data-n`, so the digits stay
 * out of the toggle's text). Place it as a direct child of the
 * element carrying `ms-focus`, which shows it (`css/explorer`). Hidden
 * from assistive technologies: the toggle's `aria-pressed` and name carry
 * the state, the digits repeat the colour.
 */
const props = defineProps<{
    node: NodeId | readonly NodeId[];
}>();

const marks = useLinkedMarks();

const digits = computed<Digit[]>(() =>
    marks.slots(props.node).map(({ slot, level }) => ({
        slot,
        hue: focusHue(slot),
        evidence: level === "evidence",
        own: level === "self",
    })),
);
</script>

<template>
    <span
        class="ms-focus-pip"
        aria-hidden="true"
    >
        <template v-if="digits.length > 0">
            <b
                v-for="digit in digits"
                :key="digit.slot"
                :class="{ ev: digit.evidence, own: digit.own }"
                :data-n="digit.slot"
                :style="{ '--h': digit.hue }"
            ></b>
        </template>
        <b
            v-else
            class="add"
            data-n="+"
        ></b>
    </span>
</template>
