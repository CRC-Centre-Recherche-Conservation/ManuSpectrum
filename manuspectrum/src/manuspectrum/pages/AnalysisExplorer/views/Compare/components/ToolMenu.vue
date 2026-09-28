<script setup lang="ts">
import {
    computed,
    nextTick,
    onBeforeUnmount,
    ref,
    useId,
    useTemplateRef,
    watch,
} from "vue";
import { useGettext } from "vue3-gettext";

import { toolTitles } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tool-labels.ts";

import type { RequestStatus } from "@/manuspectrum/pages/AnalysisExplorer/composables/useRequest.ts";
import type { ToolKind } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

interface MenuEntry {
    id: string;
    label: string;
    disabled: boolean;
    kind: ToolKind | null;
    retry: boolean;
}

/**
 * « + Tool »: a menu button (WAI-ARIA menu button pattern) listing the tools
 * the Selection has something for (`offered`, null until the synthesis is
 * read). While it is read, or when it failed, one entry says so (the
 * failure offers Retry). Arrows, Home and End move through the entries;
 * Escape closes and gives the focus back to the button, as does a choice;
 * Tab or a click outside closes. When the entries change while it is open,
 * the first one takes the focus.
 */
const props = defineProps<{
    offered: readonly ToolKind[] | null;
    status: RequestStatus;
}>();

const emit = defineEmits<{
    (event: "choose", payload: { kind: ToolKind }): void;
    (event: "retry"): void;
}>();

const { $gettext } = useGettext();

const buttonId = useId();
const menuId = useId();
const root = useTemplateRef<HTMLElement>("root");
const button = useTemplateRef<HTMLButtonElement>("button");

const expanded = ref(false);

const entries = computed<MenuEntry[]>(() => {
    if (props.offered === null) {
        if (props.status === "error") {
            return [
                {
                    id: "retry",
                    label: $gettext("The tools could not be read. Retry"),
                    disabled: false,
                    kind: null,
                    retry: true,
                },
            ];
        }
        return [
            {
                id: "reading",
                label:
                    props.status === "unavailable"
                        ? $gettext("No tool for this Selection")
                        : $gettext("Reading the Selection…"),
                disabled: true,
                kind: null,
                retry: false,
            },
        ];
    }
    if (props.offered.length === 0) {
        return [
            {
                id: "none",
                label: $gettext("No tool for this Selection"),
                disabled: true,
                kind: null,
                retry: false,
            },
        ];
    }
    const titles = toolTitles($gettext);
    return props.offered.map((kind) => ({
        id: kind,
        label: titles[kind],
        disabled: false,
        kind,
        retry: false,
    }));
});

watch(
    () => entries.value.map((entry) => entry.id).join("\n"),
    () => {
        if (expanded.value) focusItem(0);
    },
    { flush: "post" },
);

onBeforeUnmount(stopListening);

function menuItems(): HTMLElement[] {
    return [
        ...(root.value?.querySelectorAll<HTMLElement>('[role="menuitem"]') ??
            []),
    ];
}

function focusItem(index: number): void {
    const found = menuItems();
    if (found.length === 0) return;
    found[(index + found.length) % found.length].focus();
}

async function openMenu(focusIndex: number): Promise<void> {
    expanded.value = true;
    document.addEventListener("pointerdown", onPointerDown);
    await nextTick();
    focusItem(focusIndex);
}

function stopListening(): void {
    document.removeEventListener("pointerdown", onPointerDown);
}

function closeMenu(returnFocus: boolean): void {
    expanded.value = false;
    stopListening();
    if (returnFocus) button.value?.focus();
}

function onPointerDown(event: PointerEvent): void {
    if (!root.value?.contains(event.target as Node)) closeMenu(false);
}

function toggle(): void {
    if (expanded.value) closeMenu(true);
    else void openMenu(0);
}

function onButtonKeydown(event: KeyboardEvent): void {
    if (event.key === "ArrowDown") {
        event.preventDefault();
        void openMenu(0);
    } else if (event.key === "ArrowUp") {
        event.preventDefault();
        void openMenu(-1);
    }
}

function onMenuKeydown(event: KeyboardEvent): void {
    const found = menuItems();
    const index = found.indexOf(document.activeElement as HTMLElement);
    switch (event.key) {
        case "ArrowDown":
            event.preventDefault();
            focusItem(index + 1);
            break;
        case "ArrowUp":
            event.preventDefault();
            focusItem(index - 1);
            break;
        case "Home":
            event.preventDefault();
            focusItem(0);
            break;
        case "End":
            event.preventDefault();
            focusItem(-1);
            break;
        case "Escape":
            event.preventDefault();
            closeMenu(true);
            break;
        case "Tab":
            closeMenu(false);
            break;
    }
}

function choose(entry: MenuEntry): void {
    if (entry.disabled) return;
    closeMenu(true);
    if (entry.retry) emit("retry");
    else if (entry.kind) emit("choose", { kind: entry.kind });
}
</script>

<template>
    <div
        ref="root"
        class="tool-menu"
    >
        <button
            :id="buttonId"
            ref="button"
            type="button"
            class="tool-menu-button"
            aria-haspopup="menu"
            :aria-expanded="expanded ? 'true' : 'false'"
            :aria-controls="expanded ? menuId : undefined"
            @click="toggle"
            @keydown="onButtonKeydown"
        >
            <span>{{ $gettext("+ Tool") }}</span>
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
                v-for="entry in entries"
                :key="entry.id"
                role="none"
            >
                <button
                    type="button"
                    role="menuitem"
                    tabindex="-1"
                    :data-tool="entry.kind ?? undefined"
                    :aria-disabled="entry.disabled ? 'true' : undefined"
                    @click="choose(entry)"
                >
                    <span>{{ entry.label }}</span>
                </button>
            </li>
        </ul>
    </div>
</template>

<style scoped>
.tool-menu {
    position: relative;
}

.tool-menu .tool-menu-button {
    min-block-size: var(--explorer-target, 2.75rem);
    padding-inline: 0.75rem;
    border: 0.0625rem solid var(--ink);
    border-radius: 0.25rem;
    background: var(--ink);
    color: var(--surface);
    font: inherit;
    cursor: pointer;
}

.tool-menu .menu {
    position: absolute;
    inset-block-start: 100%;
    inset-inline-end: 0;
    z-index: 1100;
    display: grid;
    min-inline-size: 14rem;
    margin: 0.25rem 0 0;
    padding: 0.25rem;
    border: 0.0625rem solid var(--border-hover);
    border-radius: 0.375rem;
    background: var(--surface);
    box-shadow: 0 0.25rem 1rem color-mix(in srgb, var(--ink) 15%, transparent);
    list-style: none;
}

.tool-menu .menu button {
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

.tool-menu .menu button:hover,
.tool-menu .menu button:focus {
    background: var(--bg-alt);
}

.tool-menu .menu button[aria-disabled="true"] {
    color: var(--ink-muted);
    cursor: default;
}

.tool-menu .tool-menu-button:focus-visible,
.tool-menu .menu button:focus-visible {
    outline: 0.125rem solid var(--blue-text);
    outline-offset: 0.125rem;
}
</style>
