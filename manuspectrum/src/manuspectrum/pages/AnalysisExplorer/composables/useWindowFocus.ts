import { onBeforeUnmount, onMounted, ref, watch } from "vue";

import {
    focusHue,
    focusRim,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/focus.ts";

import type { Ref, ShallowRef } from "vue";

export interface WindowFocus {
    /** The slots reaching into the window, in slot order. */
    slots: Readonly<Ref<readonly number[]>>;
    /** The things lit in the window, each `data-node` counted once. */
    linkedCount: Readonly<Ref<number>>;
    /** The rim: one band per slot, as wide as the things of that slot. */
    rim: Readonly<Ref<string>>;
    /** Whether something in the window is lit by the node previewed. */
    previewed: Readonly<Ref<boolean>>;
    /** The parity of the bloom under way in the window (its breath), null when none. */
    breath: Readonly<Ref<"odd" | "even" | null>>;
}

const WATCHED = ["data-slots", "data-preview", "data-bloom"];
/** What a window reads: an element added or removed that neither is nor holds one changes nothing. */
const MARKED = "[data-node], [data-slots], [data-preview], [data-bloom]";

function holdsMarks(nodes: NodeList): boolean {
    for (const node of nodes) {
        if (
            node instanceof Element &&
            (node.matches(MARKED) || node.querySelector(MARKED) !== null)
        ) {
            return true;
        }
    }
    return false;
}

/** Whether a mutation may change what the window reads. */
function touchesMarks(record: MutationRecord): boolean {
    return (
        record.type !== "childList" ||
        holdsMarks(record.addedNodes) ||
        holdsMarks(record.removedNodes)
    );
}

/**
 * What the focus lights in a window, read off the toggles its body shows
 * (`useLinkedMarks().focus` attributes): each body renders its own
 * toggles, so the window reads them back from the DOM after a change of
 * their attributes, or of the body's content that adds or removes one
 * (`MutationObserver`), whatever the body is (a table, a legend, a list
 * beside a map). The changes of one frame are read once, on the next frame.
 */
export function useWindowFocus(
    body: Readonly<ShallowRef<HTMLElement | null>>,
): WindowFocus {
    const slots = ref<readonly number[]>([]);
    const linkedCount = ref(0);
    const rim = ref("");
    const previewed = ref(false);
    const breath = ref<"odd" | "even" | null>(null);
    let observer: MutationObserver | null = null;
    let frame: number | null = null;

    function read(): void {
        const element = body.value;
        if (!element) return;
        const counts = new Map<number, number>();
        const seen = new Set<string>();
        for (const lit of element.querySelectorAll<HTMLElement>(
            "[data-slots]",
        )) {
            const node = lit.dataset.node ?? "";
            if (node !== "" && seen.has(node)) continue;
            seen.add(node);
            for (const slot of (lit.dataset.slots ?? "").split(" ")) {
                const number = Number(slot);
                if (!Number.isInteger(number) || number < 1) continue;
                counts.set(number, (counts.get(number) ?? 0) + 1);
            }
        }
        const sorted = [...counts.keys()].sort((left, right) => left - right);
        if (sorted.join(" ") !== slots.value.join(" ")) slots.value = sorted;
        linkedCount.value = seen.size;
        rim.value = focusRim(counts);
        previewed.value = element.querySelector("[data-preview]") !== null;
        const blooming = element.querySelector<HTMLElement>("[data-bloom]");
        const parity = blooming?.dataset.bloom;
        breath.value = parity === "odd" || parity === "even" ? parity : null;
    }

    function cancelRead(): void {
        if (frame !== null) cancelAnimationFrame(frame);
        frame = null;
    }

    function onMutations(records: MutationRecord[]): void {
        if (frame !== null || !records.some(touchesMarks)) return;
        frame = requestAnimationFrame(() => {
            frame = null;
            read();
        });
    }

    function observe(element: HTMLElement | null): void {
        observer?.disconnect();
        observer = null;
        cancelRead();
        if (!element || typeof MutationObserver === "undefined") return;
        observer = new MutationObserver(onMutations);
        observer.observe(element, {
            subtree: true,
            childList: true,
            attributes: true,
            attributeFilter: WATCHED,
        });
        read();
    }

    onMounted(() => observe(body.value));
    watch(body, observe);
    onBeforeUnmount(() => {
        observer?.disconnect();
        cancelRead();
    });

    return { slots, linkedCount, rim, previewed, breath };
}

/** The hue a window takes for its tint: its first slot's. */
export function windowHue(slots: readonly number[]): string | null {
    return slots.length > 0 ? focusHue(slots[0]) : null;
}
