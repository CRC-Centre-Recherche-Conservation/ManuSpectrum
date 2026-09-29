<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, watch } from "vue";
import { useGettext } from "vue3-gettext";

import FocusSlotDot from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusSlotDot.vue";

import { LINKED_SELECTION_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { circled } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";

import type { Label } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { RelationLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";

interface TrailRow {
    slot: number;
    label: Label;
    level: string;
}

const GAP_REM = 0.5;
const MAX_WIDTH_REM = 20;
const ROOT_FONT_PX = 16;

/**
 * The trail of the focus: while a mouse or pen rests on a toggle that
 * relates to pinned nodes (the preview of `LINKED_SELECTION_KEY`, after
 * its delay), a small dark note under it lists each of its slots (the
 * slot disc, the pinned node's label, « in the focus », « linked
 * directly » or « cited as evidence ») and what a click does (« Click to
 * unpin », « Click to pin as ③ »). It answers the pointer only and
 * repeats what the pips, the toggle's pressed state and the legend of the
 * focus already say, so it is hidden from assistive technologies and is
 * not a tooltip that owns Escape: Escape still clears the focus, which
 * hides the trail with it. It moves into the enlarged window's dialog
 * when the toggle is there, above which nothing else would show. It
 * follows its toggle when the page scrolls or the viewport changes size,
 * and is gone once the toggle has left the page.
 */
const linked = inject(LINKED_SELECTION_KEY)!;

const { $gettext, interpolate } = useGettext();

/** Counts the scrolls and resizes while the trail is shown, so its place is read again. */
const moved = ref(0);

const relations = computed(() => {
    const id = linked.previewing.value;
    return id === null ? null : linked.relations.value.get(id) ?? null;
});
const anchor = computed(() =>
    relations.value ? linked.previewAnchor.value : null,
);
const rows = computed<TrailRow[]>(() =>
    (relations.value?.slots ?? []).flatMap(({ slot, level }) => {
        const id = linked.slots.value[slot - 1];
        if (!id) return [];
        return [
            {
                slot,
                label: linked.labelOf(id) ?? { value: id, lang: "" },
                level: levelText(level),
            },
        ];
    }),
);
const shown = computed(
    () =>
        anchor.value !== null &&
        anchor.value.isConnected &&
        rows.value.length > 0,
);
const hint = computed(() =>
    relations.value?.best === "self"
        ? $gettext("Click to unpin")
        : interpolate(
              $gettext("Click to pin as %{slot}"),
              { slot: circled(linked.nextSlot.value) },
              true,
          ),
);
const target = computed<HTMLElement | string>(
    () => anchor.value?.closest<HTMLElement>("dialog[open]") ?? "body",
);
const position = computed(() => {
    void moved.value;
    return placeUnder(anchor.value);
});

watch(anchor, (next, previous) => {
    if (next && !previous) follow(true);
    else if (!next && previous) follow(false);
});

onBeforeUnmount(() => follow(false));

function onMove(): void {
    moved.value += 1;
}

/** Listens to scrolls (any scroller) and resizes while `on`. */
function follow(on: boolean): void {
    if (on) {
        window.addEventListener("scroll", onMove, {
            capture: true,
            passive: true,
        });
        window.addEventListener("resize", onMove, { passive: true });
    } else {
        window.removeEventListener("scroll", onMove, { capture: true });
        window.removeEventListener("resize", onMove);
    }
}

/** The trail's place, under `element` and inside the viewport. */
function placeUnder(element: Element | null): Record<string, string> {
    const box = element?.getBoundingClientRect();
    if (!box) return {};
    const gap = GAP_REM * ROOT_FONT_PX;
    const width = MAX_WIDTH_REM * ROOT_FONT_PX;
    const left = Math.max(
        gap,
        Math.min(window.innerWidth - width - gap, box.left),
    );
    return {
        "--trail-left": `${left}px`,
        "--trail-top": `${box.bottom + gap}px`,
    };
}

function levelText(level: RelationLevel): string {
    switch (level) {
        case "self":
            return $gettext("in the focus");
        case "direct":
            return $gettext("linked directly");
        default:
            return $gettext("cited as evidence");
    }
}
</script>

<template>
    <Teleport :to="target">
        <div
            v-if="shown"
            class="focus-trail"
            aria-hidden="true"
            :style="position"
        >
            <ul class="rows">
                <li
                    v-for="row in rows"
                    :key="row.slot"
                >
                    <FocusSlotDot
                        size="small"
                        :number="row.slot"
                    />
                    <span
                        class="label"
                        :lang="row.label.lang || undefined"
                        >{{ row.label.value }}</span
                    >
                    <em>{{ row.level }}</em>
                </li>
            </ul>
            <p class="hint">{{ hint }}</p>
        </div>
    </Teleport>
</template>

<style scoped>
.focus-trail {
    position: fixed;
    z-index: 1200;
    inset-block-start: var(--trail-top);
    inset-inline-start: var(--trail-left);
    display: grid;
    gap: 0.25rem;
    max-inline-size: 20rem;
    padding-block: 0.5rem;
    padding-inline: 0.625rem;
    border-radius: 0.5rem;
    background: var(--ink);
    box-shadow: var(--shadow-md);
    color: var(--surface);
    font-size: 0.75rem;
    line-height: 1.4;
    pointer-events: none;
}

.focus-trail .rows {
    display: grid;
    gap: 0.25rem;
    margin: 0;
    padding: 0;
    list-style: none;
}

.focus-trail .rows li {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    min-inline-size: 0;
    white-space: nowrap;
}

.focus-trail .label {
    overflow: hidden;
    text-overflow: ellipsis;
}

.focus-trail em {
    flex: none;
    color: color-mix(in srgb, var(--surface) 75%, transparent);
    font-style: normal;
}

.focus-trail .hint {
    margin: 0;
    color: color-mix(in srgb, var(--surface) 70%, transparent);
}
</style>
