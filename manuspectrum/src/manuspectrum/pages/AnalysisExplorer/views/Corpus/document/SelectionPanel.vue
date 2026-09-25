<script setup lang="ts">
import { computed } from "vue";
import { useGettext } from "vue3-gettext";

import { useItems } from "@/manuspectrum/pages/AnalysisExplorer/composables/useItems.ts";
import { useVocabulary } from "@/manuspectrum/pages/AnalysisExplorer/composables/useVocabulary.ts";
import {
    BASKET_LIMIT,
    slotLabel,
} from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { isViewAvailable } from "@/manuspectrum/pages/AnalysisExplorer/views/registry.ts";

import type {
    Item,
    Label,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const store = useExplorerStore();
const { $gettext, interpolate } = useGettext();
const { dataKindBadge } = useVocabulary();
const items = useItems(() => store.basket.map((item) => item.key));

const byKey = computed(
    () =>
        new Map(
            (items.data.value?.items ?? []).map((item) => [item.key, item]),
        ),
);
const missing = computed(() => new Set(items.data.value?.missing ?? []));
const rows = computed(() => [...store.basket].sort((a, b) => a.slot - b.slot));
const canCompare = computed(() => isViewAvailable("compare"));

function kindText(item: Item): string {
    if (item.kind === "characterization")
        return $gettext("identified material");
    if (item.kind === "imaging") return $gettext("map layer");
    return dataKindBadge(item.file.dataKind);
}

function titleOf(item: Item): Label {
    if (item.kind === "characterization") return item.characterization.name;
    if (item.kind === "imaging") {
        const index = Number(item.key.split(":")[2]);
        const layer = item.file.layers.find((entry) => entry.index === index);
        return {
            value: `${item.analysis.name.value}${layer ? ` · ${layer.label}` : ""}`,
            lang: item.analysis.name.lang,
        };
    }
    return item.analysis.name;
}

function documentOf(item: Item): Label | null {
    return item.kind === "characterization"
        ? null
        : item.analysis.document.name;
}

function removeLabel(slot: number): string {
    return interpolate(
        $gettext("Remove %{slot}"),
        { slot: slotLabel(slot) },
        true,
    );
}
</script>

<template>
    <section
        class="selection-panel"
        aria-labelledby="selection-title"
    >
        <h3 id="selection-title">
            <span>{{ $gettext("Selection") }}</span>
            <span class="count"
                >{{ store.basket.length }} / {{ BASKET_LIMIT }}</span
            >
        </h3>
        <p
            v-if="store.basket.length === 0"
            class="empty"
        >
            <span>
                {{
                    $gettext(
                        "Your Selection is empty. Add analyses, maps or identified materials with « + Selection ».",
                    )
                }}
            </span>
        </p>
        <ol v-else>
            <li
                v-for="row in rows"
                :key="row.key"
                :data-key="row.key"
            >
                <span class="slot">{{ slotLabel(row.slot) }}</span>
                <span class="info">
                    <template v-if="byKey.get(row.key)">
                        <span class="kind">{{
                            kindText(byKey.get(row.key)!)
                        }}</span>
                        <span
                            class="title"
                            :lang="titleOf(byKey.get(row.key)!).lang"
                        >
                            {{ titleOf(byKey.get(row.key)!).value }}
                        </span>
                        <span
                            v-if="documentOf(byKey.get(row.key)!)"
                            class="document"
                            :lang="documentOf(byKey.get(row.key)!)!.lang"
                        >
                            {{ documentOf(byKey.get(row.key)!)!.value }}
                        </span>
                    </template>
                    <span
                        v-else-if="missing.has(row.key)"
                        class="gone"
                    >
                        {{ $gettext("no longer available") }}
                    </span>
                </span>
                <button
                    type="button"
                    class="remove"
                    :aria-label="removeLabel(row.slot)"
                    @click="store.removeFromBasket(row.key)"
                >
                    <span aria-hidden="true">×</span>
                </button>
            </li>
        </ol>
        <div
            v-if="store.basket.length > 0"
            class="actions"
        >
            <button
                type="button"
                class="clear"
                @click="store.clearBasket()"
            >
                <span>{{ $gettext("Empty the Selection") }}</span>
            </button>
            <button
                v-if="canCompare"
                type="button"
                class="compare"
                @click="store.setView('compare')"
            >
                <span>{{ $gettext("Compare") }}</span>
            </button>
        </div>
    </section>
</template>

<style scoped>
.selection-panel {
    display: grid;
    gap: 1rem;
}

.selection-panel h3 {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    font-weight: 600;
}

.selection-panel .count {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-weight: 400;
}

.selection-panel .empty {
    color: var(--ink-muted);
}

.selection-panel ol {
    display: grid;
    gap: 0.25rem;
    padding: 0;
    list-style: none;
}

.selection-panel li {
    display: grid;
    grid-template-columns: auto 1fr auto;
    align-items: center;
    gap: 0 0.5rem;
}

.selection-panel .slot {
    font-family: var(--font-mono);
    font-weight: 600;
}

.selection-panel .info {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0 0.5rem;
}

.selection-panel .kind,
.selection-panel .document,
.selection-panel .gone {
    color: var(--ink-muted);
    font-size: 0.75rem;
}

.selection-panel .remove {
    display: inline-grid;
    place-items: center;
    inline-size: 2.75rem;
    block-size: 2.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.selection-panel .remove:focus-visible,
.selection-panel .clear:focus-visible,
.selection-panel .compare:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.selection-panel .actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
}

.selection-panel .clear,
.selection-panel .compare {
    min-block-size: 2.75rem;
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}
</style>
