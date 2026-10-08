<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import HelpTip from "@/manuspectrum/pages/AnalysisExplorer/components/HelpTip.vue";

import { CUSTOM_RANGE } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/lens-range.ts";
import { RANGE_PRESETS } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/workshop.ts";

type Scale = "linear" | "log";

/**
 * The XRF row of an XY window's toolbar: the Y scale (a `Lin | Log` switch,
 * Log unavailable in the Offset layout, said in a tooltip), the energy range
 * (a segmented group of the presets, not a select; « Custom » once the reader zoomed by hand), and
 * two slots for the controls of the lens that carry their own state: the
 * settings menu and the peak identifier toggle.
 */
const props = defineProps<{
    log: boolean;
    logDisabled: boolean;
    /** A preset key (`RANGE_PRESETS`) or `CUSTOM_RANGE`. */
    range: string;
}>();

const emit = defineEmits<{
    (event: "update-log", payload: { log: boolean }): void;
    (event: "update-range", payload: { key: string }): void;
}>();

const { $gettext, interpolate } = useGettext();

const scaleLabels = computed<Record<Scale, string>>(() => ({
    linear: $gettext("Linear"),
    log: $gettext("Log"),
}));
const ranges = computed(() => [
    ...RANGE_PRESETS.map((preset) => ({
        key: preset.key,
        label: preset.range
            ? interpolate(
                  $gettext("%{from}–%{to} keV"),
                  {
                      from: String(preset.range[0]),
                      to: String(preset.range[1]),
                  },
                  true,
              )
            : $gettext("Full range"),
    })),
    ...(props.range === CUSTOM_RANGE
        ? [{ key: CUSTOM_RANGE, label: $gettext("Custom") }]
        : []),
]);

function pressed(scale: Scale): "true" | "false" {
    return (scale === "log") === (props.log && !props.logDisabled)
        ? "true"
        : "false";
}

function chooseScale(scale: Scale): void {
    if (scale === "log" && props.logDisabled) return;
    emit("update-log", { log: scale === "log" });
}

function chooseRange(key: string): void {
    if (key !== CUSTOM_RANGE) emit("update-range", { key });
}
</script>

<template>
    <div
        class="xrf-lens-controls"
        role="group"
        :aria-label="$gettext('XRF lens')"
    >
        <span
            class="segmented"
            role="group"
            :aria-label="$gettext('Log scale')"
        >
            <button
                type="button"
                data-scale="linear"
                :aria-pressed="pressed('linear')"
                @click="chooseScale('linear')"
            >
                <span>{{ scaleLabels.linear }}</span>
            </button>
            <HelpTip
                v-if="logDisabled"
                :text="$gettext('Not available with Offset')"
                placement="below"
            >
                <template #default="{ describedby }">
                    <button
                        type="button"
                        data-scale="log"
                        aria-disabled="true"
                        :aria-pressed="pressed('log')"
                        :aria-describedby="describedby"
                    >
                        <span>{{ scaleLabels.log }}</span>
                    </button>
                </template>
            </HelpTip>
            <button
                v-else
                type="button"
                data-scale="log"
                :aria-pressed="pressed('log')"
                @click="chooseScale('log')"
            >
                <span>{{ scaleLabels.log }}</span>
            </button>
        </span>
        <span
            class="segmented"
            role="group"
            :aria-label="$gettext('Energy range')"
        >
            <button
                v-for="entry in ranges"
                :key="entry.key"
                type="button"
                :data-range="entry.key"
                :aria-pressed="range === entry.key ? 'true' : 'false'"
                :aria-disabled="entry.key === CUSTOM_RANGE ? 'true' : undefined"
                @click="chooseRange(entry.key)"
            >
                <span>{{ entry.label }}</span>
            </button>
        </span>
        <slot name="settings"></slot>
        <slot name="identify"></slot>
    </div>
</template>

<style scoped>
.xrf-lens-controls {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem 0.5rem;
}

.xrf-lens-controls .segmented {
    display: inline-flex;
    padding: 0.1875rem;
    border-radius: 999rem;
    background: var(--bg-alt);
    box-shadow: inset 0 0 0 0.0625rem var(--border);
}

.xrf-lens-controls .segmented button {
    min-block-size: 1.75rem;
    padding-inline: 0.75rem;
    border: none;
    border-radius: 999rem;
    background: none;
    color: var(--ink-muted);
    font: inherit;
    font-size: 0.78125rem;
    white-space: nowrap;
    cursor: pointer;
    transition:
        background-color var(--dur-fast, 160ms),
        color var(--dur-fast, 160ms);
}

.xrf-lens-controls .segmented button:hover {
    color: var(--ink);
}

.xrf-lens-controls .segmented button[aria-pressed="true"] {
    background: var(--surface);
    box-shadow:
        0 0.0625rem 0.125rem rgb(26 26 46 / 0.08),
        inset 0 0 0 0.0625rem var(--seg-on-rule);
    color: var(--seg-on-ink);
    font-weight: 600;
}

.xrf-lens-controls .segmented button[aria-disabled="true"] {
    color: var(--ink-dim);
    cursor: default;
}

.xrf-lens-controls .segmented button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
