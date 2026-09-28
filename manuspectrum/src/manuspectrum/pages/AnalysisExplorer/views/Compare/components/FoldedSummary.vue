<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { COLOURED_SLOTS } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";

import type { FoldedSummary } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/folded-summary.ts";

const SHOWN_SLOTS = 8;
const SHOWN_NAMES = 6;

/**
 * What a folded window shows under its header: a chip per slot it holds
 * (in its series colour for A1–A8, the context grey beyond; the first
 * `SHOWN_SLOTS`, then how many more), one counted line (« 4 FTIR spectra,
 * not drawn », « 2 maps · Pb, Hg ») and the button that unfolds it,
 * named after the window's `title`.
 */
const props = defineProps<{ summary: FoldedSummary; title: string }>();

const emit = defineEmits<{ (event: "unfold"): void }>();

const { $gettext, $ngettext, interpolate } = useGettext();

const chips = computed(() => {
    const shown = props.summary.slots.slice(0, SHOWN_SLOTS).map((slot) => ({
        key: String(slot),
        text: slotLabel(slot),
        tone: slot < COLOURED_SLOTS ? `slot-${slot + 1}` : "slot-context",
    }));
    const more = props.summary.slots.length - shown.length;
    return more > 0
        ? [...shown, { key: "more", text: `+${more}`, tone: "more" }]
        : shown;
});
const names = computed(() => {
    const list = props.summary.names;
    const shown = list.slice(0, SHOWN_NAMES).join(", ");
    return list.length > SHOWN_NAMES ? `${shown}…` : shown;
});
const line = computed(() => {
    const count = props.summary.count;
    if (props.summary.kind === "maps") {
        return interpolate(
            names.value
                ? $ngettext(
                      "%{n} map · %{layers}",
                      "%{n} maps · %{layers}",
                      count,
                  )
                : $ngettext("%{n} map", "%{n} maps", count),
            { n: count, layers: names.value },
            true,
        );
    }
    return interpolate(
        names.value
            ? $ngettext(
                  "%{n} %{techniques} spectrum, not drawn",
                  "%{n} %{techniques} spectra, not drawn",
                  count,
              )
            : $ngettext(
                  "%{n} spectrum, not drawn",
                  "%{n} spectra, not drawn",
                  count,
              ),
        { n: count, techniques: names.value },
        true,
    );
});
const action = computed(() =>
    props.summary.kind === "maps" ? $gettext("Show") : $gettext("Draw"),
);
const actionLabel = computed(() =>
    interpolate(
        props.summary.kind === "maps"
            ? $gettext("Show « %{title} »")
            : $gettext("Draw « %{title} »"),
        { title: props.title },
        true,
    ),
);
</script>

<template>
    <div class="folded-summary">
        <ul
            class="slots"
            :aria-label="$gettext('Items of the Selection')"
        >
            <li
                v-for="chip in chips"
                :key="chip.key"
                :class="chip.tone"
            >
                <span>{{ chip.text }}</span>
            </li>
        </ul>
        <p class="line">
            <span>{{ line }}</span>
        </p>
        <button
            type="button"
            class="unfold"
            :aria-label="actionLabel"
            @click="emit('unfold')"
        >
            <span>{{ action }}</span>
        </button>
    </div>
</template>

<style scoped>
.folded-summary {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.375rem 0.75rem;
    padding-block: 0.25rem;
    padding-inline: 0.75rem;
    font-size: 0.8125rem;
}

.folded-summary .slots {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.folded-summary .slots li {
    padding-block: 0.0625rem;
    padding-inline: 0.375rem;
    border-radius: 0.25rem;
    background: var(--series-context);
    color: var(--ink);
    font: 600 0.6875rem var(--font-mono);
    font-variant-numeric: tabular-nums;
}

.folded-summary .slots .more {
    background: var(--bg-alt);
    color: var(--ink-muted);
}

.folded-summary .slots .slot-1 {
    background: var(--series-1);
    color: var(--series-1-on);
}

.folded-summary .slots .slot-2 {
    background: var(--series-2);
    color: var(--series-2-on);
}

.folded-summary .slots .slot-3 {
    background: var(--series-3);
    color: var(--series-3-on);
}

.folded-summary .slots .slot-4 {
    background: var(--series-4);
    color: var(--series-4-on);
}

.folded-summary .slots .slot-5 {
    background: var(--series-5);
    color: var(--series-5-on);
}

.folded-summary .slots .slot-6 {
    background: var(--series-6);
    color: var(--series-6-on);
}

.folded-summary .slots .slot-7 {
    background: var(--series-7);
    color: var(--series-7-on);
}

.folded-summary .slots .slot-8 {
    background: var(--series-8);
    color: var(--series-8-on);
}

.folded-summary .line {
    flex: 1 1 12rem;
    min-inline-size: 0;
    margin: 0;
    color: var(--ink-muted);
    font-variant-numeric: tabular-nums;
}

.folded-summary .unfold {
    min-block-size: var(--explorer-target, 2rem);
    padding-inline: 0.625rem;
    border: none;
    border-radius: 0.375rem;
    background: var(--bg-alt);
    color: var(--ink);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
}

.folded-summary .unfold:hover {
    background: var(--border-hover);
}

.folded-summary .unfold:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
