<script setup lang="ts">
import {
    computed,
    inject,
    nextTick,
    onBeforeUnmount,
    ref,
    shallowRef,
    useTemplateRef,
    watch,
} from "vue";
import { useGettext } from "vue3-gettext";

import DraftBanner from "@/manuspectrum/pages/AnalysisExplorer/components/DraftBanner.vue";
import LoadingSpinner from "@/manuspectrum/pages/AnalysisExplorer/components/LoadingSpinner.vue";
import UnavailableState from "@/manuspectrum/pages/AnalysisExplorer/components/UnavailableState.vue";
import AutoWindowBody from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/AutoWindowBody.vue";
import ToolMenu from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ToolMenu.vue";
import ToolWindowBody from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ToolWindowBody.vue";
import WindowGrid from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/WindowGrid.vue";

import { useScreenHeading } from "@/manuspectrum/pages/AnalysisExplorer/composables/useScreenHeading.ts";
import { useSelectionItems } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionItems.ts";
import { useSynthesis } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSynthesis.ts";
import {
    ANNOUNCE_KEY,
    SELECTION_ITEMS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { setFullSeriesRoom } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    forgetWindows,
    readHidden,
    readTools,
    writeHidden,
    writeTools,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layout.ts";
import { toolTitles } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tool-labels.ts";
import {
    offeredTools,
    staleToolFilters,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tools.ts";
import {
    autoWindows,
    keepUnchangedCurves,
    windowIdsOf,
    xyCurvesGained,
    xySpectraCount,
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
import type { ToolKind } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

const FIRST_SIZE: Record<AutoWindowKind, WindowSize> = {
    xy: "M",
    maps: "L",
    micro: "M",
    characterizations: "L",
    "not-in-chart": "S",
};

const TOOL_SIZE: Record<ToolKind, WindowSize> = {
    coverage: "L",
    "colour-material": "L",
    periodic: "L",
    folio: "M",
};

/**
 * The Compare view: windows arranged from the Selection (`autoWindows`),
 * shown once every Selection key has been read. « Close » on a window
 * arranged from the Selection hides it and leaves the Selection as it is;
 * a hidden window comes back from « Hidden windows » or with « Rearrange ».
 * The hidden windows are kept next to the layout (`ms-explorer-layout-v1`);
 * a window whose items all leave the Selection is gone, and forgotten there.
 * A hidden XY window that gains spectra stays hidden: they are announced,
 * and « Hidden windows » counts the spectra it holds that it did not hold
 * when hidden (or when the view opened with it hidden). An XY window whose
 * spectra did not change keeps its curves, so its chart is not drawn
 * again. While the view is shown, the tab keeps the full series of every
 * spectrum its XY windows draw, hidden ones included (`setFullSeriesRoom`,
 * at most 30): adding a spectrum or showing a window again reads no series
 * twice. A failure to read the Selection offers a retry, before and after
 * the windows are arranged.
 * Its heading takes the focus when the shell asks (`SCREEN_FOCUS_KEY`).
 *
 * The tools (D60) are opened from « + Tool », which offers those the
 * synthesis of the Selection (`useSynthesis`, read while the view is shown)
 * has something for. A tool window follows the grid like the others,
 * after them; « Close » closes the tool. The tools open are kept with the
 * layout and opened again with the view; a tool filter naming a value the
 * Selection no longer holds is dropped. While a tool is open, the drafts
 * the synthesis reads are counted above the windows. When the last window
 * shown is hidden or closed, the focus goes to « Hidden windows », else to
 * the heading.
 */
const announce = inject(ANNOUNCE_KEY, () => undefined, false);
const selectionItems = inject(SELECTION_ITEMS_KEY, useSelectionItems, false);

const store = useExplorerStore();
const selection = selectionItems();
const synthesis = useSynthesis(() => store.basket.map((item) => item.key));
const { $gettext, $ngettext, interpolate } = useGettext();
const root = useTemplateRef<HTMLElement>("root");
const heading = useTemplateRef<HTMLElement>("heading");
useScreenHeading(() => heading.value);

if (store.compare.tools.length === 0) {
    for (const tool of readTools()) store.openTool(tool.kind, tool.params);
}

const hidden = ref<string[]>(readHidden());
/** Set once the Selection has been read: windows are arranged from then on. */
const opened = ref(false);
/** Each hidden window as it was when hidden, or when the view opened with it hidden. */
const hiddenFrom = shallowRef(new Map<string, AutoWindow>());

// The windows last compared for new spectra, once the view is open.
let known: AutoWindow[] = [];

const windows = computed<AutoWindow[]>((previous) =>
    keepUnchangedCurves(
        previous ?? [],
        autoWindows(
            store.basket,
            selection.byKey.value,
            selection.missing.value,
        ),
    ),
);
const windowById = computed(
    () => new Map(windows.value.map((window) => [window.id, window])),
);
const specs = computed<CompareWindowSpec[]>(() =>
    windows.value.map((window) => ({
        id: window.id,
        title: titleOf(window),
        size: FIRST_SIZE[window.kind],
        folded:
            window.kind === "xy" || window.kind === "maps"
                ? window.folded
                : undefined,
    })),
);
const tools = computed(() => store.compare.tools);
const toolById = computed(
    () => new Map(tools.value.map((tool) => [tool.id, tool])),
);
const toolSpecs = computed<CompareWindowSpec[]>(() => {
    const titles = toolTitles($gettext);
    return tools.value.map((tool) => ({
        id: tool.id,
        title: titles[tool.kind],
        size: TOOL_SIZE[tool.kind],
    }));
});
const gridSpecs = computed(() => [
    ...specs.value.filter((spec) => !hidden.value.includes(spec.id)),
    ...toolSpecs.value,
]);
const draftCount = computed(() =>
    tools.value.length > 0 && synthesis.status.value === "ready"
        ? synthesis.data.value?.unpublishedCount ?? 0
        : 0,
);
const offered = computed(() =>
    synthesis.status.value === "ready" && synthesis.data.value
        ? offeredTools(synthesis.data.value)
        : null,
);
const hiddenSpecs = computed(() =>
    specs.value.filter((spec) => hidden.value.includes(spec.id)),
);
/** The spectra each hidden XY window holds that it did not hold when hidden. */
const newSpectra = computed(() =>
    xyCurvesGained(
        [...hiddenFrom.value.values()],
        windows.value.filter((window) => hiddenFrom.value.has(window.id)),
    ),
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
        if (!opened.value) known = windows.value;
        opened.value = true;
        const ids = windowIdsOf(windows.value);
        forgetWindows([...ids, ...tools.value.map((tool) => tool.id)]);
        const kept = hidden.value.filter((id) => ids.includes(id));
        if (kept.length !== hidden.value.length) hidden.value = kept;
        rememberHidden();
    },
    { immediate: true },
);

watch(() => xySpectraCount(windows.value), setFullSeriesRoom, {
    immediate: true,
});

watch(
    () => store.compare.tools,
    (open) => writeTools(open),
);

watch(
    () => (synthesis.status.value === "ready" ? synthesis.data.value : null),
    (answer) => {
        if (!answer) return;
        for (const key of staleToolFilters(answer, store.compare.toolFilters)) {
            store.setToolFilter(key, null);
        }
    },
    { immediate: true },
);

watch(windows, (next) => {
    if (!opened.value) return;
    const gaining = [...xyCurvesGained(known, next).keys()].filter(
        (id) => (newSpectra.value.get(id) ?? 0) > 0,
    );
    known = next;
    if (gaining.length === 0) return;
    announce(
        gaining
            .map((id) => {
                const count = newSpectra.value.get(id) ?? 0;
                return interpolate(
                    $ngettext(
                        "%{title}: %{n} new spectrum since the window was hidden.",
                        "%{title}: %{n} new spectra since the window was hidden.",
                        count,
                    ),
                    { title: specTitle(id), n: count },
                    true,
                );
            })
            .join(" "),
    );
});

onBeforeUnmount(() => setFullSeriesRoom(0));

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
        case "maps":
            return $gettext("Element maps");
        case "micro":
            return $gettext("Micro-images");
        case "characterizations":
            return $gettext("Identified materials");
        case "not-in-chart":
            return $gettext("Not in a chart");
    }
}

