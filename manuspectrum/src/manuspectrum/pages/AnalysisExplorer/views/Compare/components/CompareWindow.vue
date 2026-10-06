<script setup lang="ts">
import {
    computed,
    inject,
    provide,
    ref,
    useId,
    useTemplateRef,
    watch,
} from "vue";
import { useGettext } from "vue3-gettext";

import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";
import FocusSlotDot from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FocusSlotDot.vue";
import SizePicker from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/SizePicker.vue";

import {
    ICONS,
    ICON_VIEW_BOX,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";
import { useMenuButton } from "@/manuspectrum/pages/AnalysisExplorer/composables/useMenuButton.ts";
import { provideWindowActions } from "@/manuspectrum/pages/AnalysisExplorer/composables/useWindowActions.ts";
import {
    useWindowFocus,
    windowHue,
} from "@/manuspectrum/pages/AnalysisExplorer/composables/useWindowFocus.ts";
import {
    LINKED_SELECTION_KEY,
    WINDOW_FRAME_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    focusHue,
    focusStripe,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";

import type { WindowSize } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/types.ts";

/**
 * The frame of one Compare window, its header on one line (in a narrow
 * window it wraps, the button groups at the end of the next line): a drag
 * handle, the title (after an upper-case `kind`, before a counted
 * `subtitle`), the
 * actions its body declares (`useWindowActions`), then its own: the size
 * (`SizePicker`), « Enlarge », the fold disclosure of a window that folds
 * (its state in `aria-expanded`), « More » (a menu: move before or after,
 * hide the window or close the tool, as `hides` says) and « Close ». Every
 * button is an `IconButton`. The group of the window's own controls is
 * named after the title.
 *
 * Enlarged, the header and the body move into the element `enlargeTarget`
 * names (the grid's dialog) through a `Teleport`: the body is the same
 * instance, with its state (a chart drawn, a map, the series read, a
 * treatment). The header then offers the body's actions and « Restore »
 * only, and the grid cell says the window is shown enlarged, with
 * « Restore ». A window that opens folded mounts its content when first
 * unfolded or enlarged; folding it again only hides the content, which
 * keeps its state. Folded, it shows its `summary` slot under the header,
 * which receives `unfold`. `position` is 1-based in reading order; `size` is null
 * for a size set by hand.
 *
 * While the focus holds pinned nodes (`LINKED_SELECTION_KEY`), the window
 * reads what its body lights (`useWindowFocus`): lit, its top rim shows
 * one band per slot reaching into it (as wide as the things of that slot)
 * and its header counts them (slot discs, « N linked »); otherwise it is
 * quiet. A preview lighting something in it half-shows the rim, and the
 * rim breathes once when something in it just gained a slot.
 */
const props = withDefaults(
    defineProps<{
        title: string;
        position: number;
        total: number;
        size: WindowSize | null;
        /** Folded to its header; null: this window does not fold. */
        folded: boolean | null;
        kind?: string;
        subtitle?: string;
        /** « Close » hides the window (true) or closes a tool (false). */
        hides?: boolean;
        enlarged?: boolean;
        /** The selector of the element the enlarged window moves into. */
        enlargeTarget?: string;
    }>(),
    {
        kind: "",
        subtitle: "",
        hides: true,
        enlarged: false,
        enlargeTarget: "body",
    },
);

const emit = defineEmits<{
    (event: "move", payload: { step: -1 | 1 }): void;
    (event: "size-chosen", payload: { size: WindowSize }): void;
    (event: "fold-toggled"): void;
    (event: "enlarge-toggled"): void;
    (event: "close"): void;
}>();

const linked = inject(LINKED_SELECTION_KEY, null);

const { $gettext, $ngettext, interpolate } = useGettext();

const headingId = useId();
const bodyId = useId();
const menuId = useId();
const actions = provideWindowActions();
provide(
    WINDOW_FRAME_KEY,
    computed(() => ({ size: props.size, enlarged: props.enlarged })),
);
const moreRoot = useTemplateRef<HTMLElement>("moreRoot");
const bodyElement = useTemplateRef<HTMLElement>("bodyElement");
const lit = useWindowFocus(bodyElement);
const moreControl = useTemplateRef<InstanceType<typeof IconButton>>("more");
const moreElement = computed(() => moreControl.value?.element ?? null);
const { expanded, closeMenu, toggle, onButtonKeydown, onMenuKeydown } =
    useMenuButton(moreRoot, moreElement);

/** Set once the content was shown: it stays mounted while folded. */
const everShown = ref(props.folded !== true || props.enlarged);

const focusActive = computed(() => (linked?.selection.value.length ?? 0) > 0);
const isLinked = computed(() => focusActive.value && lit.linkedCount.value > 0);
const frameClass = computed(() => ({
    enlarged: props.enlarged,
    "is-linked": isLinked.value,
    "is-quiet": focusActive.value && lit.linkedCount.value === 0,
    "is-previewed": lit.previewed.value,
}));
const frameStyle = computed<Record<string, string> | undefined>(() => {
    const previewSlot = linked?.previewSlot.value ?? null;
    const previewHue = previewSlot === null ? null : focusHue(previewSlot);
    const rim = lit.rim.value || (previewHue ? focusStripe([previewHue]) : "");
    const hue = windowHue(lit.slots.value) ?? previewHue;
    if (!rim && !hue) return undefined;
    return {
        ...(rim ? { "--rim": rim } : {}),
        ...(hue ? { "--h1": hue } : {}),
    };
});
const linkedText = computed(() =>
    interpolate(
        $ngettext("%{n} linked", "%{n} linked", lit.linkedCount.value),
        { n: lit.linkedCount.value },
        true,
    ),
);
const isFirst = computed(() => props.position <= 1);
const isLast = computed(() => props.position >= props.total);
const bodyHidden = computed(() => props.folded === true && !props.enlarged);
const controlsLabel = computed(() =>
    interpolate($gettext("Arrange « %{title} »"), { title: props.title }, true),
);
const actionsLabel = computed(() =>
    interpolate(
        $gettext("Tools of « %{title} »"),
        { title: props.title },
        true,
    ),
);
const moreLabel = computed(() =>
    interpolate(
        $gettext("More for « %{title} »"),
        { title: props.title },
        true,
    ),
);

watch(bodyHidden, (hidden) => {
    if (!hidden) everShown.value = true;
});

function onMove(step: -1 | 1): void {
    if ((step < 0 && isFirst.value) || (step > 0 && isLast.value)) return;
    closeMenu(true);
    emit("move", { step });
}

function unfold(): void {
    if (bodyHidden.value) emit("fold-toggled");
}

function onMenuClose(): void {
    closeMenu(true);
    emit("close");
}
</script>

<template>
    <section
        class="compare-window"
        :class="{ enlarged: props.enlarged }"
        tabindex="-1"
        :aria-labelledby="headingId"
    >
        <p
            v-if="props.enlarged"
            class="enlarged-note"
        >
            <span>{{ $gettext("Shown enlarged") }}</span>
            <button
                type="button"
                class="restore"
                data-action="restore"
                @click="emit('enlarge-toggled')"
            >
                <span>{{ $gettext("Restore") }}</span>
            </button>
        </p>
        <Teleport
            :to="props.enlargeTarget"
            :disabled="!props.enlarged"
            defer
        >
            <div
                class="compare-window-frame"
                :class="frameClass"
                :data-breath="lit.breath.value ?? undefined"
                :style="frameStyle"
            >
                <header class="head">
                    <span
                        v-if="!props.enlarged"
                        class="grab"
                        aria-hidden="true"
                    >
                        <svg
                            :viewBox="ICON_VIEW_BOX"
                            focusable="false"
                        >
                            <path
                                v-for="(path, index) in ICONS['arrows-alt']"
                                :key="index"
                                :d="path"
                            />
                        </svg>
                    </span>
                    <h3
                        :id="headingId"
                        class="title"
                        tabindex="-1"
                        :title="props.title"
                    >
                        <span
                            v-if="props.kind"
                            class="kind"
                            >{{ props.kind }}</span
                        >
                        <span class="name">{{ props.title }}</span>
                        <span
                            v-if="props.subtitle"
                            class="subtitle"
                            >{{ props.subtitle }}</span
                        >
                    </h3>
                    <span
                        v-if="isLinked"
                        class="linked-count"
                    >
                        <span class="dots">
                            <FocusSlotDot
                                v-for="slot in lit.slots.value"
                                :key="slot"
                                size="small"
                                :number="slot"
                            />
                        </span>
                        <span class="text">{{ linkedText }}</span>
                    </span>
                    <div
                        v-if="actions.length > 0 && !bodyHidden"
                        class="actions"
                        role="group"
                        :aria-label="actionsLabel"
                    >
                        <IconButton
                            v-for="action in actions"
                            :key="action.id"
                            :data-action="action.id"
                            :icon="action.icon"
                            :label="action.label"
                            :description="action.description"
                            :pressed="action.pressed ?? null"
                            :disabled="action.disabled ?? false"
                            @click="action.run()"
                        />
                    </div>
                    <div
                        class="controls"
                        role="group"
                        :aria-label="controlsLabel"
                    >
                        <SizePicker
                            v-if="!props.enlarged"
                            :size="props.size"
                            :title="props.title"
                            @size-chosen="emit('size-chosen', $event)"
                        />
                        <IconButton
                            data-action="enlarge"
                            :icon="
                                props.enlarged
                                    ? 'arrow-down-left-and-arrow-up-right-to-center'
                                    : 'expand'
                            "
                            :label="
                                props.enlarged
                                    ? $gettext('Restore')
                                    : $gettext('Enlarge')
                            "
                            @click="emit('enlarge-toggled')"
                        />
                        <IconButton
                            v-if="props.folded !== null && !props.enlarged"
                            data-action="fold"
                            :icon="
                                props.folded ? 'chevron-right' : 'chevron-down'
                            "
                            :label="
                                props.folded
                                    ? $gettext('Unfold')
                                    : $gettext('Fold')
                            "
                            :aria-expanded="props.folded ? 'false' : 'true'"
                            :aria-controls="bodyId"
                            @click="emit('fold-toggled')"
                        />
                        <div
                            v-if="!props.enlarged"
                            ref="moreRoot"
                            class="more"
                        >
                            <IconButton
                                ref="more"
                                data-action="more"
                                icon="ellipsis-h"
                                aria-haspopup="menu"
                                :label="$gettext('More')"
                                :aria-expanded="expanded ? 'true' : 'false'"
                                :aria-controls="expanded ? menuId : undefined"
                                @click="toggle"
                                @keydown="onButtonKeydown"
                            />
                            <ul
                                v-if="expanded"
                                :id="menuId"
                                class="menu"
                                role="menu"
                                :aria-label="moreLabel"
                                @keydown="onMenuKeydown"
                            >
                                <li role="none">
                                    <button
                                        type="button"
                                        role="menuitem"
                                        tabindex="-1"
                                        data-action="move-before"
                                        :aria-disabled="
                                            isFirst ? 'true' : undefined
                                        "
                                        @click="onMove(-1)"
                                    >
                                        <svg
                                            :viewBox="ICON_VIEW_BOX"
                                            aria-hidden="true"
                                            focusable="false"
                                        >
                                            <path
                                                v-for="(path, index) in ICONS[
                                                    'arrow-left'
                                                ]"
                                                :key="index"
                                                :d="path"
                                            />
                                        </svg>
                                        <span>{{
                                            $gettext("Move before")
                                        }}</span>
                                    </button>
                                </li>
                                <li role="none">
                                    <button
                                        type="button"
                                        role="menuitem"
                                        tabindex="-1"
                                        data-action="move-after"
                                        :aria-disabled="
                                            isLast ? 'true' : undefined
                                        "
                                        @click="onMove(1)"
                                    >
                                        <svg
                                            :viewBox="ICON_VIEW_BOX"
                                            aria-hidden="true"
                                            focusable="false"
                                        >
                                            <path
                                                v-for="(path, index) in ICONS[
                                                    'arrow-right'
                                                ]"
                                                :key="index"
                                                :d="path"
                                            />
                                        </svg>
                                        <span>{{
                                            $gettext("Move after")
                                        }}</span>
                                    </button>
                                </li>
                                <li role="none">
                                    <button
                                        type="button"
                                        role="menuitem"
                                        tabindex="-1"
                                        data-action="menu-close"
                                        @click="onMenuClose"
                                    >
                                        <svg
                                            :viewBox="ICON_VIEW_BOX"
                                            aria-hidden="true"
                                            focusable="false"
                                        >
                                            <path
                                                v-for="(path, index) in ICONS[
                                                    props.hides
                                                        ? 'eye-slash'
                                                        : 'times'
                                                ]"
                                                :key="index"
                                                :d="path"
                                            />
                                        </svg>
                                        <span>{{
                                            props.hides
                                                ? $gettext("Hide the window")
                                                : $gettext("Close the tool")
                                        }}</span>
                                    </button>
                                </li>
                            </ul>
                        </div>
                        <IconButton
                            v-if="!props.enlarged"
                            data-action="close"
                            icon="times"
                            :label="$gettext('Close')"
                            @click="emit('close')"
                        />
                    </div>
                </header>
                <div
                    v-if="bodyHidden"
                    class="summary"
                >
                    <slot
                        name="summary"
                        :unfold="unfold"
                    />
                </div>
                <div
                    :id="bodyId"
                    ref="bodyElement"
                    class="body"
                    :hidden="bodyHidden"
                >
                    <slot v-if="everShown" />
                </div>
            </div>
        </Teleport>
    </section>
