<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import Slider from "primevue/slider";

/**
 * The layer scroll of D47: a slider over `labels` in their order, one tick
 * per layer, the first and last labels at its ends, the handle's place said
 * in words (« 550 nm, layer 4 of 13 »). Keyboard: the slider's arrows,
 * Home and End.
 */
const props = defineProps<{
    labels: readonly string[];
    position: number;
}>();

const emit = defineEmits<{
    (event: "update:position", position: number): void;
}>();

const { $gettext, interpolate } = useGettext();

const current = computed(() => props.labels[props.position] ?? null);
const valueText = computed(() =>
    current.value === null
        ? ""
        : interpolate(
              $gettext("%{label}, layer %{n} of %{total}"),
              {
                  label: current.value,
                  n: props.position + 1,
                  total: props.labels.length,
              },
              true,
          ),
);
const scrollLabel = computed(() =>
    current.value === null
        ? $gettext("Layers, in order")
        : interpolate(
              $gettext("Layers, in order: %{label}"),
              { label: current.value },
              true,
          ),
);

function moveTo(value: number | number[]): void {
    emit("update:position", Array.isArray(value) ? value[0] : value);
}
</script>

<template>
    <div class="scroll">
        <span aria-hidden="true">{{ $gettext("Layers, in order") }}</span>
        <Slider
            :model-value="props.position"
            :min="0"
            :max="props.labels.length - 1"
            :step="1"
            :aria-label="scrollLabel"
            :pt="{ handle: { 'aria-valuetext': valueText } }"
            @update:model-value="moveTo"
        />
        <span
            class="ticks"
            aria-hidden="true"
        >
            <span
                v-for="(label, index) in props.labels"
                :key="`${index}:${label}`"
                class="tick"
            ></span>
        </span>
        <span
            class="ends"
            aria-hidden="true"
        >
            <span>{{ props.labels[0] }}</span>
            <span>{{ props.labels.at(-1) }}</span>
        </span>
    </div>
</template>

<style scoped>
.scroll {
    display: grid;
    gap: 0.5rem;
    padding-inline: 0.625rem;
}

.scroll .ticks {
    display: flex;
    justify-content: space-between;
}

.scroll .tick {
    inline-size: 0.0625rem;
    block-size: 0.375rem;
    background: var(--border-hover);
}

.scroll .ends {
    display: flex;
    justify-content: space-between;
    gap: 1rem;
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-size: 0.6875rem;
}
</style>
