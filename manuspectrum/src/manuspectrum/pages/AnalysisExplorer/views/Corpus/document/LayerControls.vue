<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import Slider from "primevue/slider";

import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";

import { useAnchoredPopover } from "@/manuspectrum/pages/AnalysisExplorer/composables/useAnchoredPopover.ts";
import { nextId } from "@/manuspectrum/pages/AnalysisExplorer/folio/roving.ts";

import type { FolioOverlay } from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";

const PERCENT = 100;
const OPACITY_STEP = 5;
const BUTTON_COUNT = 7;
const OPACITY_INDEX = 3;
const ROVING_KEYS = new Set([
    "ArrowLeft",
    "ArrowRight",
    "ArrowUp",
    "ArrowDown",
    "Home",
    "End",
]);
const STOPS = Array.from({ length: BUTTON_COUNT }, (_, index) => String(index));

/**
 * The controls of one layer laid on the folio, in one toolbar (arrow keys
 * move between the buttons, one tab stop): adjust (toggle), turn left and
 * right, opacity (a slider in a popover), curtain (toggle), capture and
 * reset. The bar changes nothing itself; each control is an event.
 */
const props = withDefaults(
    defineProps<{
        overlay: FolioOverlay;
        adjusting: boolean;
        underCurtain: boolean;
        capturing: boolean;
        /** False when the folio has no image service to take a capture from. */
        canCapture?: boolean;
        /** True while a turn is being checked with the image server. */
        turning?: boolean;
    }>(),
    { canCapture: true, turning: false },
);

const emit = defineEmits<{
    adjust: [on: boolean];
    turn: [by: 1 | -1];
    opacity: [value: number];
    curtain: [on: boolean];
    capture: [];
    reset: [];
}>();

const { $gettext, interpolate } = useGettext();
const root = useTemplateRef<HTMLElement>("root");
const popover = useTemplateRef<HTMLElement>("popover");
const opacityButton = useTemplateRef<{ element: HTMLButtonElement | null }>(
    "opacity-button",
);

const stop = ref(0);
const opacityOpen = ref(false);

const anchor = computed(() => opacityButton.value?.element ?? null);
const { style: popoverStyle } = useAnchoredPopover(
    opacityOpen,
    popover,
    anchor,
    { prefer: "below", align: "end", onLost: closeOpacity },
);

const toolbarName = computed(() =>
    interpolate(
        $gettext("Layer on the page: %{label}"),
        { label: props.overlay.label },
        true,
    ),
);
const noTurn = computed(() =>
    props.overlay.canTurn
        ? ""
        : $gettext("This layer has no image service: it cannot turn"),
);
const noCapture = computed(() =>
    props.canCapture
        ? ""
        : $gettext("This folio has no image service: it cannot be captured."),
);
const opacityPercent = computed(() =>
    Math.round(props.overlay.opacity * PERCENT),
);

onBeforeUnmount(stopListening);

function buttons(): HTMLButtonElement[] {
    return [...(root.value?.querySelectorAll("button") ?? [])];
}

function onFocusin(event: FocusEvent): void {
    const index = buttons().indexOf(event.target as HTMLButtonElement);
    if (index >= 0) stop.value = index;
}

function onKeydown(event: KeyboardEvent): void {
    if (event.key === "Escape" && opacityOpen.value) {
        event.stopPropagation();
        closeOpacity();
        anchor.value?.focus();
        return;
    }
    if (!ROVING_KEYS.has(event.key)) return;
    if (!(event.target instanceof HTMLButtonElement)) return;
    const next = nextId(STOPS, String(stop.value), event.key);
    if (next === null) return;
    event.preventDefault();
    stop.value = Number(next);
    buttons()[stop.value]?.focus();
}

function onOpacityPointerDown(event: PointerEvent): void {
    const target = event.target as Node;
    if (popover.value?.contains(target) || anchor.value?.contains(target)) {
        return;
    }
    closeOpacity();
}

function stopListening(): void {
    document.removeEventListener("pointerdown", onOpacityPointerDown);
}

function closeOpacity(): void {
    opacityOpen.value = false;
    stopListening();
}

async function toggleOpacity(): Promise<void> {
    if (opacityOpen.value) {
        closeOpacity();
        return;
    }
    opacityOpen.value = true;
    document.addEventListener("pointerdown", onOpacityPointerDown);
    await nextTick();
}

function onOpacity(value: number | number[]): void {
    emit("opacity", (Array.isArray(value) ? value[0] : value) / PERCENT);
}

function tabindexOf(index: number): number {
    return index === stop.value ? 0 : -1;
}
</script>

<template>
    <div
        ref="root"
        class="layer-controls"
        role="toolbar"
        :aria-label="toolbarName"
        @focusin="onFocusin"
        @keydown="onKeydown"
    >
        <IconButton
            icon="arrows-alt"
            data-action="adjust"
            :label="$gettext('Adjust the layer')"
            :pressed="props.adjusting"
            :tabindex="tabindexOf(0)"
            tip-placement="below"
            @click="emit('adjust', !props.adjusting)"
        />
        <IconButton
            icon="replay"
            data-action="turn-left"
            :label="$gettext('Turn left')"
            :description="noTurn"
            :disabled="!props.overlay.canTurn || props.turning"
            :tabindex="tabindexOf(1)"
            @click="emit('turn', -1)"
        />
        <IconButton
            icon="refresh"
            data-action="turn-right"
            :label="$gettext('Turn right')"
            :description="noTurn"
            :disabled="!props.overlay.canTurn || props.turning"
            :tabindex="tabindexOf(2)"
            @click="emit('turn', 1)"
        />
        <IconButton
            ref="opacity-button"
            icon="sun"
            data-action="opacity"
            data-popover="opacity"
            :label="$gettext('Opacity')"
            :aria-expanded="opacityOpen ? 'true' : 'false'"
            :tabindex="tabindexOf(OPACITY_INDEX)"
            @click="toggleOpacity"
        />
        <IconButton
            icon="clone"
            data-action="curtain"
            :label="$gettext('Curtain: compare with the page')"
            :pressed="props.underCurtain"
            :tabindex="tabindexOf(4)"
            @click="emit('curtain', !props.underCurtain)"
        />
        <IconButton
            icon="camera"
            data-action="capture"
            :label="$gettext('Capture the folio under the layer')"
            :description="noCapture"
            :disabled="props.capturing || !props.canCapture"
            :tabindex="tabindexOf(5)"
            @click="emit('capture')"
        />
        <IconButton
            icon="history"
            data-action="reset"
            :label="$gettext('Reset the position')"
            :disabled="!props.overlay.registered"
            :tabindex="tabindexOf(6)"
            @click="emit('reset')"
        />
        <div
            v-if="opacityOpen"
            ref="popover"
            class="opacity-popover"
            popover="manual"
            role="group"
            :aria-label="$gettext('Opacity')"
            :style="popoverStyle"
        >
            <Slider
                :model-value="opacityPercent"
                :min="0"
                :max="PERCENT"
                :step="OPACITY_STEP"
                :aria-label="$gettext('Opacity')"
                @update:model-value="onOpacity"
            />
        </div>
    </div>
</template>

<style scoped>
.layer-controls {
    display: flex;
    gap: 0.125rem;
    padding: 0.125rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.5rem;
    background: var(--surface);
    box-shadow: var(--shadow-md);
}

.layer-controls .opacity-popover {
    inline-size: 12rem;
    margin: 0;
    padding: 0.75rem 1rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.5rem;
    background: var(--surface);
    color: var(--ink);
}
</style>
