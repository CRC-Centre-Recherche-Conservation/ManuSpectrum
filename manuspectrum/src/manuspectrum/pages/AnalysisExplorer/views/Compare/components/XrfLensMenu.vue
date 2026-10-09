<script setup lang="ts">
import { computed, nextTick, useId, useTemplateRef, watch } from "vue";
import { useGettext } from "vue3-gettext";

import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";

import { useAnchoredPopover } from "@/manuspectrum/pages/AnalysisExplorer/composables/useAnchoredPopover.ts";
import { useMenuButton } from "@/manuspectrum/pages/AnalysisExplorer/composables/useMenuButton.ts";
import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import {
    XRF_ANODES,
    XRF_DETECTORS,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layout.ts";

import type {
    AnodeRow,
    LayerCounts,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useXrfLens.ts";
import type {
    XrfAnode,
    XrfDetector,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layout.ts";

type LayerName = "declared" | "instrument" | "overlaps";

const LAYER_NAMES: readonly LayerName[] = [
    "declared",
    "instrument",
    "overlaps",
];
const UNKNOWN_ANODE = "";
const NO_TUBE = "none";

/**
 * « XRF lens settings »: an icon button opening a popover (`data-popover`,
 * so Escape closes it and leaves the focus alone; `useMenuButton` holds its
 * state, the focus return and the click outside; `useAnchoredPopover` puts
 * it in the top layer under the button). It holds the layer
 * toggles (declared elements, instrument peaks, overlaps), the detector
 * resolution, the tube anode of each analysis of the window (the one the
 * conditions gave, shown as such, else a select) and the line table's
 * attribution. A choice emits and leaves the popover open.
 */
const props = defineProps<{
    declared: boolean;
    instrument: boolean;
    overlaps: boolean;
    detector: XrfDetector;
    /** What each layer draws on the window; a layer with nothing says so. */
    counts: LayerCounts;
    anodes: readonly AnodeRow[];
    /** The version of the line table, for the attribution; empty while it loads. */
    version: string;
}>();

const emit = defineEmits<{
    (event: "update-layer", payload: { name: LayerName; value: boolean }): void;
    (event: "update-detector", payload: { detector: XrfDetector }): void;
    (
        event: "update-anode",
        payload: { analysis: string; anode: XrfAnode | "none" | null },
    ): void;
}>();

const { $gettext, interpolate } = useGettext();

const panelId = useId();
const root = useTemplateRef<HTMLElement>("root");
const trigger = useTemplateRef<InstanceType<typeof IconButton>>("trigger");
const panel = useTemplateRef<HTMLElement>("panel");
const button = computed<HTMLButtonElement | null>(
    () => trigger.value?.element ?? null,
);
const { expanded, closeMenu, toggle } = useMenuButton(root, button);
const { style: panelStyle } = useAnchoredPopover(expanded, panel, button);

const layerLabels = computed<Record<LayerName, string>>(() => ({
    declared: $gettext("Declared elements"),
    instrument: $gettext("Instrument peaks"),
    overlaps: $gettext("Overlaps"),
}));
const layerValues = computed<Record<LayerName, boolean>>(() => ({
    declared: props.declared,
    instrument: props.instrument,
    overlaps: props.overlaps,
}));
const detectorLabels = computed<Record<XrfDetector, string>>(() => ({
    sdd: $gettext("SDD (≈ 140 eV at Mn Kα)"),
    "si-pin": $gettext("Si-PIN (≈ 180 eV at Mn Kα)"),
}));
const attribution = computed(() =>
    interpolate(
        $gettext("Lines: XrayDB %{version} (CC0), Elam, Ravel & Sieber 2002"),
        { version: props.version },
        true,
    ),
);

watch(expanded, async (open) => {
    if (!open) return;
    await nextTick();
    panel.value?.querySelector<HTMLElement>("input, select, button")?.focus();
});

function inferredText(anode: string): string {
    return interpolate(
        $gettext("%{anode}, inferred from the conditions"),
        { anode },
        true,
    );
}

function rowLabel(row: AnodeRow): string {
    return `${slotLabel(row.slot)} · ${row.name}`;
}

function onLayer(name: LayerName, event: Event): void {
    emit("update-layer", {
        name,
        value: (event.target as HTMLInputElement).checked,
    });
}

function onDetector(event: Event): void {
    const detector = XRF_DETECTORS.find(
        (name) => name === (event.target as HTMLSelectElement).value,
    );
    if (detector) emit("update-detector", { detector });
}

function onAnode(analysis: string, event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    const anode =
        value === NO_TUBE
            ? NO_TUBE
            : XRF_ANODES.find((name) => name === value) ?? null;
    emit("update-anode", { analysis, anode });
}

function onKeydown(event: KeyboardEvent): void {
    if (event.key !== "Escape") return;
    event.preventDefault();
    closeMenu(true);
}
</script>

<template>
    <div
        ref="root"
        class="xrf-lens-menu"
    >
        <IconButton
            ref="trigger"
            icon="sliders-h"
            data-action="xrf-settings"
            data-popover="xrf-settings"
            aria-haspopup="dialog"
            :aria-expanded="expanded ? 'true' : 'false'"
            :aria-controls="expanded ? panelId : undefined"
            :label="$gettext('XRF lens settings')"
            tip-placement="below"
            tip-align="start"
            @click="toggle"
        />
        <div
            v-if="expanded"
            :id="panelId"
            ref="panel"
            popover="manual"
            class="panel"
            :style="panelStyle"
            role="dialog"
            :aria-label="$gettext('XRF lens settings')"
            @keydown="onKeydown"
        >
            <div
                class="section"
                role="group"
                :aria-label="$gettext('Layers')"
            >
                <label
                    v-for="name in LAYER_NAMES"
                    :key="name"
                    class="choice"
                >
                    <input
                        type="checkbox"
                        :data-layer="name"
                        :checked="layerValues[name]"
                        @change="onLayer(name, $event)"
                    />
                    <span>{{ layerLabels[name] }}</span>
                    <span
                        class="count"
                        :data-empty="counts[name] === 0 ? 'true' : undefined"
                        >{{
                            counts[name] === 0
                                ? $gettext("(none)")
                                : `(${counts[name]})`
                        }}</span
                    >
                </label>
            </div>
            <label class="choice stacked">
                <span>{{ $gettext("Detector resolution") }}</span>
                <select
                    data-field="detector"
                    :value="detector"
                    @change="onDetector"
                >
                    <option
                        v-for="name in XRF_DETECTORS"
                        :key="name"
                        :value="name"
                    >
                        {{ detectorLabels[name] }}
                    </option>
                </select>
            </label>
            <div
                v-if="anodes.length > 0"
                class="section"
                role="group"
                :aria-label="$gettext('Tube anode')"
            >
                <template
                    v-for="row in anodes"
                    :key="row.analysis"
                >
                    <p
                        v-if="row.inferred"
                        class="choice inferred"
                        :data-analysis="row.analysis"
                    >
                        <span>{{ rowLabel(row) }}</span>
                        <span>{{ inferredText(row.inferred) }}</span>
                    </p>
                    <label
                        v-else
                        class="choice stacked"
                    >
                        <span>{{ rowLabel(row) }}</span>
                        <select
                            :data-analysis="row.analysis"
                            :value="row.chosen ?? UNKNOWN_ANODE"
                            @change="onAnode(row.analysis, $event)"
                        >
                            <option :value="UNKNOWN_ANODE">
                                {{ $gettext("Unknown") }}
                            </option>
                            <option
                                v-for="anode in XRF_ANODES"
                                :key="anode"
                                :value="anode"
                            >
                                {{ anode }}
                            </option>
                            <option :value="NO_TUBE">
                                {{ $gettext("None (no tube)") }}
                            </option>
                        </select>
                    </label>
                </template>
            </div>
            <p
                v-if="version !== ''"
                class="attribution"
            >
                <span>{{ attribution }}</span>
            </p>
        </div>
    </div>
</template>

<style scoped>
.xrf-lens-menu {
    position: relative;
}

.xrf-lens-menu .panel {
    position: fixed;
    inset: auto;
    display: grid;
    gap: 0.5rem;
    min-inline-size: 16rem;
    max-inline-size: min(22rem, calc(100vw - 1rem));
    overflow-y: auto;
    margin: 0;
    padding: 0.5rem 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    box-shadow: 0 0.25rem 1rem color-mix(in srgb, var(--ink) 15%, transparent);
    font-size: 0.8125rem;
    color: var(--ink);
}

.xrf-lens-menu .section {
    display: grid;
    gap: 0.25rem;
}

.xrf-lens-menu .choice {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    min-block-size: 1.75rem;
}

.xrf-lens-menu .choice .count {
    color: var(--ink-muted);
    font-variant-numeric: tabular-nums;
}

.xrf-lens-menu .choice .count[data-empty] {
    font-style: italic;
}

.xrf-lens-menu .choice.stacked {
    flex-direction: column;
    align-items: stretch;
    gap: 0.125rem;
}

.xrf-lens-menu .inferred {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.125rem;
    margin: 0;
}

.xrf-lens-menu .inferred span:last-child {
    color: var(--ink-muted);
}

.xrf-lens-menu select {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
}

.xrf-lens-menu .attribution {
    margin: 0;
    color: var(--ink-muted);
    font-size: 0.75rem;
}

.xrf-lens-menu input:focus-visible,
.xrf-lens-menu select:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
