<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import WindowGrid from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/WindowGrid.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { placeholderWindows } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

import type {
    AutoWindow,
    AutoWindowKind,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";
import type {
    CompareWindowSpec,
    WindowSize,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/types.ts";

const FIRST_SIZE: Record<AutoWindowKind, WindowSize> = {
    xy: "M",
    micro: "M",
    characterizations: "L",
    "not-in-chart": "S",
};

/**
 * The Compare view: windows arranged from the Selection. Closing a window
 * arranged from the Selection takes its items out of the Selection; closing
 * a tool closes the tool.
 */
const store = useExplorerStore();
const { $gettext } = useGettext();

const autoWindows = computed<AutoWindow[]>(() =>
    placeholderWindows(store.basket),
);
const windows = computed<CompareWindowSpec[]>(() =>
    autoWindows.value.map((window) => ({
        id: window.id,
        title: titleOf(window.kind),
        size: FIRST_SIZE[window.kind],
    })),
);

function titleOf(kind: AutoWindowKind): string {
    switch (kind) {
        case "xy":
            return $gettext("Spectra");
        case "micro":
            return $gettext("Micro-images");
        case "characterizations":
            return $gettext("Identified materials");
        case "not-in-chart":
            return $gettext("Not in a chart");
    }
}

function closeWindow({ id }: { id: string }): void {
    const window = autoWindows.value.find((entry) => entry.id === id);
    if (window) {
        for (const key of window.keys) store.removeFromBasket(key);
    } else {
        store.closeTool(id);
    }
}
</script>

<template>
    <section
        class="compare-view"
        aria-labelledby="explorer-compare-title"
    >
        <h2
            id="explorer-compare-title"
            class="visually-hidden"
        >
            <span>{{ $gettext("Compare") }}</span>
        </h2>
        <p
            v-if="windows.length === 0"
            class="empty"
        >
            <span>{{
                $gettext(
                    "Your Selection is empty. Add analyses or identified materials with « + Selection ».",
                )
            }}</span>
        </p>
        <WindowGrid
            v-else
            :windows="windows"
            @close="closeWindow"
        />
    </section>
</template>

<style scoped>
.compare-view {
    display: grid;
    gap: 1rem;
}

.compare-view .empty {
    color: var(--ink-muted);
}

.compare-view .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}
</style>
