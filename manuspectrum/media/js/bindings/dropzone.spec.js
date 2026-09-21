/**
 * Vitest unit spec — bindings/dropzone.js teardown.
 *
 * Dropzone keeps every instance in the static `Dropzone.instances` until
 * `destroy()` runs, so the binding destroys the instance attached to its
 * element when Knockout disposes the node.
 *
 * Note: this file lives under media/js/bindings/, which coverage.include does
 * not target, so it executes without touching the coverage gate.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import $ from 'jquery';
import ko from 'knockout';

vi.mock('dropzone', () => ({ default: {} }));

import './dropzone.js';

const mount = (options = {}) => {
    const root = document.createElement('div');
    root.innerHTML = '<div class="dz" data-bind="dropzone: options"></div>';
    document.body.appendChild(root);
    ko.applyBindings({ options }, root);
    return root;
};

describe('bindings/dropzone', () => {
    let instance;

    beforeEach(() => {
        instance = { destroy: vi.fn(), files: [], cancelUpload: vi.fn() };
        $.fn.dropzone = vi.fn(function() {
            this.each((_, element) => {
                element.dropzone = instance;
            });
            return this;
        });
    });

    afterEach(() => {
        delete $.fn.dropzone;
        document.body.innerHTML = '';
    });

    it('initialises Dropzone on the element through the jQuery plugin', () => {
        const root = mount();

        expect($.fn.dropzone).toHaveBeenCalledTimes(1);
        expect(root.querySelector('.dz').dropzone).toBe(instance);
    });

    it('destroys the instance when Knockout disposes the node', () => {
        const root = mount();

        ko.removeNode(root);

        expect(instance.destroy).toHaveBeenCalledTimes(1);
    });

    it('tolerates an element the plugin never attached to', () => {
        $.fn.dropzone = vi.fn(function() { return this; });
        const root = mount();

        expect(() => ko.removeNode(root)).not.toThrow();
    });

    it('destroys without emitting removedfile for staged files', () => {
        const staged = { status: 'added' };
        const removedfile = vi.fn();
        instance.files = [staged];
        instance.cancelUpload = vi.fn();
        instance.destroy = vi.fn(function() {
            // Dropzone 5.7.0 destroy() -> removeAllFiles(true) -> one removedfile per remaining file
            this.files.forEach(() => removedfile());
        });
        const root = mount();

        ko.removeNode(root);

        expect(instance.cancelUpload).toHaveBeenCalledWith(staged);
        expect(removedfile).not.toHaveBeenCalled();
        expect(instance.destroy).toHaveBeenCalledTimes(1);
    });
});
