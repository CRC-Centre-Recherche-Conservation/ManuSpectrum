/**
 * Stacking of annotation paths on a Leaflet map: largest first, pinned paths
 * last. Imported by the Knockout IIIF viewer and the Explorer folio; no
 * Knockout here.
 */
import L from 'leaflet';

/** Bounding-box area of a vector layer in degrees²; markers count as 0. */
function footprint(layer) {
    if (typeof layer.getBounds !== 'function') return 0;
    const bounds = layer.getBounds();
    if (!bounds.isValid()) return 0;
    const sw = bounds.getSouthWest();
    const ne = bounds.getNorthEast();
    return Math.abs((ne.lat - sw.lat) * (ne.lng - sw.lng));
}

/**
 * Leaflet keeps annotations in manifest order, and a click reaches only the
 * topmost path. After each batch of additions, every annotation path is
 * brought to the front from the largest to the smallest; the paths `isPinned`
 * accepts come last, above them all.
 */
export function stackSmallestOnTop(
    map,
    schedule = (fn) => setTimeout(fn, 0),
    isPinned = () => false
) {
    let pending = false;
    map.on('layeradd', (event) => {
        if (pending || !(event.layer instanceof L.Path) || !event.layer.feature) return;
        pending = true;
        schedule(() => {
            pending = false;
            const paths = [];
            map.eachLayer((layer) => {
                if (layer instanceof L.Path && layer.feature) paths.push(layer);
            });
            paths.sort((a, b) => footprint(b) - footprint(a));
            paths.filter((layer) => !isPinned(layer)).forEach((layer) => layer.bringToFront());
            paths.filter(isPinned).forEach((layer) => layer.bringToFront());
        });
    });
}
