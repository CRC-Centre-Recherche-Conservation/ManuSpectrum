import ko from 'knockout';
import arches from 'arches';
import xyTechniqueConfigTemplate from 'templates/views/components/functions/xy-technique-config.htm';

/**
 * Configuration panel for the "XY Technique Configuration" function.
 *
 * The function has nothing to tune: the technique -> preset table lives in
 * `manuspectrum/constants/xy_presets.py`, and its triggering nodegroups are
 * fixed by the Analysis graph. The panel exists because Arches requires a
 * component for every function, and it is the natural place to tell a curator
 * what the function will and will not do to their data.
 */
const viewModel = function (params) {
    const self = this;

    this.config = params.config;

    // Surfaced read-only so an administrator can confirm the function is bound
    // to the nodegroups they expect without opening the source.
    this.triggeringNodegroups = ko.computed(function () {
        const nodegroups = self.config && self.config.triggering_nodegroups;
        return ko.unwrap(nodegroups) || [];
    });

    this.translations = arches.translations;
};

ko.components.register('views/components/functions/xy-technique-config', {
    viewModel: viewModel,
    template: xyTechniqueConfigTemplate,
});

export default viewModel;
