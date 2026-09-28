<script setup lang="ts">
import {
    computed,
    inject,
    nextTick,
    onBeforeUnmount,
    provide,
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
import FoldedSummary from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FoldedSummary.vue";
import HiddenWindowsMenu from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/HiddenWindowsMenu.vue";
import SelectionIndicator from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/SelectionIndicator.vue";
import ToolMenu from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ToolMenu.vue";
import ToolWindowBody from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ToolWindowBody.vue";
import WindowGrid from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/WindowGrid.vue";

import { useLinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import { useScreenHeading } from "@/manuspectrum/pages/AnalysisExplorer/composables/useScreenHeading.ts";
import { useSelectionItems } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionItems.ts";
import { useSynthesis } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSynthesis.ts";
import {
    ANNOUNCE_KEY,
    FOLIO_REQUEST_KEY,
    LINKED_SELECTION_KEY,
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
import { foldedSummary } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/folded-summary.ts";
import { toolTitles } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tool-labels.ts";
import { offeredTools } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tools.ts";
import {
    autoWindows,
    keepUnchangedCurves,
    windowIdsOf,
    xyCurvesGained,
    xySpectraCount,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

import type {
    CompareWindowSpec,
    HiddenWindowEntry,
    WindowSize,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/types.ts";
import type {
    AutoWindow,
    XyWindow,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";
import type { FolioRequest } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import type { ToolKind } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

/** The size every window and tool opens at. */
const FIRST_SIZE: WindowSize = "M";

/**
 * The Compare view: windows arranged from the Selection (`autoWindows`),
 * shown once every Selection key has been read. « Close » on a window
 * arranged from the Selection hides it and leaves the Selection as it is;
 * a hidden window comes back from « Hidden windows », a menu of the
 * toolbar, never with « Rearrange ».
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
 * layout and opened again with the view. While a tool is open, the drafts
 * the synthesis reads are counted above the windows (the last count while
 * the next synthesis is read). When the last window
 * shown is hidden or closed, the focus goes to « Hidden windows », else to
 * the heading.
 *
 * The view provides the linked selection of its windows
 * (`useLinkedSelection`, `LINKED_SELECTION_KEY`), shown in the toolbar by
 * `SelectionIndicator` before « Hidden windows » and « + Tool ». Its
 * windows mark the linked with the `--linked-*` tokens of the page. A
 * folded window sums up what it holds (`FoldedSummary`), with the button
 * that unfolds it. A folio asked of the folio image tools
 * (`FOLIO_REQUEST_KEY`, a folio of the coverage matrix clicked) is shown
 * by every one open, and said once after the selection's count.
 */
const announce = inject(ANNOUNCE_KEY, () => undefined, false);
const selectionItems = inject(SELECTION_ITEMS_KEY, useSelectionItems, false);

const store = useExplorerStore();
const selection = selectionItems();
const synthesis = useSynthesis(() => store.basket.map((item) => item.key));
const linked = useLinkedSelection({
    items: selection,
    synthesis,
    announce: (message) => announce(message),
});
provide(LINKED_SELECTION_KEY, linked);
const folioAsked = ref<FolioRequest | null>(null);
provide(FOLIO_REQUEST_KEY, { asked: folioAsked, show: showFolio });
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
const summaries = computed(
    () =>
        new Map(
            windows.value.flatMap((window) => {
                const summary = foldedSummary(window);
                return summary ? [[window.id, summary] as const] : [];
            }),
        ),
);
const specs = computed<CompareWindowSpec[]>(() =>
    windows.value.map((window) => ({
        id: window.id,
        title: titleOf(window),
        kind: window.kind === "xy" ? $gettext("Spectra") : undefined,
        subtitle: subtitleOf(window),
        size: FIRST_SIZE,
        folded:
            window.kind === "xy" || window.kind === "chemical-imaging"
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
        kind: $gettext("Tool"),
        size: FIRST_SIZE,
        hides: false,
    }));
});
const gridSpecs = computed(() => [
    ...specs.value.filter((spec) => !hidden.value.includes(spec.id)),
    ...toolSpecs.value,
]);
const draftCount = computed(() =>
    tools.value.length > 0 &&
    (synthesis.status.value === "ready" || synthesis.status.value === "loading")
        ? synthesis.data.value?.unpublishedCount ?? 0
        : 0,
);
const offered = computed(() =>
    synthesis.status.value === "ready" && synthesis.data.value
        ? offeredTools(synthesis.data.value)
        : null,
);
/** The spectra each hidden XY window holds that it did not hold when hidden. */
const newSpectra = computed(() =>
    xyCurvesGained(
        [...hiddenFrom.value.values()],
        windows.value.filter((window) => hiddenFrom.value.has(window.id)),
    ),
);
const hiddenEntries = computed<HiddenWindowEntry[]>(() =>
    specs.value
        .filter((spec) => hidden.value.includes(spec.id))
        .map((spec) => ({
            id: spec.id,
            title: spec.title,
            added: newSpectra.value.get(spec.id) ?? 0,
        })),
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
                        "%{title}: %{n} spectrum added while the window was hidden.",
                        "%{title}: %{n} spectra added while the window was hidden.",
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
        case "chemical-imaging":
            return $gettext("Chemical imaging");
        case "micro":
            return $gettext("Micro-images");
        case "characterizations":
            return $gettext("Identified materials");
        case "not-in-chart":
            return $gettext("Without visualisation");
    }
}

/** What the window holds, counted. */
function subtitleOf(window: AutoWindow): string {
    let count: number;
    let message: string;
    switch (window.kind) {
        case "xy":
            count = window.curves.length;
            message = $ngettext("%{n} spectrum", "%{n} spectra", count);
            break;
        case "chemical-imaging":
            count = window.maps.length;
            message = $ngettext("%{n} map", "%{n} maps", count);
            break;
        case "micro":
            count = window.images.length;
            message = $ngettext("%{n} image", "%{n} images", count);
            break;
        case "characterizations":
            count = window.rows.length;
            message = $ngettext("%{n} material", "%{n} materials", count);
            break;
        default:
            count = window.entries.length;
            message = $ngettext("%{n} item", "%{n} items", count);
    }
    return interpolate(message, { n: count }, true);
}

function specTitle(id: string): string {
    return specs.value.find((spec) => spec.id === id)?.title ?? "";
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
        root.value?.querySelector<HTMLElement>(".hidden-windows-button") ??
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

async function showWindow({ id }: { id: string }): Promise<void> {
    setHidden(hidden.value.filter((entry) => entry !== id));
    await nextTick();
    windowElement(id)?.focus();
}

/** Opens a tool once; a tool already open takes the focus. */
/** Asks the folio image tools to show `canvas` and, when one is open, says so after the selection's count. */
function showFolio(canvas: string, label: string): void {
    folioAsked.value = { canvas, count: (folioAsked.value?.count ?? 0) + 1 };
    if (!store.compare.tools.some((tool) => tool.kind === "folio")) return;
    announce(
        interpolate(
            $gettext("%{summary}. %{message}"),
            {
                summary: linked.summary.value,
                message: interpolate(
                    $gettext("The folio image shows %{folio}."),
                    { folio: label },
                    true,
                ),
            },
            true,
        ),
    );
}

async function chooseTool({ kind }: { kind: ToolKind }): Promise<void> {
    const known = store.compare.tools.map((tool) => tool.id);
    const id = store.openTool(kind);
    if (!known.includes(id)) return;
    await nextTick();
    windowElement(id)?.focus();
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
            <WindowGrid
                v-if="specs.length > 0 || toolSpecs.length > 0"
                :windows="gridSpecs"
                :retained="hidden"
                @close="closeWindow"
            >
                <template #toolbar>
                    <SelectionIndicator />
                    <HiddenWindowsMenu
                        :windows="hiddenEntries"
                        @show="showWindow"
                    />
                    <ToolMenu
                        :offered="offered"
                        :status="synthesis.status.value"
                        @choose="chooseTool"
                        @retry="synthesis.retry"
                    />
                </template>
                <template #summary="{ window: spec, unfold }">
                    <FoldedSummary
                        v-if="summaries.get(spec.id)"
                        :summary="summaries.get(spec.id)!"
                        :title="spec.title"
                        @unfold="unfold"
                    />
                </template>
                <template #default="{ window: spec }">
                    <AutoWindowBody
                        v-if="windowById.get(spec.id)"
                        :window="windowById.get(spec.id)!"
                        :title="spec.title"
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

.compare-view .visually-hidden {
    position: absolute;
    inline-size: 0.0625rem;
    block-size: 0.0625rem;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
}
</style>
