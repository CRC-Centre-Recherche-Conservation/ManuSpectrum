/**
 * `msSpark: {fileId, title}` — the spectrum of one file as an inline sparkline.
 *
 * The series is fetched from the `manuspectrum:api-spectrum-preview` route, which
 * answers at most a couple of hundred points, already reduced to the curve the XY
 * reader draws, and `204` for a file it cannot plot.
 *
 * Init-only and without a single subscription: a popup is destroyed and rebuilt
 * on every click, and the value it hands over never changes under one element.
 * The drawing is assembled with `createElementNS` — the payload is built from a
 * file a curator uploaded, and nothing in it is ever parsed as markup.
 */

import ko from 'knockout';
import { generateArchesURL } from '@/arches/utils/generate-arches-url.ts';

const SVG_NS = 'http://www.w3.org/2000/svg';

/** The drawing box, in user units; CSS gives the element its real size. */
const WIDTH = 100;
const HEIGHT = 32;

/** Two decimals of a user unit, well under a device pixel at any size. */
const round = (value) => Math.round(value * 100) / 100;

/**
 * The finite points of a preview payload, or `null` when it draws nothing.
 *
 * A single point has no line to draw, and a series whose x are all equal has
 * no horizontal extent to normalise against. A flat y is fine: it is drawn
 * along the middle of the box. `x_reversed` mirrors the axis, as the XY reader
 * does for the techniques whose wavenumbers run the other way.
 */
function series(payload) {
    if (!payload || !Array.isArray(payload.x) || !Array.isArray(payload.y)) {
        return null;
    }
    const points = [];
    const length = Math.min(payload.x.length, payload.y.length);
    for (let index = 0; index < length; index += 1) {
        const x = payload.x[index];
        const y = payload.y[index];
        if (Number.isFinite(x) && Number.isFinite(y)) {
            points.push([x, y]);
        }
    }
    if (points.length < 2) {
        return null;
    }
    const xs = points.map((point) => point[0]);
    const ys = points.map((point) => point[1]);
    const xmin = Math.min.apply(null, xs);
    const xmax = Math.max.apply(null, xs);
    if (xmax === xmin) {
        return null;
    }
    const ymin = Math.min.apply(null, ys);
    const ymax = Math.max.apply(null, ys);
    const height = ymax - ymin;
    const width = xmax - xmin;
    const reversed = Boolean(payload.x_reversed);
    return points
        .map(
            (point) =>
                round(
                    ((reversed ? xmax - point[0] : point[0] - xmin) / width) * WIDTH
                ) +
                ',' +
                round(
                    height
                        ? HEIGHT - ((point[1] - ymin) / height) * HEIGHT
                        : HEIGHT / 2
                )
        )
        .join(' ');
}

/** The sparkline of `points`, labelled `title` for a screen reader. */
function drawing(points, title) {
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${WIDTH} ${HEIGHT}`);
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('role', 'img');

    const label = document.createElementNS(SVG_NS, 'title');
    label.textContent = title;
    svg.appendChild(label);

    const polyline = document.createElementNS(SVG_NS, 'polyline');
    polyline.setAttribute('fill', 'none');
    polyline.setAttribute('stroke', 'currentColor');
    polyline.setAttribute('stroke-width', '1');
    polyline.setAttribute('vector-effect', 'non-scaling-stroke');
    polyline.setAttribute('points', points);
    svg.appendChild(polyline);

    return svg;
}

ko.bindingHandlers.msSpark = {
    init: function (element, valueAccessor) {
        const spark = ko.unwrap(valueAccessor()) || {};
        const controller = new AbortController();
        ko.utils.domNodeDisposal.addDisposeCallback(element, () => controller.abort());

        if (!spark.fileId) {
            element.hidden = true;
            return;
        }

        const hide = () => {
            if (!controller.signal.aborted) {
                element.hidden = true;
            }
        };

        const url = generateArchesURL('manuspectrum:api-spectrum-preview', {
            file_id: encodeURIComponent(spark.fileId),
        });

        fetch(url, {
            credentials: 'same-origin',
            headers: { Accept: 'application/json' },
            signal: controller.signal,
        })
            .then((response) => (response.status === 200 ? response.json() : null))
            .then((payload) => {
                if (controller.signal.aborted) {
                    return;
                }
                const points = series(payload);
                if (points) {
                    element.appendChild(drawing(points, spark.title || ''));
                } else {
                    element.hidden = true;
                }
            })
            .catch(hide);
    },
};

export default ko.bindingHandlers.msSpark;
