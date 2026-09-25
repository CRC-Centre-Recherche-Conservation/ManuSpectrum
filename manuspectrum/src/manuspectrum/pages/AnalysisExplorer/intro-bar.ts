/** Id of the slot the page template leaves in the intro line for the explorer's bar (back link, Selection). */
export const INTRO_BAR_ID = "ms-explorer-intro-bar";

/** The intro line's slot, or null when the page has none (the bar then stays in place). */
export function introBar(): HTMLElement | null {
    return document.getElementById(INTRO_BAR_ID);
}
