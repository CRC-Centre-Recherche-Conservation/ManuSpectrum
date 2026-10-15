/**
 * `buildAnnotationNodes` of the project IIIF viewer.
 *
 * Replaces the default of arches/app/media/js/views/components/iiif-viewer.js
 * (Arches 8.1.5), which fetches `iiifannotations` once per canvas of the
 * manifest, in batches of 20, only to fill `annotationCounts` (the number under
 * each thumbnail). Diff vs the core function:
 *   - `preloadAllAnnotations` is gone: the counts of a node come from one
 *     `GET api/iiif-annotation-counts?nodeid=` (`views/iiif_annotation_counts.py`);
 *     a node's counts are summed with the other nodes' as the core preload does
 *   - the current canvas is loaded as in the core (`updateAnnotations`: one
 *     `iiifannotations` request per canvas change and node, memoised per URL),
 *     but it no longer writes the canvas count from the length of the list
 *   - the memo of annotation responses is local to this builder
 *   - the counts of a node are requested once, not again on a later
 *     `manifestData` change; the request follows the current canvas load at
 *     once, without the core's 100 ms `setTimeout`
 *   - no request when the host replaced `getAnnotationCount` (the annotation
 *     widget counts its own drawn features): `isCountShown`
 * Two core bugs are not reproduced: `updateAnnotations` overwriting
 * `counts[canvas]` with the length of one node's list, and the preload adding
 * (`+=`) to the current canvas count already set, which grows on each
 * `manifestData` change.
 * The counts are stricter than the core list: the counts route leaves out the
 * features of resources the reader cannot read, the core list does not.
 * Everything else (node objects, subscriptions, order) is the core's.
 */
import arches from 'arches';
import ko from 'knockout';
import { generateArchesURL } from '@/arches/utils/generate-arches-url.ts';

const countsUrl = (nodeid) =>
    `${generateArchesURL('manuspectrum:api-iiif-annotation-counts')}?nodeid=${encodeURIComponent(nodeid)}`;

/**
 * @param {object} viewer the IIIF viewer viewmodel (`canvas`, `manifestData`,
 *   `annotationNodes`, `annotationCounts`)
 * @param {() => boolean} [isCountShown] false when the host replaced
 *   `getAnnotationCount`, so no counts are needed
 * @returns {(json: object[]) => void} the function the core calls with the
 *   annotation nodes of the reader
 */
export function createBuildAnnotationNodes(viewer, isCountShown = () => true) {
    const cachedAnnotations = {};

    return function buildAnnotationNodes(json) {
        const countsByNode = {};

        const publishCounts = () => {
            const total = {};
            Object.values(countsByNode).forEach((counts) => {
                Object.entries(counts).forEach(([canvas, count]) => {
                    total[canvas] = (total[canvas] || 0) + count;
                });
            });
            viewer.annotationCounts(total);
        };

        viewer.annotationNodes(
            json.map((node) => {
                const annotations = ko.observableArray();

                const updateAnnotations = async function () {
                    const canvas = viewer.canvas();
                    if (!canvas) return;
                    const annotationsUrl =
                        arches.urls.iiifannotations + '?canvas=' + canvas + '&nodeid=' + node.nodeid;
                    try {
                        if (!cachedAnnotations[annotationsUrl]) {
                            const response = await window.fetch(annotationsUrl);
                            cachedAnnotations[annotationsUrl] = await response.json();
                        }
                        const annotation = cachedAnnotations[annotationsUrl];
                        annotation.features.forEach(function (feature) {
                            feature.properties.graphName = node['graph_name'];
                        });
                        annotations(annotation.features);
                    } catch (error) {
                        console.error('Error loading annotations for current canvas:', error);
                    }
                };

                let countsRequested = false;
                const loadCounts = async function () {
                    if (countsRequested || !isCountShown()) return;
                    countsRequested = true;
                    try {
                        const response = await window.fetch(countsUrl(node.nodeid));
                        if (!response.ok) throw new Error(`HTTP ${response.status}`);
                        countsByNode[node.nodeid] = await response.json();
                        publishCounts();
                    } catch (error) {
                        countsRequested = false;
                        console.error('Error loading annotation counts:', error);
                    }
                };

                const initializeAnnotationLoading = async function () {
                    await updateAnnotations();
                    loadCounts();
                };

                viewer.manifestData.subscribe(initializeAnnotationLoading);
                viewer.canvas.subscribe(updateAnnotations);

                initializeAnnotationLoading();

                return {
                    name: node['graph_name'] + ' - ' + node.name,
                    icon: node.icon,
                    active: ko.observable(false),
                    opacity: ko.observable(100),
                    annotations: annotations,
                };
            }),
        );
    };
}
