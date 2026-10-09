const WEB_SCHEMES = new Set(["http:", "https:"]);

/** What the viewer opens: a manifest by its URL, or a published content state by its URL. */
export type MiradorTarget = { manifest: string } | { contentState: string };

/**
 * The address that opens `target` in the Mirador viewer at `viewer`
 * (`EXPLORER_MIRADOR_URL`): `?manifest=<url>` or `?iiif-content=<url>`
 * (IIIF Content State 1.0 §3.1: the URL of a published state, never
 * content-state-encoded), added to the viewer's own query. Null without a
 * viewer or for a viewer address that is not absolute http(s).
 */
export function miradorLink(
    viewer: string,
    target: MiradorTarget,
): string | null {
    let url: URL;
    try {
        url = new URL(viewer);
    } catch {
        return null;
    }
    if (!WEB_SCHEMES.has(url.protocol)) return null;
    if ("manifest" in target) {
        url.searchParams.set("manifest", target.manifest);
    } else {
        url.searchParams.set("iiif-content", target.contentState);
    }
    return url.href;
}

/**
 * The IIIF link of the published content state at `state`, a URL to copy:
 * the viewer at `viewer` opening it (`miradorLink`) when that viewer is an
 * absolute http(s) address, else `state` itself.
 */
export function contentStateLink(viewer: string, state: string): string {
    return miradorLink(viewer, { contentState: state }) ?? state;
}
