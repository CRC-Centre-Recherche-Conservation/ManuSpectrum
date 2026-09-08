/**
 * Vitest unit spec — xy-parser.js generated abscissa.
 *
 * A file carrying intensities only has no X column, so the parser makes one
 * from the row position. What that position means is a claim the file has to
 * back: it is the Nth row, never the detector's channel N.
 */

import { describe, it, expect } from 'vitest';

import XyParser from './xy-parser';

const intensitiesOnly = ['12', '18', '25', '19', '11'].join('\n');

describe('the generated abscissa', () => {
    const parse = () =>
        XyParser.parse(intensitiesOnly, {
            xColumnMode: 'generate',
            headerFixedLines: 0,
        });

    it('numbers the rows from one, as every other way of counting them does', () => {
        // It was zero-based while the panel's help promised "1, 2, 3 …", so a
        // reader picking out the 722nd point landed on row 723 of the file.
        expect(parse().x).toEqual([1, 2, 3, 4, 5]);
    });

    it('keeps one abscissa per row', () => {
        const parsed = parse();
        const y = parsed.y || parsed.ys[0];

        expect(parsed.x).toHaveLength(y.length);
    });
});
