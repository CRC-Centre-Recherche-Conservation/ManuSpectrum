<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import { useItems } from "@/manuspectrum/pages/AnalysisExplorer/composables/useItems.ts";
import { BASKET_LIMIT } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type {
    Item,
    Label,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { SharedSelection } from "@/manuspectrum/pages/AnalysisExplorer/store/selection-link.ts";

const props = defineProps<{ selection: SharedSelection }>();
const emit = defineEmits<{ resolved: [message: string] }>();

const store = useExplorerStore();
const { $gettext, $ngettext, interpolate } = useGettext();
const { data: itemsData } = useItems(() => props.selection.keys);

const heading = computed(() =>
    interpolate(
        $ngettext(
            "A shared Selection of %{n} item",
            "A shared Selection of %{n} items",
            props.selection.keys.length,
        ),
        { n: props.selection.keys.length },
        true,
    ),
);
const truncatedNotice = computed(() =>
    interpolate(
        $ngettext(
            "Only the first %{limit} items were kept; %{n} more was left out.",
            "Only the first %{limit} items were kept; %{n} more were left out.",
            props.selection.truncated,
        ),
        { n: props.selection.truncated, limit: BASKET_LIMIT },
        true,
    ),
);
const missingCount = computed(() => itemsData.value?.missing.length ?? 0);
const missingNotice = computed(() =>
    interpolate(
        $ngettext(
            "%{n} item is no longer available.",
            "%{n} items are no longer available.",
            missingCount.value,
        ),
        { n: missingCount.value },
        true,
    ),
);

/** The shared keys, less those the items API reported missing; every key while that answer is not in. */
function availableKeys(): string[] {
    const missing = new Set(itemsData.value?.missing ?? []);
    return props.selection.keys.filter((key) => !missing.has(key));
}

function itemName(item: Item): Label {
    if (item.kind === "characterization") {
        return item.characterization.name;
    }
    if (item.kind === "analysis") {
        return item.analysis.name;
    }
    return {
        value: `${item.analysis.name.value} · ${item.file.name}`,
        lang: item.analysis.name.lang,
    };
}

function replace(): void {
    const result = store.replaceBasket(availableKeys());
    emit(
        "resolved",
        interpolate(
            $ngettext(
                "Your Selection now holds the %{n} shared item.",
                "Your Selection now holds the %{n} shared items.",
                result.kept.length,
            ),
            { n: result.kept.length },
            true,
        ),
    );
}

/** Two complete translated sentences, joined with a space when some keys did not fit. */
function merge(): void {
    const result = store.mergeBasket(availableKeys());
    const added = interpolate(
        $ngettext("%{n} item added.", "%{n} items added.", result.kept.length),
        { n: result.kept.length },
        true,
    );
    if (result.truncated === 0) {
        emit("resolved", added);
        return;
    }
    const refused = interpolate(
        $ngettext(
            "%{n} item could not be added: the Selection is full (%{limit}).",
            "%{n} items could not be added: the Selection is full (%{limit}).",
            result.truncated,
        ),
        { n: result.truncated, limit: BASKET_LIMIT },
        true,
    );
    emit("resolved", `${added} ${refused}`);
}

function dismiss(): void {
    emit("resolved", "");
}
</script>

<template>
    <section
        class="shared-selection"
        aria-labelledby="shared-selection-title"
    >
        <h2
            id="shared-selection-title"
            class="title"
        >
            <span>{{ heading }}</span>
        </h2>
        <p
            v-if="props.selection.truncated > 0"
            class="notice"
        >
            <span>{{ truncatedNotice }}</span>
        </p>
        <ul
            v-if="itemsData"
            class="items"
        >
            <li
                v-for="item in itemsData.items"
                :key="item.key"
                :lang="itemName(item).lang"
            >
                <span>{{ itemName(item).value }}</span>
            </li>
        </ul>
        <p
            v-if="missingCount > 0"
            class="notice"
        >
            <span>{{ missingNotice }}</span>
        </p>
        <div class="actions">
            <button
                type="button"
                class="replace"
                @click="replace"
            >
                <span>{{ $gettext("Replace my Selection") }}</span>
            </button>
            <button
                type="button"
                class="merge"
                @click="merge"
            >
                <span>{{ $gettext("Merge into my Selection") }}</span>
            </button>
            <button
                type="button"
                class="dismiss"
                @click="dismiss"
            >
                <span>{{ $gettext("Ignore") }}</span>
            </button>
        </div>
    </section>
</template>

<style scoped>
.shared-selection {
    display: grid;
    gap: 0.75rem;
    padding: 1.25rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.75rem;
    background: var(--surface);
}

.shared-selection .title {
    font-family: var(--font-display);
    font-size: 1.375rem;
    font-weight: 500;
}

.shared-selection .items {
    display: grid;
    gap: 0.25rem;
    padding-inline-start: 1.25rem;
}

.shared-selection .notice {
    color: var(--ink-muted);
    font-size: 0.875rem;
}

.shared-selection .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
}

.shared-selection .actions button {
    min-block-size: 2.75rem;
    padding-inline: 1rem;
    border: 0.0625rem solid var(--ink);
    border-radius: 999rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.shared-selection .actions .replace {
    background: var(--ink);
    color: var(--surface);
}

.shared-selection .actions button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
