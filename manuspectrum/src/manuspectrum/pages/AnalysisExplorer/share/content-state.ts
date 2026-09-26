import type { Shape } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const MEDIA_FRAGMENTS = "http://www.w3.org/TR/media-frags/";
const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
const WEB_SCHEMES = new Set(["http:", "https:"]);

type Selector =
    | { type: "PointSelector"; x: number; y: number }
    | { type: "FragmentSelector"; conformsTo: string; value: string }
    | { type: "SvgSelector"; value: string };

/** IIIF selector of a shape in canvas pixels, by the rule of the Explorer manifest: point, `xywh` fragment, SVG polygon. */
function selectorOf(shape: Shape): Selector {
    if (shape.type === "point") {
        return {
            type: "PointSelector",
            x: Math.trunc(shape.x),
            y: Math.trunc(shape.y),
        };
    }
    if (shape.type === "rect") {
        const box = [shape.x, shape.y, shape.w, shape.h].map(Math.trunc);
        return {
            type: "FragmentSelector",
            conformsTo: MEDIA_FRAGMENTS,
            value: `xywh=${box.join(",")}`,
        };
    }
    const points = shape.points
        .map(([x, y]) => `${Math.trunc(x)},${Math.trunc(y)}`)
        .join(" ");
    return {
        type: "SvgSelector",
        value: `<svg xmlns="${SVG_NAMESPACE}"><polygon points="${points}"/></svg>`,
    };
}

/**
 * IIIF Content State 1.0 of an analysis on `canvas` of `manifest`,
 * base64url-encoded: an Annotation with motivation `contentState` whose
 * target is the zone `shape` on the canvas, or the whole canvas without one.
 * The IIIF helpers are loaded on first use.
 */
export async function analysisContentState(
    manifest: string,
    canvas: string,
    shape: Shape | null,
): Promise<string> {
    const { serialiseContentState } = await import(
        "@iiif/helpers/content-state"
    );
    const source = {
        id: canvas,
        type: "Canvas",
        partOf: [{ id: manifest, type: "Manifest" }],
    };
    const annotation = {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        id: `${manifest}#content-state`,
        type: "Annotation",
        motivation: ["contentState"],
        target: shape
            ? { type: "SpecificResource", source, selector: selectorOf(shape) }
            : source,
    };
    return serialiseContentState(
        annotation as unknown as Parameters<typeof serialiseContentState>[0],
    );
}

/** What the viewer opens: a manifest by its URL, or a content state. */
export type MiradorTarget = { manifest: string } | { contentState: string };

/**
 * The address that opens `target` in the Mirador viewer at `viewer`
 * (`EXPLORER_MIRADOR_URL`): `?manifest=<url>` or `?iiif-content=<base64url>`,
 * added to the viewer's own query. Null without a viewer or for a viewer
 * address that is not absolute http(s).
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
 * The IIIF link of the content state `state` of `manifest`, a URL to copy
 * (IIIF Content State 1.0 §3.1, `iiif-content` request parameter): the
 * link that opens it in the viewer at `viewer` when one is set, else the
 * manifest URL carrying it as `iiif-content`.
 */
export function contentStateLink(
    viewer: string,
    manifest: string,
    state: string,
): string {
    const opened = miradorLink(viewer, { contentState: state });
    if (opened) return opened;
    const url = new URL(manifest);
    url.searchParams.set("iiif-content", state);
    return url.href;
}
