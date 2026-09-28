<script setup lang="ts">
import { computed, ref, useId, useTemplateRef, watch } from "vue";
import { useGettext } from "vue3-gettext";

import IconButton from "@/manuspectrum/pages/AnalysisExplorer/components/IconButton.vue";
import SizePicker from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/SizePicker.vue";

import {
    ICONS,
    ICON_VIEW_BOX,
} from "@/manuspectrum/pages/AnalysisExplorer/components/icons.ts";
import { useMenuButton } from "@/manuspectrum/pages/AnalysisExplorer/composables/useMenuButton.ts";
import { provideWindowActions } from "@/manuspectrum/pages/AnalysisExplorer/composables/useWindowActions.ts";

import type { WindowSize } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/types.ts";

/**
 * The frame of one Compare window, its header on one line: a drag handle,
 * the title (after a small-caps `kind`, before a counted `subtitle`), the
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
 * keeps its state. `position` is 1-based in reading order; `size` is null
 * for a size set by hand.
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

const { $gettext, interpolate } = useGettext();

const headingId = useId();
const bodyId = useId();
const menuId = useId();
const actions = provideWindowActions();
const moreRoot = useTemplateRef<HTMLElement>("moreRoot");
const moreControl = useTemplateRef<InstanceType<typeof IconButton>>("more");
const moreElement = computed(() => moreControl.value?.element ?? null);
const { expanded, closeMenu, toggle, onButtonKeydown, onMenuKeydown } =
    useMenuButton(moreRoot, moreElement);

/** Set once the content was shown: it stays mounted while folded. */
const everShown = ref(props.folded !== true || props.enlarged);

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
                :class="{ enlarged: props.enlarged }"
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
                    :id="bodyId"
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
    border: 0.0625rem solid var(--border-hover);
    border-radius: var(--explorer-radius, 0.625rem);
    background: var(--surface);
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
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto minmax(0, 1fr);
    min-block-size: 0;
    block-size: 100%;
}

.compare-window-frame .head {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    min-block-size: 2.5rem;
    padding-block: 0.125rem;
    padding-inline: 0.25rem;
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
    flex: 1;
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
    font-variant-caps: all-small-caps;
    letter-spacing: 0.06em;
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

.compare-window-frame .body {
    min-block-size: 0;
    padding: 0.5rem;
    border-end-start-radius: var(--explorer-radius, 0.625rem);
    border-end-end-radius: var(--explorer-radius, 0.625rem);
    overflow: auto;
}

.compare-window-frame.enlarged .body {
    padding: 0.75rem;
}
</style>
