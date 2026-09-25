<script setup lang="ts">
import { computed, inject, nextTick, useId, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { slotLabel } from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

/**
 * Adds all its keys to the Selection or none. Once every key is held it says
 * under which slots; when the new keys do not fit, the button is disabled and
 * says how many items for how many places left. The line that replaces the
 * button takes the keyboard focus the removed button leaves.
 */
const props = defineProps<{ keys: string[]; label: string }>();

const announce = inject(ANNOUNCE_KEY, () => undefined);

const store = useExplorerStore();
const { $gettext, $ngettext, interpolate } = useGettext();
const reasonId = useId();
const heldLine = useTemplateRef<HTMLElement>("held-line");

const held = computed(() =>
    store.basket.filter((item) => props.keys.includes(item.key)),
);
const fresh = computed(() =>
    props.keys.filter((key) => !held.value.some((item) => item.key === key)),
);
const heldLabels = computed(() =>
    held.value.map((item) => slotLabel(item.slot)).join(", "),
);
const allHeld = computed(
    () => props.keys.length > 0 && fresh.value.length === 0,
);
const tooMany = computed(() => fresh.value.length > store.basketFree);
const reason = computed(() =>
    [
        interpolate(
            $ngettext("%{n} item", "%{n} items", fresh.value.length),
            { n: fresh.value.length },
            true,
        ),
        interpolate(
            $ngettext(
                "%{free} place left",
                "%{free} places left",
                store.basketFree,
            ),
            { free: store.basketFree },
            true,
        ),
    ].join(", "),
);
const heldText = computed(() =>
    interpolate(
        $gettext("In the Selection as %{slots}"),
        { slots: heldLabels.value },
        true,
    ),
);

async function add(): Promise<void> {
    const result = store.addManyToBasket(props.keys);
    if (result.refused === null && result.added.length > 0) {
        announce(
            interpolate(
                $gettext("Added to the Selection as %{slots}."),
                { slots: heldLabels.value },
                true,
            ),
        );
        await nextTick();
        const active = document.activeElement;
        if (!active || active === document.body) heldLine.value?.focus();
    }
}
</script>

<template>
    <div class="add-to-selection">
        <p
            v-if="allHeld"
            ref="held-line"
            class="held"
            tabindex="-1"
        >
            <span>{{ heldText }}</span>
        </p>
        <template v-else>
            <button
                type="button"
                :disabled="tooMany || props.keys.length === 0"
                :aria-describedby="tooMany ? reasonId : undefined"
                @click="add"
            >
                <span>{{ props.label }}</span>
            </button>
            <p
                v-if="tooMany"
                :id="reasonId"
                class="reason"
            >
                <span>{{ reason }}</span>
            </p>
        </template>
    </div>
</template>

<style scoped>
.add-to-selection button {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--blue-text);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--blue-text);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
}

.add-to-selection button:disabled {
    border-color: var(--border-hover);
    color: var(--ink-dim);
    cursor: not-allowed;
}

.add-to-selection button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.add-to-selection .held,
.add-to-selection .reason {
    color: var(--ink-muted);
    font-size: 0.875rem;
}
</style>
