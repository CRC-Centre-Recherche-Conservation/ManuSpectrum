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
const props = defineProps<{
    size: ServedSize;
    against: ServedSize;
}>();

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
    ),
);
</script>

<template>
    <HelpTip
        class="scale-badge"
        :text="sizes"
        placement="below"
        align="end"
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
    border-radius: 0.75rem;
    background: var(--heat-1);
    color: var(--ink);
    font-size: 0.75rem;
    font-weight: 600;
}

.scale-badge .scale-badge-chip:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.0625rem;
}

.scale-badge .icon {
    inline-size: 0.875rem;
    block-size: 0.875rem;
    fill: currentColor;
}
</style>