</template>

<style scoped>
.compare-window {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: minmax(0, 1fr);
    block-size: 100%;
    border: 0.0625rem solid var(--border);
    border-radius: var(--explorer-radius, 0.625rem);
    background: var(--surface);
    box-shadow: var(--shadow-sm);
}

.compare-window:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.compare-window.enlarged {
    place-content: center;
    background: var(--bg-alt);
}

.compare-window .enlarged-note {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    padding: 0.75rem;
    color: var(--ink-muted);
    font-size: 0.875rem;
}

.compare-window .restore {
    min-block-size: var(--explorer-target, 2rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.compare-window .restore:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.compare-window-frame {
    position: relative;
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
    min-block-size: 0;
    block-size: 100%;
    border-radius: var(--explorer-radius, 0.625rem);
    font-size: 0.8125rem;
    transition: box-shadow var(--dur-slow, 420ms) var(--ease-out-expo);
}

/* The rim: one band per focus slot reaching into the window, widths by count. */
.compare-window-frame::before {
    position: absolute;
    z-index: 1;
    inset-block-start: 0;
    inset-inline: 0;
    block-size: 0.125rem;
    border-start-start-radius: var(--explorer-radius, 0.625rem);
    border-start-end-radius: var(--explorer-radius, 0.625rem);
    background: var(--rim, var(--focus-1));
    content: "";
    opacity: 0;
    pointer-events: none;
    transition:
        opacity var(--dur-slow, 420ms),
        background var(--dur-med, 260ms);
}

.compare-window-frame.is-linked {
    box-shadow: var(--shadow-md);
}

.compare-window-frame.is-linked::before {
    opacity: 1;
}

.compare-window-frame.is-previewed::before {
    opacity: 0.45;
    transition-duration: var(--dur-fast, 160ms);
}

.compare-window-frame.is-quiet .title .name {
    color: var(--ink-muted);
}

/* The breath: the rim of a window that just gained a slot rises, dips once and settles. */
.compare-window-frame[data-breath="odd"]::before {
    animation: compare-window-breathe-odd var(--breathe-dur, 900ms) ease-in-out
        1;
}

.compare-window-frame[data-breath="even"]::before {
    animation: compare-window-breathe-even var(--breathe-dur, 900ms) ease-in-out
        1;
}

@keyframes compare-window-breathe-odd {
    0% {
        opacity: 0;
    }
    35% {
        opacity: 1;
    }
    65% {
        opacity: 0.45;
    }
    100% {
        opacity: 1;
    }
}

@keyframes compare-window-breathe-even {
    0% {
        opacity: 0;
    }
    35% {
        opacity: 1;
    }
    65% {
        opacity: 0.45;
    }
    100% {
        opacity: 1;
    }
}

.compare-window-frame .linked-count {
    display: inline-flex;
    flex: none;
    align-items: center;
    gap: 0.375rem;
    padding-block: 0.125rem;
    padding-inline: 0.25rem 0.5rem;
    border-radius: 999rem;
    background: var(--bg-alt);
    color: var(--ink);
    font-size: 0.75rem;
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    white-space: nowrap;
}

.compare-window-frame .linked-count .dots {
    display: inline-flex;
    gap: 0.1875rem;
}

@media (prefers-reduced-motion: reduce) {
    .compare-window-frame,
    .compare-window-frame::before {
        animation: none !important;
        transition-duration: 1ms !important;
    }
}

.compare-window-frame .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem;
    min-block-size: 2.5rem;
    padding-block: 0.125rem;
    padding-inline: 0.25rem 0.375rem;
    border-block-end: 0.0625rem solid var(--border);
}

.compare-window-frame .grab {
    display: inline-grid;
    place-items: center;
    inline-size: 1.5rem;
    block-size: var(--explorer-target, 2rem);
    color: var(--ink-dim);
    cursor: grab;
    user-select: none;
}

.compare-window-frame .grab svg {
    inline-size: 1rem;
    block-size: 1rem;
    fill: currentColor;
}

.compare-window-frame .title {
    display: flex;
    flex: 1 1 14rem;
    align-items: baseline;
    gap: 0.5rem;
    min-inline-size: 0;
    padding-inline-start: 0.25rem;
    overflow: hidden;
    font-size: 0.875rem;
    font-weight: 600;
    white-space: nowrap;
}

.compare-window-frame .title:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}

