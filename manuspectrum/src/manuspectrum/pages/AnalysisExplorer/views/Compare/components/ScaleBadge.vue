<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import HelpTip from "@/manuspectrum/pages/AnalysisExplorer/components/HelpTip.vue";

import {
    ICONS,
    ICON_VIEW_BOX,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";

import type { ServedSize } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/scale-notes.ts";

/**
 * « Different scale »: this image is not served at the size of the one it is
 * shown with (a linked pane, the other side of a curtain, the first layer of
 * a stack). The chip's description gives both served sizes.
 */
const props = withDefaults(
    defineProps<{
        size: ServedSize;
        against: ServedSize;
        placement?: "above" | "below";
        align?: "start" | "end";
    }>(),
    { placement: "below", align: "end" },
);

const { $gettext, interpolate } = useGettext();

const sizes = computed(() =>
    interpolate(
        $gettext(
            "%{width} × %{height} px against %{otherWidth} × %{otherHeight} px",
        ),
        {
            width: String(props.size.w),
            height: String(props.size.h),
            otherWidth: String(props.against.w),
            otherHeight: String(props.against.h),
        },
        true,
    ),
);
</script>

<template>
    <HelpTip
        class="scale-badge"
        :text="sizes"
        :placement="props.placement"
        :align="props.align"
    >
        <template #default="{ describedby }">
            <span
                class="scale-badge-chip"
                tabindex="0"
                :aria-describedby="describedby"
            >
                <svg
                    class="icon"
                    :viewBox="ICON_VIEW_BOX"
                    aria-hidden="true"
                    focusable="false"
                >
                    <path
                        v-for="(path, index) in ICONS['exclamation-triangle']"
                        :key="index"
                        :d="path"
                    />
                </svg>
                <span>{{ $gettext("Different scale") }}</span>
            </span>
        </template>
    </HelpTip>
</template>

<style scoped>
.scale-badge .scale-badge-chip {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding-block: 0.125rem;
    padding-inline: 0.5rem;
    border: 0.0625rem solid var(--heat-3);
    border-radius: 999rem;
    background: var(--heat-1);
    box-shadow: 0 0.0625rem 0.25rem rgb(0 0 0 / 30%);
    color: var(--ink);
    font: 500 0.65625rem var(--font-mono);
    white-space: nowrap;
}

.scale-badge .scale-badge-chip:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.0625rem;
}

.scale-badge .icon {
    inline-size: 0.75rem;
    block-size: 0.75rem;
    fill: currentColor;
}
</style>
