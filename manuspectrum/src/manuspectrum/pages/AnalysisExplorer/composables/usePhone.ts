import { onBeforeUnmount, readonly, ref } from "vue";

import type { Ref } from "vue";

/** Under this width a window is read as on a phone (the grid is one column too). */
export const PHONE_QUERY = "(max-width: 48rem)";

/** Whether the screen is narrower than 48 rem, kept current while the component lives. */
export function usePhone(): Readonly<Ref<boolean>> {
    const query = window.matchMedia?.(PHONE_QUERY) ?? null;
    const phone = ref(query?.matches ?? false);
    const onChange = (event: { matches: boolean }): void => {
        phone.value = event.matches;
    };
    query?.addEventListener?.("change", onChange);
    onBeforeUnmount(() => query?.removeEventListener?.("change", onChange));
    return readonly(phone);
}
