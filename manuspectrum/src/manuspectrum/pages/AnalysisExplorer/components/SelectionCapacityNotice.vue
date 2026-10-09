<script setup lang="ts">
import { computed, inject } from "vue";
import { useGettext } from "vue3-gettext";

import {
    ICONS,
    ICON_VIEW_BOX,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";
import { useSelectionToggle } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionToggle.ts";
import { SELECTION_DRAWER_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { BASKET_LIMIT } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";

/**
 * Says why the « select all » of a zone does nothing: the Selection is full,
 * or the zone's `keys` do not fit in the places left. Shown only while that
 * select-all is refused and no grouped change is on screen (one message per
 * spot); it is not a live region, the refused click announces itself. Its
 * `id` is what the zone's checkboxes name in `aria-describedby`. « Open the
 * Selection » opens the drawer, to remove items.
 */
const props = defineProps<{ keys: string[]; id: string }>();

const { $gettext, $ngettext, interpolate } = useGettext();
const toggle = useSelectionToggle();
const drawer = inject(SELECTION_DRAWER_KEY, null);

const refusal = computed(() => toggle.refusal(props.keys));
const shown = computed(
    () => refusal.value !== null && toggle.lastBulk.value === null,
);
const title = computed(() => {
    const refused = refusal.value;
    if (refused === null) return "";
    if (refused.kind === "full") {
        return interpolate(
            $gettext("Selection full (%{limit} / %{limit})"),
            { limit: BASKET_LIMIT },
            true,
        );
    }
    return interpolate(
        $ngettext(
            "Only one place left in the Selection",
            "Only %{free} places left in the Selection",
            refused.free,
        ),
        { free: refused.free },
        true,
    );
});
const text = computed(() => {
    const refused = refusal.value;
    if (refused === null) return "";
    if (refused.kind === "full") {
        return $gettext("Remove items to add others.");
    }
    return interpolate(
        $gettext(
            "This page has %{n} analyses to add: tick them one by one or make room.",
        ),
        { n: refused.needed },
        true,
    );
});

function openSelection(): void {
    drawer?.open();
}
</script>

<template>
    <div
        v-if="shown"
        :id="props.id"
        class="selection-capacity-notice"
    >
        <svg
            class="icon"
            :viewBox="ICON_VIEW_BOX"
            aria-hidden="true"
            focusable="false"
        >
            <path
                v-for="shape in ICONS['exclamation-circle']"
                :key="shape"
                :d="shape"
            />
        </svg>
        <p class="title">
            <span>{{ title }}</span>
        </p>
        <p class="text">
            <span>{{ text }}</span>
        </p>
        <button
            type="button"
            data-action="open-selection"
            @click="openSelection"
        >
            <span>{{ $gettext("Open the Selection") }}</span>
            <svg
                class="arrow"
                :viewBox="ICON_VIEW_BOX"
                aria-hidden="true"
                focusable="false"
            >
                <path
                    v-for="shape in ICONS['arrow-right']"
                    :key="shape"
                    :d="shape"
                />
            </svg>
        </button>
    </div>
</template>

<style scoped>
.selection-capacity-notice {
    display: grid;
    grid-template-columns: 1.125rem minmax(0, 1fr);
    gap: 0.125rem 0.625rem;
    padding: 0.625rem 0.75rem;
    border-inline-start: 0.1875rem solid var(--accent);
    border-radius: 0.5rem;
    background: color-mix(in srgb, var(--accent) 9%, var(--surface));
    font-size: 0.8125rem;
}

.selection-capacity-notice .icon {
    inline-size: 1.125rem;
    block-size: 1.125rem;
    margin-block-start: 0.0625rem;
    fill: var(--accent-text);
}

.selection-capacity-notice .title {
    color: var(--ink);
    font-weight: 600;
}

.selection-capacity-notice .text {
    grid-column: 2;
    color: var(--ink-muted);
}

.selection-capacity-notice button {
    display: inline-flex;
    grid-column: 2;
    gap: 0.375rem;
    align-items: center;
    justify-self: start;
    min-block-size: var(--explorer-target, 2.75rem);
    padding: 0;
    border: 0;
    background: none;
    color: var(--blue-text);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
}

.selection-capacity-notice button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.selection-capacity-notice .arrow {
    inline-size: 0.875rem;
    block-size: 0.875rem;
    fill: var(--blue-text);
}
</style>
