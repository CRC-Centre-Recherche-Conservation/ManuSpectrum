/**
 * Shadow of arches/app/media/js/bindings/dropzone.js (Arches 8.1.4).
 *
 * Diff vs original:
 *   - registers a node-disposal callback that calls `destroy()` on the
 *     Dropzone instance attached to the element (`element.dropzone`), which
 *     also removes it from the static `Dropzone.instances` registry
 *   - `import dropzone from 'dropzone'` -> side-effect import (the module is
 *     only needed for its jQuery plugin registration)
 */

import ko from 'knockout';
import _ from 'underscore';
import $ from 'jquery';
import 'dropzone';


/**
 * @constructor
 * @name dropzone
 */
ko.bindingHandlers.dropzone = {
    init: function(element, valueAccessor, allBindings, viewModel, bindingContext) {
        var innerBindingContext = bindingContext.extend(valueAccessor);
        ko.applyBindingsToDescendants(innerBindingContext, element);

        var options = valueAccessor() || {};

        _.each(_.filter(options, function(value, key) {
            return _.contains(['previewsContainer', 'clickable'], key);
        }),function(value, key) {
            options[key] = $(element).find(value)[0];
        });

        $(element).dropzone(options);

        ko.utils.domNodeDisposal.addDisposeCallback(element, function() {
            var instance = element.dropzone;
            if (instance && typeof instance.destroy === 'function') {
                instance.destroy();
            }
        });
        return { controlsDescendantBindings: true };
    }
};
ko.bindingHandlers.dropzone.init = ko.bindingHandlers.dropzone.init.bind(ko.bindingHandlers.dropzone);

export default ko.bindingHandlers.dropzone;

