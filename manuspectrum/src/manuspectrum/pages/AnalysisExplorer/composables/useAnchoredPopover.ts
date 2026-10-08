import { onBeforeUnmount, ref, watch } from "vue";

import type { Ref } from "vue";

/** Space kept to the viewport's edges, and between the anchor and the popover, in px. */
const EDGE_PX = 8;
const OFFSET_PX = 4;

export interface AnchoredPopoverOptions {
    /** The side tried first; the other one is used when it has more room and this one too little. Default: below. */
    prefer?: "above" | "below";
    /** The anchor's edge the popover lines up with. Default: start (left). */
    align?: "start" | "end";
    /** Gap between the anchor and the popover, in px. */
    offset?: number;
    /** Called while open when the anchor is no longer visible (scrolled out of, or clipped by, its container). */
    onLost?: () => void;
}

export interface AnchoredPopover {
    /** Inline position of the popover and `--anchor-width`; apply it with `:style`. */
    style: Ref<Record<string, string>>;
    /** Places the popover again against its anchor. */
    place: () => void;
}

/**
 * Puts `popover` in the top layer (`popover="manual"` element, so it is never
 * clipped by a scrolling window body) while `open` is true, under `anchor`,
 * left-aligned and kept inside the viewport; above the anchor when there is
 * more room there (`options.prefer: "above"` tries above first, `align: "end"`
 * lines the popover up with the anchor's right edge). It follows the anchor
 * wherever it goes: scroll, resize, and any layout shift that moves it (the
 * anchor's box is read once per frame while open). When the anchor leaves the
 * visible area it calls `options.onLost`, for the caller to close. Showing and
 * hiding do not move the focus; light dismissal is the caller's.
 */
export function useAnchoredPopover(
    open: Readonly<Ref<boolean>>,
    popover: Readonly<Ref<HTMLElement | null>>,
    anchor: Readonly<Ref<HTMLElement | null>>,
    options: AnchoredPopoverOptions = {},
): AnchoredPopover {
    const gap = options.offset ?? OFFSET_PX;
    const style = ref<Record<string, string>>({});
    let listening = false;
    let frame: number | null = null;
    let placedBox = "";
    let sight: IntersectionObserver | null = null;

    watch(
        [open, popover],
        ([isOpen, element], [wasOpen, previous]) => {
            if (previous && previous !== element) hide(previous);
            if (isOpen && element) {
                show(element);
                place();
                listen();
            } else {
                if (wasOpen && element) hide(element);
                unlisten();
            }
        },
        { flush: "post" },
    );

    onBeforeUnmount(unlisten);

    function show(element: HTMLElement): void {
        if (typeof element.showPopover !== "function") return;
        try {
            if (!element.matches(":popover-open")) element.showPopover();
        } catch {
            // Not connected yet: the element stays where the stylesheet puts it.
        }
    }

    function hide(element: HTMLElement): void {
        if (typeof element.hidePopover !== "function") return;
        try {
            if (element.matches(":popover-open")) element.hidePopover();
        } catch {
            // Already gone with its parent.
        }
    }

    function place(): void {
        const element = popover.value;
        const from = anchor.value;
        if (!element || !from) return;
        const rect = from.getBoundingClientRect();
        placedBox = boxOf(rect);
        const width = element.offsetWidth;
        const height = element.scrollHeight;
        const room = {
            below: window.innerHeight - rect.bottom - EDGE_PX - gap,
            above: rect.top - EDGE_PX - gap,
        };
        const above =
            options.prefer === "above"
                ? height <= room.above || room.above >= room.below
                : height > room.below && room.above > room.below;
        const available = Math.max(above ? room.above : room.below, 0);
        const wanted = options.align === "end" ? rect.right - width : rect.left;
        const left = Math.max(
            EDGE_PX,
            Math.min(wanted, window.innerWidth - width - EDGE_PX),
        );
        const shown = Math.min(height, available);
        style.value = {
            insetInlineStart: `${left}px`,
            insetBlockStart: `${above ? rect.top - gap - shown : rect.bottom + gap}px`,
            maxBlockSize: `${available}px`,
            "--anchor-width": `${rect.width}px`,
        };
    }

    function onMoved(event: Event): void {
        if (
            event.target instanceof Node &&
            popover.value?.contains(event.target)
        )
            return;
        place();
    }

    function boxOf(rect: DOMRect): string {
        return `${rect.left}|${rect.top}|${rect.width}|${rect.bottom}`;
    }

    function follow(): void {
        frame = requestAnimationFrame(() => {
            frame = null;
            const from = anchor.value;
            if (!listening) return;
            if (from && boxOf(from.getBoundingClientRect()) !== placedBox) {
                place();
            }
            follow();
        });
    }

    function listen(): void {
        if (listening) return;
        listening = true;
        window.addEventListener("scroll", onMoved, true);
        window.addEventListener("resize", onMoved);
        follow();
        const from = anchor.value;
        if (
            from &&
            options.onLost &&
            typeof IntersectionObserver !== "undefined"
        ) {
            sight = new IntersectionObserver((entries) => {
                if (entries.at(-1)?.isIntersecting === false)
                    options.onLost?.();
            });
            sight.observe(from);
        }
    }

    function unlisten(): void {
        if (!listening) return;
        listening = false;
        window.removeEventListener("scroll", onMoved, true);
        window.removeEventListener("resize", onMoved);
        if (frame !== null) cancelAnimationFrame(frame);
        frame = null;
        sight?.disconnect();
        sight = null;
    }

    return { style, place };
}
