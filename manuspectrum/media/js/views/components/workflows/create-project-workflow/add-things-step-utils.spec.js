/**
 * Vitest unit spec — add-things-step-utils.js.
 *
 * `renderTermResult` feeds selectWoo's `templateResult`: a string is escaped by
 * selectWoo, a jQuery element is appended as-is. Labels come from the search
 * API, so the free-text row must be built as nodes, never as markup.
 *
 * Note: this file lives under media/js/views/components/, which coverage.include
 * does not target, so it executes without touching the coverage gate.
 */

import { describe, expect, it } from 'vitest';
import $ from 'jquery';

import { renderTermResult } from './add-things-step-utils.js';

const HOSTILE = '<img src=x onerror="alert(1)">';

describe('renderTermResult', () => {
    it('renders the free-text row as nodes with the label as text', () => {
        const result = renderTermResult({ context_label: 'Search Term', text: HOSTILE });

        expect(result).toBeInstanceOf($);
        expect(result.is('strong')).toBe(true);
        expect(result.find('u').length).toBe(1);
        expect(result.find('img').length).toBe(0);
        expect(result.text()).toBe(HOSTILE);
        expect(result.prop('outerHTML')).toContain('&lt;img');
    });

    it('returns the plain label for any other row so selectWoo escapes it', () => {
        const result = renderTermResult({ context_label: 'Document', text: HOSTILE });

        expect(typeof result).toBe('string');
        expect(result).toBe(HOSTILE);
    });

    it('tolerates a missing label', () => {
        const result = renderTermResult({ context_label: 'Search Term' });

        expect(result.text()).toBe('');
    });
});
