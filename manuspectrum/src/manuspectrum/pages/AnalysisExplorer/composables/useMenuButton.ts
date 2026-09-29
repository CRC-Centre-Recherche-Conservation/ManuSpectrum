import { nextTick, onBeforeUnmount, ref } from "vue";

import type { Ref } from "vue";

export interface MenuButton {
    expanded: Ref<boolean>;
    focusItem: (index: number) => void;
    closeMenu: (returnFocus: boolean) => void;
    toggle: () => void;
    onButtonKeydown: (event: KeyboardEvent) => void;
    onMenuKeydown: (event: KeyboardEvent) => void;
}

/**
 * The WAI-ARIA menu button pattern for a button and the `role="menuitem"`
 * entries under `root`: the button opens the menu on the first entry
 * (ArrowUp: on the last); Arrows, Home and End move through the entries;
 * Escape closes and gives the focus back to the button; Tab or a pointer
 * down outside `root` closes. A negative index counts from the end.
 */
export function useMenuButton(
    root: Readonly<Ref<HTMLElement | null>>,
    button: Readonly<Ref<HTMLButtonElement | null>>,
): MenuButton {
    const expanded = ref(false);

    onBeforeUnmount(stopListening);

    function menuItems(): HTMLElement[] {
        return [
            ...(root.value?.querySelectorAll<HTMLElement>(
                '[role="menuitem"]',
            ) ?? []),
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

    return {
        expanded,
        focusItem,
        closeMenu,
        toggle,
        onButtonKeydown,
        onMenuKeydown,
    };
}