.compare-window-frame .title .kind {
    color: var(--ink-muted);
    font-size: 0.6875rem;
    font-weight: 500;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.compare-window-frame .title .name {
    min-inline-size: 0;
    overflow: hidden;
    text-overflow: ellipsis;
}

.compare-window-frame .title .subtitle {
    color: var(--ink-muted);
    font-size: 0.75rem;
    font-variant-numeric: tabular-nums;
    font-weight: 400;
}

.compare-window-frame .actions,
.compare-window-frame .controls {
    display: flex;
    flex: none;
    margin-inline-start: auto;
    align-items: center;
    gap: 0.125rem;
}

.compare-window-frame .actions {
    padding-inline-end: 0.25rem;
    border-inline-end: 0.0625rem solid var(--border);
}

.compare-window-frame .more {
    position: relative;
}

.compare-window-frame .menu {
    position: absolute;
    z-index: 110;
    inset-block-start: 100%;
    inset-inline-end: 0;
    display: grid;
    min-inline-size: 13rem;
    padding: 0.25rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    box-shadow: var(--shadow-md);
    list-style: none;
}

.compare-window-frame .menu button {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    inline-size: 100%;
    min-block-size: var(--explorer-target, 2rem);
    padding-inline: 0.5rem;
    border: none;
    border-radius: 0.25rem;
    background: none;
    color: var(--ink);
    font: inherit;
    font-size: 0.875rem;
    text-align: start;
    cursor: pointer;
}

.compare-window-frame .menu button svg {
    flex: none;
    inline-size: 1rem;
    block-size: 1rem;
    fill: currentColor;
}

.compare-window-frame .menu button:hover,
.compare-window-frame .menu button:focus {
    background: var(--bg-alt);
}

.compare-window-frame .menu button[aria-disabled="true"] {
    color: var(--ink-dim);
    cursor: default;
}

.compare-window-frame .menu button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: -0.125rem;
}

.compare-window-frame .summary {
    display: grid;
    align-content: center;
    min-block-size: 0;
    overflow: hidden;
}

.compare-window-frame .body {
    position: relative;
    min-block-size: 0;
    padding: 0.75rem;
    border-end-start-radius: var(--explorer-radius, 0.625rem);
    border-end-end-radius: var(--explorer-radius, 0.625rem);
    overflow: auto;
}

.compare-window-frame.enlarged .body {
    padding: 0.75rem;
}
</style>