function specTitle(id: string): string {
    return specs.value.find((spec) => spec.id === id)?.title ?? "";
}

function showLabel(title: string): string {
    return interpolate($gettext("Show %{title}"), { title }, true);
}

function newSpectraLabel(count: number): string {
    return interpolate(
        $ngettext(
            "%{n} new spectrum since hidden",
            "%{n} new spectra since hidden",
            count,
        ),
        { n: count },
        true,
    );
}

/** Keeps the state of each window still hidden, and takes the current one of a window just hidden. */
function rememberHidden(): void {
    hiddenFrom.value = new Map(
        hidden.value.flatMap((id) => {
            const state = hiddenFrom.value.get(id) ?? windowById.value.get(id);
            return state ? [[id, state] as const] : [];
        }),
    );
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
    rememberHidden();
}

/** Gives the focus to « Hidden windows », else to the heading, once no window is shown. */
async function focusWithoutWindows(): Promise<void> {
    if (gridSpecs.value.length > 0) return;
    await nextTick();
    (
        root.value?.querySelector<HTMLElement>(".hidden-windows button") ??
        heading.value
    )?.focus();
}

/** Hides a window arranged from the Selection; a tool is closed. */
async function closeWindow({ id }: { id: string }): Promise<void> {
    const spec = specs.value.find((entry) => entry.id === id);
    if (!windowById.value.has(id) || !spec) {
        const title = toolSpecs.value.find((entry) => entry.id === id)?.title;
        store.closeTool(id);
        if (title) {
            announce(
                interpolate($gettext("%{title} closed."), { title }, true),
            );
        }
        await focusWithoutWindows();
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
    await focusWithoutWindows();
}

async function showWindow(id: string): Promise<void> {
    setHidden(hidden.value.filter((entry) => entry !== id));
    await nextTick();
    windowElement(id)?.focus();
}

/** Opens a tool once; a tool already open takes the focus. */
async function chooseTool({ kind }: { kind: ToolKind }): Promise<void> {
    const known = store.compare.tools.map((tool) => tool.id);
    const id = store.openTool(kind);
    if (!known.includes(id)) return;
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
            ref="heading"
            class="visually-hidden"
            tabindex="-1"
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
            <UnavailableState
                v-if="selection.status.value === 'error'"
                status="error"
                :hide-home="true"
                @retry="selection.retry"
            />
            <DraftBanner
                scope="tools"
                :count="draftCount"
            />
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
                            <span
                                v-if="newSpectra.has(spec.id)"
                                class="badge"
                                >{{
                                    newSpectraLabel(newSpectra.get(spec.id)!)
                                }}</span
                            >
                        </button>
                    </li>
                </ul>
            </section>
            <WindowGrid
                v-if="specs.length > 0 || toolSpecs.length > 0"
                :windows="gridSpecs"
                :retained="hidden"
                @close="closeWindow"
                @rearrange="showAll"
            >
                <template #toolbar>
                    <ToolMenu
                        :offered="offered"
                        :status="synthesis.status.value"
                        @choose="chooseTool"
                        @retry="synthesis.retry"
                    />
                </template>
                <template #default="{ window: spec }">
                    <AutoWindowBody
                        v-if="windowById.get(spec.id)"
                        :window="windowById.get(spec.id)!"
                    />
                    <ToolWindowBody
                        v-else-if="toolById.get(spec.id)"
                        :kind="toolById.get(spec.id)!.kind"
                        :status="synthesis.status.value"
                        :synthesis="synthesis.data.value"
                        @retry="synthesis.retry"
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

.compare-view .hidden-windows .badge {
    margin-inline-start: 0.5rem;
    padding-inline: 0.375rem;
    border-radius: 999rem;
    background: var(--ink);
    color: var(--surface);
    font-size: 0.75rem;
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
