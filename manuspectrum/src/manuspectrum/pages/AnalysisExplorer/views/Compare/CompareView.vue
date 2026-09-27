<script setup lang="ts">
import { computed, inject, nextTick, ref, useTemplateRef, watch } from "vue";
import { useGettext } from "vue3-gettext";

import LoadingSpinner from "@/manuspectrum/pages/AnalysisExplorer/components/LoadingSpinner.vue";
import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";
import AutoWindowBody from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/AutoWindowBody.vue";
import WindowGrid from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/WindowGrid.vue";

import { useSelectionItems } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionItems.ts";
import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    forgetWindows,
    readHidden,
    writeHidden,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layout.ts";
import {
    autoWindows,
    windowIdsOf,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

import type {
    CompareWindowSpec,
    WindowSize,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/types.ts";
import type {
    AutoWindow,
    AutoWindowKind,
    XyWindow,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

const FIRST_SIZE: Record<AutoWindowKind, WindowSize> = {
    xy: "M",
    micro: "M",
    characterizations: "L",
    "not-in-chart": "S",
};

/**
 * The Compare view: windows arranged from the Selection (`autoWindows`),
 * shown once every Selection key has been read. « Close » on a window
 * arranged from the Selection hides it and leaves the Selection as it is;
 * a hidden window comes back from « Hidden windows » or with « Rearrange ».
 * The hidden windows are kept next to the layout (`ms-explorer-layout-v1`);
 * a window whose items all leave the Selection is gone, and forgotten there.
 */
const announce = inject(ANNOUNCE_KEY, () => undefined, false);

const store = useExplorerStore();
const selection = useSelectionItems();
const { $gettext, interpolate } = useGettext();
const root = useTemplateRef<HTMLElement>("root");

const hidden = ref<string[]>(readHidden());
/** Set once the Selection has been read: windows are arranged from then on. */
const opened = ref(false);

const windows = computed<AutoWindow[]>(() =>
    autoWindows(store.basket, selection.byKey.value, selection.missing.value),
);
const windowById = computed(
    () => new Map(windows.value.map((window) => [window.id, window])),
);
const specs = computed<CompareWindowSpec[]>(() =>
    windows.value.map((window) => ({
        id: window.id,
        title: titleOf(window),
        size: FIRST_SIZE[window.kind],
        folded: window.kind === "xy" ? window.folded : undefined,
    })),
);
const shownSpecs = computed(() =>
    specs.value.filter((spec) => !hidden.value.includes(spec.id)),
);
const hiddenSpecs = computed(() =>
    specs.value.filter((spec) => hidden.value.includes(spec.id)),
);
const hiddenTitle = computed(() =>
    interpolate(
        $gettext("Hidden windows (%{n})"),
        { n: hiddenSpecs.value.length },
        true,
    ),
);

watch(
    () =>
        selection.settled.value ? windowIdsOf(windows.value).join("\n") : null,
    (joined) => {
        if (joined === null) return;
        opened.value = true;
        const ids = windowIdsOf(windows.value);
        forgetWindows(ids);
        const kept = hidden.value.filter((id) => ids.includes(id));
        if (kept.length !== hidden.value.length) hidden.value = kept;
    },
    { immediate: true },
);

function xyTitle(window: XyWindow): string {
    if (window.configName) return window.configName;
    if (window.xLabel && window.yLabel) {
        return interpolate(
            $gettext("%{y} against %{x}"),
            { x: window.xLabel, y: window.yLabel },
            true,
        );
    }
    return (
        window.yLabel ??
        window.xLabel ??
        $gettext("Spectra without axis titles")
    );
}

function titleOf(window: AutoWindow): string {
    switch (window.kind) {
        case "xy":
            return xyTitle(window);
        case "micro":
            return $gettext("Micro-images");
        case "characterizations":
            return $gettext("Identified materials");
        case "not-in-chart":
            return $gettext("Not in a chart");
    }
}

function showLabel(title: string): string {
    return interpolate($gettext("Show %{title}"), { title }, true);
}

function windowElement(id: string): HTMLElement | null {
    const items =
        root.value?.querySelectorAll<HTMLElement>(".grid-stack-item") ?? [];
    for (const item of items) {
        if (item.dataset.windowId === id) {
            return item.querySelector<HTMLElement>(".compare-window");
        }
    }
    return null;
}

function setHidden(ids: string[]): void {
    hidden.value = ids;
    writeHidden(ids);
}

/** Hides a window arranged from the Selection; a tool is closed. */
async function closeWindow({ id }: { id: string }): Promise<void> {
    const spec = specs.value.find((entry) => entry.id === id);
    if (!windowById.value.has(id) || !spec) {
        store.closeTool(id);
        return;
    }
    setHidden([...hidden.value, id]);
    announce(
        interpolate(
            $gettext("%{title} hidden. Show it again from « Hidden windows »."),
            { title: spec.title },
            true,
        ),
    );
    if (shownSpecs.value.length === 0) {
        await nextTick();
        root.value
            ?.querySelector<HTMLElement>(".hidden-windows button")
            ?.focus();
    }
}

async function showWindow(id: string): Promise<void> {
    setHidden(hidden.value.filter((entry) => entry !== id));
    await nextTick();
    windowElement(id)?.focus();
}

function showAll(): void {
    if (hidden.value.length > 0) setHidden([]);
}
</script>

<template>
    <section
        ref="root"
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
            v-if="store.basket.length === 0"
            class="empty"
        >
            <span>{{
                $gettext(
                    "Your Selection is empty. Add analyses or identified materials with « + Selection ».",
                )
            }}</span>
        </p>
        <UnavailableState
            v-else-if="!opened && selection.status.value === 'error'"
            status="error"
            :hide-home="true"
            @retry="selection.retry"
        />
        <p
            v-else-if="!opened"
            class="loading"
            role="status"
        >
            <LoadingSpinner />
            <span>{{ $gettext("Reading the Selection…") }}</span>
        </p>
        <template v-else>
            <section
                v-if="hiddenSpecs.length > 0"
                class="hidden-windows"
                aria-labelledby="explorer-compare-hidden"
            >
                <h3 id="explorer-compare-hidden">
                    <span>{{ hiddenTitle }}</span>
                </h3>
                <ul>
                    <li
                        v-for="spec in hiddenSpecs"
                        :key="spec.id"
                    >
                        <button
                            type="button"
                            :data-window-id="spec.id"
                            @click="showWindow(spec.id)"
                        >
                            <span>{{ showLabel(spec.title) }}</span>
                        </button>
                    </li>
                </ul>
            </section>
            <WindowGrid
                v-if="specs.length > 0"
                :windows="shownSpecs"
                :retained="hidden"
                @close="closeWindow"
                @rearrange="showAll"
            >
                <template #default="{ window: spec }">
                    <AutoWindowBody
                        v-if="windowById.get(spec.id)"
                        :window="windowById.get(spec.id)!"
                    />
                </template>
            </WindowGrid>
        </template>
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

.compare-view .loading {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--ink-muted);
}

.compare-view .hidden-windows {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
}

.compare-view .hidden-windows h3 {
    margin: 0;
    font-size: 0.875rem;
    font-weight: 600;
}

.compare-view .hidden-windows ul {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.compare-view .hidden-windows button {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.compare-view .hidden-windows button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
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
