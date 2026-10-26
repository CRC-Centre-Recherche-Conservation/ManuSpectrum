<script setup lang="ts">
import { computed, useId, useTemplateRef, watch } from "vue";
import { useGettext } from "vue3-gettext";

import { useMenuButton } from "@/manuspectrum/pages/AnalysisExplorer/composables/useMenuButton.ts";

import type { HiddenWindowEntry } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/types.ts";

/**
 * « Hidden windows (n) » in the Compare toolbar: a menu button
 * (`useMenuButton`) with one entry per hidden window, « Show <title> »,
 * marked with the spectra it gained while hidden. It is always there, and
 * disabled (`aria-disabled`, still focusable) while no window is hidden; it
 * closes when the last hidden window goes. A choice closes the menu and
 * emits `show`: the parent gives the focus to the window shown.
 */
const props = defineProps<{
    windows: readonly HiddenWindowEntry[];
}>();

const emit = defineEmits<{
    (event: "show", payload: { id: string }): void;
}>();

const { $gettext, $ngettext, interpolate } = useGettext();

const buttonId = useId();
const menuId = useId();
const root = useTemplateRef<HTMLElement>("root");
const button = useTemplateRef<HTMLButtonElement>("button");
const { expanded, closeMenu, toggle, onButtonKeydown, onMenuKeydown } =
    useMenuButton(root, button);

const disabled = computed(() => props.windows.length === 0);
const buttonLabel = computed(() =>
    interpolate(
        $gettext("Hidden windows (%{n})"),
        { n: props.windows.length },
        true,
    ),
);

watch(disabled, (none) => {
    if (none && expanded.value) closeMenu(false);
});

function showLabel(title: string): string {
    return interpolate($gettext("Show %{title}"), { title }, true);
}

function addedLabel(count: number): string {
    return interpolate(
        $ngettext("%{n} spectrum added", "%{n} spectra added", count),
        { n: count },
        true,
    );
}

function onClick(): void {
    if (!disabled.value) toggle();
}

function onKeydown(event: KeyboardEvent): void {
    if (!disabled.value) onButtonKeydown(event);
}

function choose(id: string): void {
    closeMenu(true);
    emit("show", { id });
}
</script>

<template>
    <div
        ref="root"
        class="hidden-windows"
    >
        <button
            :id="buttonId"
            ref="button"
            type="button"
            class="hidden-windows-button"
            aria-haspopup="menu"
            :aria-expanded="expanded ? 'true' : 'false'"
            :aria-controls="expanded ? menuId : undefined"
            :aria-disabled="disabled ? 'true' : undefined"
            @click="onClick"
            @keydown="onKeydown"
        >
            <span>{{ buttonLabel }}</span>
        </button>
        <ul
            v-if="expanded"
            :id="menuId"
            class="menu"
            role="menu"
            :aria-labelledby="buttonId"
            @keydown="onMenuKeydown"
        >
            <li
                v-for="entry in windows"
                :key="entry.id"
                role="none"
            >
                <button
                    type="button"
                    role="menuitem"
                    tabindex="-1"
                    :data-window-id="entry.id"
                    @click="choose(entry.id)"
                >
                    <span>{{ showLabel(entry.title) }}</span>
                    <span
                        v-if="entry.added > 0"
                        class="badge"
                        >{{ addedLabel(entry.added) }}</span
                    >
                </button>
            </li>
        </ul>
    </div>
</template>

<style scoped>
.hidden-windows {
    position: relative;
}

.hidden-windows .hidden-windows-button {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.25rem;
    background: var(--surface);
    color: var(--ink);
    font: inherit;
    cursor: pointer;
}

.hidden-windows .hidden-windows-button[aria-disabled="true"] {
    color: var(--ink-muted);
    cursor: default;
}

.hidden-windows .menu {
    position: absolute;
    inset-block-start: 100%;
    inset-inline-end: 0;
    z-index: 1100;
    display: grid;
    min-inline-size: 16rem;
    margin: 0.25rem 0 0;
    padding: 0.25rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    box-shadow: 0 0.25rem 1rem color-mix(in srgb, var(--ink) 15%, transparent);
    list-style: none;
}

.hidden-windows .menu button {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    inline-size: 100%;
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: none;
    border-radius: 0.25rem;
    background: none;
    color: var(--ink);
    font: inherit;
    text-align: start;
    cursor: pointer;
}

.hidden-windows .menu button:hover,
.hidden-windows .menu button:focus {
    background: var(--bg-alt);
}

.hidden-windows .badge {
    padding-inline: 0.375rem;
    border-radius: 999rem;
    background: var(--ink);
    color: var(--surface);
    font-size: 0.75rem;
}

.hidden-windows .hidden-windows-button:focus-visible,
.hidden-windows .menu button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
