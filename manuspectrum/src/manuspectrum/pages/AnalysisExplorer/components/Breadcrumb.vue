<script setup lang="ts">
import { useGettext } from "vue3-gettext";

import {
    ICONS,
    ICON_VIEW_BOX,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";

export interface BreadcrumbItem {
    id: string;
    label: string;
}

/**
 * The trail from the whole corpus to the screen shown. Every item but the
 * last is a button that emits `go` with its id; the last one is the current
 * page.
 */
defineOptions({ name: "BreadcrumbTrail" });

defineProps<{ items: BreadcrumbItem[] }>();

const emit = defineEmits<{ (event: "go", id: string): void }>();

const { $gettext } = useGettext();

function go(id: string): void {
    emit("go", id);
}
</script>

<template>
    <nav
        class="breadcrumb"
        :aria-label="$gettext('Breadcrumb')"
    >
        <ol>
            <li
                v-for="(item, index) in items"
                :key="item.id"
            >
                <span
                    v-if="index === items.length - 1"
                    class="current"
                    aria-current="page"
                >
                    {{ item.label }}
                </span>
                <button
                    v-else
                    type="button"
                    class="step"
                    @click="go(item.id)"
                >
                    <span>{{ item.label }}</span>
                </button>
                <svg
                    v-if="index < items.length - 1"
                    class="separator"
                    :viewBox="ICON_VIEW_BOX"
                    aria-hidden="true"
                    focusable="false"
                >
                    <path
                        v-for="(path, pathIndex) in ICONS['chevron-right']"
                        :key="pathIndex"
                        :d="path"
                    />
                </svg>
            </li>
        </ol>
    </nav>
</template>

<style scoped>
.breadcrumb ol {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem;
    margin: 0;
    padding: 0;
    list-style: none;
    font-size: 0.8125rem;
}

.breadcrumb li {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
}

.breadcrumb .step {
    min-block-size: var(--explorer-target, 2.75rem);
    padding: 0;
    border: none;
    background: transparent;
    color: var(--blue-text);
    font: inherit;
    text-decoration: underline;
    cursor: pointer;
}

.breadcrumb .step:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.breadcrumb .current {
    color: var(--ink);
    font-weight: 600;
}

.breadcrumb .separator {
    inline-size: 0.75rem;
    block-size: 0.75rem;
    fill: var(--ink-muted);
}
</style>
