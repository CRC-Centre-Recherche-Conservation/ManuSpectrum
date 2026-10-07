<script setup lang="ts">
import { computed, inject, nextTick, ref, useId, useTemplateRef } from "vue";
import { useGettext } from "vue3-gettext";

import {
    ANNOUNCE_KEY,
    SELECTION_HINTS_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    BASKET_LIMIT,
    slotLabel,
} from "@/manuspectrum/pages/AnalysisExplorer/store/basket.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";

import type { SelectionHint } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";

interface SelectionAction {
    keys: string[];
    label: string;
    hints?: ReadonlyMap<string, SelectionHint> | null;
}

/**
 * Two buttons side by side under `title`: the `primary` one adds its keys
 * (the material and its supporting analyses), the optional `secondary` one
 * adds a part of them (the material alone). Each adds all its keys or none:
 * when the new keys do not fit, it is disabled and says how many items for
 * how many places left. Once every primary key is held, a line says where
 * (« A3 (with A4, A5) ») and takes the keyboard focus the buttons leave;
 * when only the secondary keys are held, the line says so and the primary
 * button stays. `hints` tell the Selection what the added items are before
 * it has read them.
 */
const props = defineProps<{
    title: string;
    primary: SelectionAction;
    secondary?: SelectionAction | null;
}>();

const announce = inject(ANNOUNCE_KEY, () => undefined);
const selectionHints = inject(
    SELECTION_HINTS_KEY,
    () => ref(new Map<string, SelectionHint>()),
    true,
);

const store = useExplorerStore();
const { $gettext, $ngettext, interpolate } = useGettext();
const titleId = useId();
const primaryReasonId = useId();
const secondaryReasonId = useId();
const heldLine = useTemplateRef<HTMLElement>("held-line");

const heldKeys = computed(() => new Set(store.basket.map((item) => item.key)));

function allHeld(action: SelectionAction | null | undefined): boolean {
    return (
        !!action &&
        action.keys.length > 0 &&
        action.keys.every((key) => heldKeys.value.has(key))
    );
}

function slotOf(key: string): string {
    const item = store.basket.find((entry) => entry.key === key);
    return item ? slotLabel(item.slot) : "";
}

function reasonOf(action: SelectionAction): string | null {
    const fresh = action.keys.filter((key) => !heldKeys.value.has(key));
    if (fresh.length <= store.basketFree) return null;
    return [
        interpolate(
            $ngettext("%{n} item", "%{n} items", fresh.length),
            { n: fresh.length },
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
    ].join(", ");
}

const primaryHeld = computed(() => allHeld(props.primary));
const secondaryHeld = computed(() => allHeld(props.secondary));
const primaryReason = computed(() => reasonOf(props.primary));
const secondaryReason = computed(() =>
    props.secondary ? reasonOf(props.secondary) : null,
);
const heldText = computed(() => {
    const own = props.secondary?.keys ?? props.primary.keys;
    const ownSlots = own.map(slotOf).join(", ");
    const others = props.primary.keys
        .filter((key) => !own.includes(key))
        .map(slotOf);
    if (!primaryHeld.value || others.length === 0) {
        return interpolate(
            $gettext("In the Selection: %{slots}"),
            { slots: ownSlots },
            true,
        );
    }
    return interpolate(
        $gettext("In the Selection: %{slots} (with %{others})"),
        { slots: ownSlots, others: others.join(", ") },
        true,
    );
});

function recordHints(action: SelectionAction): void {
    if (!action.hints || action.hints.size === 0) return;
    const next = new Map(selectionHints.value);
    for (const [key, hint] of action.hints) next.set(key, hint);
    selectionHints.value = next;
}

async function add(action: SelectionAction): Promise<void> {
    recordHints(action);
    const result = store.addManyToBasket(action.keys);
    if (result.refused === null && result.added.length > 0) {
        announce(
            interpolate(
                $gettext("Added to the Selection (%{n}/%{limit})."),
                { n: store.basket.length, limit: BASKET_LIMIT },
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
    <div
        class="selection-actions"
        role="group"
        :aria-labelledby="titleId"
    >
        <p
            :id="titleId"
            class="group-title"
        >
            <span>{{ props.title }}</span>
        </p>
        <p
            v-if="primaryHeld || secondaryHeld"
            ref="held-line"
            class="held"
            tabindex="-1"
        >
            <span>{{ heldText }}</span>
        </p>
        <div
            v-if="!primaryHeld"
            class="buttons"
        >
            <button
                type="button"
                class="primary"
                :disabled="!!primaryReason || props.primary.keys.length === 0"
                :aria-describedby="primaryReason ? primaryReasonId : undefined"
                @click="add(props.primary)"
            >
                <span>{{ props.primary.label }}</span>
            </button>
            <button
                v-if="props.secondary && !secondaryHeld"
                type="button"
                class="secondary"
                :disabled="!!secondaryReason"
                :aria-describedby="
                    secondaryReason ? secondaryReasonId : undefined
                "
                @click="add(props.secondary)"
            >
                <span>{{ props.secondary.label }}</span>
            </button>
        </div>
        <p
            v-if="!primaryHeld && primaryReason"
            :id="primaryReasonId"
            class="reason"
        >
            <span>{{ primaryReason }}</span>
        </p>
        <p
            v-if="!primaryHeld && secondaryReason && !secondaryHeld"
            :id="secondaryReasonId"
            class="reason"
        >
            <span>{{ secondaryReason }}</span>
        </p>
    </div>
</template>

<style scoped>
.selection-actions {
    display: grid;
    gap: 0.375rem;
}

.selection-actions .group-title {
    color: var(--ink-muted);
    font-size: 0.75rem;
    font-weight: 600;
}

.selection-actions .buttons {
    display: inline-flex;
    flex-wrap: wrap;
    justify-self: start;
}

.selection-actions button {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--blue-text);
    background: var(--surface);
    color: var(--blue-text);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
}

.selection-actions .primary {
    border-start-start-radius: 0.25rem;
    border-end-start-radius: 0.25rem;
    background: var(--blue-text);
    color: var(--surface);
}

.selection-actions .primary:only-child {
    border-radius: 0.25rem;
}

.selection-actions .primary:not(:only-child) {
    border-inline-end-color: var(--surface);
}

.selection-actions .secondary {
    border-start-end-radius: 0.25rem;
    border-end-end-radius: 0.25rem;
    border-inline-start-width: 0;
}

.selection-actions button:disabled {
    border-color: var(--border-hover);
    background: var(--bg-alt);
    color: var(--ink-dim);
    cursor: not-allowed;
}

.selection-actions button:focus-visible {
    z-index: 1;
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.selection-actions .held,
.selection-actions .reason {
    color: var(--ink-muted);
    font-size: 0.875rem;
}
</style>
