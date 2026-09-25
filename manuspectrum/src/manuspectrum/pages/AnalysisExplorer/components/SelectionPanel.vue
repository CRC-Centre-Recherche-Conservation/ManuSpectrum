<script setup lang="ts">
import { computed, inject, ref, watch } from "vue";
import { useGettext } from "vue3-gettext";

import { useItems } from "@/manuspectrum/pages/AnalysisExplorer/composables/useItems.ts";
import { SELECTION_HINTS_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
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
import type { SelectionHint } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

/**
 * The Selection, kept on this browser. Items read once are kept, so an
 * addition asks the items API for the new keys only; until an item is read,
 * its row shows what the card that added it knew (`SELECTION_HINTS_KEY`).
 */
const hints = inject(
    SELECTION_HINTS_KEY,
    () => ref(new Map<string, SelectionHint>()),
    true,
);

const store = useExplorerStore();
const { $gettext, interpolate } = useGettext();
const { dataKindBadge } = useVocabulary();

const byKey = ref(new Map<string, Item>());
const missing = ref(new Set<string>());

const items = useItems(() =>
    store.basket
        .map((item) => item.key)
        .filter((key) => !byKey.value.has(key) && !missing.value.has(key)),
);

const rows = computed(() => [...store.basket].sort((a, b) => a.slot - b.slot));

watch(
    () => items.data.value,
    (answer) => {
        if (!answer) return;
        const read = new Map(byKey.value);
        for (const item of answer.items) read.set(item.key, item);
        byKey.value = read;
        missing.value = new Set([...missing.value, ...answer.missing]);
    },
);
const canCompare = computed(() => isViewAvailable("compare"));

function kindText(item: Item): string {
    if (item.kind === "characterization")
        return $gettext("identified material");
    if (item.kind === "imaging") return $gettext("map layer");
    return dataKindBadge(item.file.dataKind);
}

function titleOf(item: Item): Label {
    return item.kind === "characterization"
        ? item.characterization.name
        : item.analysis.name;
}

/** The label of a map layer, written after the analysis name (a label from the file, language unknown). */
function layerOf(item: Item): string | null {
    if (item.kind !== "imaging") return null;
    const index = Number(item.key.split(":")[2]);
    return (
        item.file.layers.find((entry) => entry.index === index)?.label ?? null
    );
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
        <header class="head">
            <h3 id="selection-title">
                <span>{{ $gettext("Selection") }}</span>
                <span class="count"
                    >{{ store.basket.length }} / {{ BASKET_LIMIT }}</span
                >
            </h3>
            <p class="kept">
                <span>{{ $gettext("Kept on this browser") }}</span>
            </p>
        </header>
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
                        <span class="title">
                            <span :lang="titleOf(byKey.get(row.key)!).lang">{{
                                titleOf(byKey.get(row.key)!).value
                            }}</span>
                            <span v-if="layerOf(byKey.get(row.key)!)">
                                · {{ layerOf(byKey.get(row.key)!) }}
                            </span>
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
                    <template v-else-if="hints.get(row.key)">
                        <span class="kind">{{ hints.get(row.key)!.kind }}</span>
                        <span class="title">
                            <span :lang="hints.get(row.key)!.title.lang">{{
                                hints.get(row.key)!.title.value
                            }}</span>
                            <span v-if="hints.get(row.key)!.detail">
                                · {{ hints.get(row.key)!.detail }}
                            </span>
                        </span>
                    </template>
                    <span
                        v-else
                        class="pending ms-skeleton"
                        role="img"
                        :aria-label="$gettext('Loading…')"
                    ></span>
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
    align-items: baseline;
    gap: 0.5rem;
    font-size: 0.9375rem;
    font-weight: 600;
}

.selection-panel .count {
    color: var(--ink-muted);
    font-family: var(--font-mono);
    font-weight: 400;
}

.selection-panel .head {
    display: grid;
    gap: 0.125rem;
}

.selection-panel .kept {
    color: var(--ink-muted);
    font-size: 0.75rem;
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

.selection-panel .pending {
    inline-size: 70%;
    block-size: 0.875rem;
}

.selection-panel .remove {
    display: inline-grid;
    place-items: center;
    inline-size: var(--explorer-target, 2.75rem);
    block-size: var(--explorer-target, 2.75rem);
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
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}
</style>
