/**
 * `HTMLDialogElement.showModal` and `close` for specs: jsdom has the element
 * without them. `showModal` opens the dialog (`open`) and throws on an open
 * one, as browsers do; `close` closes it and queues its `close` event.
 * `pressEscape` does what a browser does on Escape in a modal dialog: the
 * `keydown` on the focused element, then, unless it was prevented, a
 * cancelable `cancel` event on the dialog and its close unless that was
 * prevented.
 * `installDialog()` returns the function that removes the stubs.
 */
export function installDialog(): () => void {
    const prototype = HTMLDialogElement.prototype as Partial<HTMLDialogElement>;
    const had = {
        showModal: Object.getOwnPropertyDescriptor(prototype, "showModal"),
        close: Object.getOwnPropertyDescriptor(prototype, "close"),
    };
    Object.defineProperty(prototype, "showModal", {
        configurable: true,
        value(this: HTMLDialogElement): void {
            if (this.hasAttribute("open")) {
                throw new DOMException(
                    "The dialog is open.",
                    "InvalidStateError",
                );
            }
            this.setAttribute("open", "");
        },
    });
    Object.defineProperty(prototype, "close", {
        configurable: true,
        value(this: HTMLDialogElement): void {
            if (!this.hasAttribute("open")) return;
            this.removeAttribute("open");
            queueMicrotask(() => this.dispatchEvent(new Event("close")));
        },
    });
    return () => {
        for (const [name, descriptor] of Object.entries(had)) {
            if (descriptor) Object.defineProperty(prototype, name, descriptor);
            else delete (prototype as Record<string, unknown>)[name];
        }
    };
}

export function pressEscape(dialog: HTMLDialogElement): void {
    const target = document.activeElement ?? document.body;
    const key = new KeyboardEvent("keydown", {
        key: "Escape",
        bubbles: true,
        cancelable: true,
    });
    if (!target.dispatchEvent(key)) return;
    const cancel = new Event("cancel", { cancelable: true });
    if (dialog.dispatchEvent(cancel)) dialog.close();
}
