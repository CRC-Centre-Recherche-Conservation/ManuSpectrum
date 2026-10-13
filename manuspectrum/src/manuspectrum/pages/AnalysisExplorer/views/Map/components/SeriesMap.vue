<script setup lang="ts">
import { computed } from "vue";

import { focusHue } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";
import {
    project,
    wrapInto,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";
import { snapshotFrame } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/multiples.ts";

import type { Bounds } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";
import type {
    MapSnapshot,
    MiniDot,
    MiniMap,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/multiples.ts";

const DOT_BASE = 4;
const DOT_STEP = 3;
const PIP_RADIUS = 5;
const PIP_GAP = 11;

/**
 * The drawing of one map of the series in a `width`×`height` box: the
 * land, the snapshot laid where its bounds fall in `bounds` (`snapshotFrame`)
 * or a sea frame without one, and the dots projected in the same box
 * (`project`), so that they sit on their places at any size. A dot keeps its
 * radius in box units: the mini map scales it with the box, the enlarged map
 * draws it at its own size. A material map is hollow where the material is
 * not attested, pale in its hue on low-certainty ground only, dashed on an
 * attributed place; a century map draws a pip per followed slot attested.
 * `followedSlot` is the followed slot of a material map, if any.
 */
const props = defineProps<{
    map: MiniMap;
    bounds: Bounds;
    background: MapSnapshot | null;
    width: number;
    height: number;
    followedSlot: number | null;
}>();

const viewBox = computed(() => `0 0 ${props.width} ${props.height}`);
const frame = computed(() =>
    props.background
        ? snapshotFrame(
              props.background,
              props.bounds,
              props.width,
              props.height,
          )
        : null,
);
const dotStyle = computed<Record<string, string>>(() => {
    const style: Record<string, string> = {};
    if (props.followedSlot !== null) {
        style["--h"] = focusHue(props.followedSlot);
    }
    return style;
});

function at(entry: MiniDot): [number, number] {
    const [x, y] = project(
        wrapInto(entry.lngLat, props.bounds),
        props.bounds,
        props.width,
        props.height,
    );
    return [Math.round(x * 10) / 10, Math.round(y * 10) / 10];
}

function radiusOf(entry: MiniDot): number {
    return entry.attested ? DOT_BASE + entry.size * DOT_STEP : DOT_BASE;
}

function dotClass(entry: MiniDot): Record<string, boolean> {
    return {
        attested: entry.attested,
        absent: !entry.attested,
        pale: entry.attested && entry.pale,
        dashed: entry.dashed,
    };
}

/** Pips by century: in a row centred on the place. */
function pipsOf(entry: MiniDot): { slot: number; x: number; y: number }[] {
    const [x, y] = at(entry);
    const first = x - ((entry.slots.length - 1) * PIP_GAP) / 2;
    return entry.slots.map((slot, index) => ({
        slot,
        x: first + index * PIP_GAP,
        y,
    }));
}

function byCenturyPips(entry: MiniDot): boolean {
    return props.map.century !== null && entry.slots.length > 0;
}
</script>

<template>
    <svg
        class="series-map"
        aria-hidden="true"
        focusable="false"
        :viewBox="viewBox"
    >
        <rect
            class="land"
            :width="props.width"
            :height="props.height"
        />
        <image
            v-if="props.background && frame"
            :key="props.background.url"
            class="snapshot"
            preserveAspectRatio="none"
            :href="props.background.url"
            :x="frame.x"
            :y="frame.y"
            :width="frame.width"
            :height="frame.height"
        />
        <rect
            v-else
            class="sea-frame"
            x="1"
            y="1"
            :width="props.width - 2"
            :height="props.height - 2"
        />
        <g
            v-for="entry in props.map.dots"
            :key="entry.id"
        >
            <g v-if="byCenturyPips(entry)">
                <circle
                    v-for="pip in pipsOf(entry)"
                    :key="pip.slot"
                    class="pip"
                    :cx="pip.x"
                    :cy="pip.y"
                    :r="PIP_RADIUS"
                    :style="{ '--h': focusHue(pip.slot) }"
                />
            </g>
            <circle
                v-else
                class="dot"
                :class="dotClass(entry)"
                :cx="at(entry)[0]"
                :cy="at(entry)[1]"
                :r="radiusOf(entry)"
                :style="dotStyle"
            />
        </g>
    </svg>
</template>

<style scoped>
.series-map {
    display: block;
    overflow: hidden;
    inline-size: 100%;
    block-size: auto;
}

.series-map .snapshot {
    animation: series-map-fade var(--dur-med) var(--ease-out-expo);
}

.series-map .land {
    fill: var(--map-land);
}

.series-map .sea-frame {
    fill: none;
    stroke: var(--map-sea);
    stroke-width: 2;
}

.series-map .dot.attested {
    fill: var(--h, var(--ink));
    stroke: var(--bg);
    stroke-width: 1;
}

.series-map .dot.pale {
    fill: var(--surface);
    stroke: var(--h, var(--ink));
    stroke-width: 1.5;
}

.series-map .dot.absent {
    fill: none;
    stroke: var(--series-context);
    stroke-width: 1;
}

/* The main map's dashed ring of an attributed place */
.series-map .dot.dashed {
    stroke-dasharray: 2 1.5;
}

.series-map .dot.attested.dashed:not(.pale) {
    stroke: var(--series-context);
}

.series-map .pip {
    fill: var(--h);
    stroke: var(--surface);
    stroke-width: 1;
}

@keyframes series-map-fade {
    from {
        opacity: 0;
    }

    to {
        opacity: 1;
    }
}

@media (prefers-reduced-motion: reduce) {
    .series-map .snapshot {
        animation: none;
    }
}
</style>
