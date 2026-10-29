import ko from "knockout";
import arches from "arches";
import imagingLayersProposalTemplate from "templates/views/components/functions/imaging-layers-proposal.htm";

/**
 * Configuration panel for the "Imaging layers proposal" function.
 *
 * The function has nothing to tune: the label -> layer rule lives in
 * `manuspectrum/utils/imaging_layers.py` and its triggering nodegroup is fixed
 * by the Analysis graph. Arches requires a component for every function; the
 * panel states what the function does and does not do to existing data.
 */
const viewModel = function (params) {
    const self = this;

    this.config = params.config;

    this.triggeringNodegroups = ko.computed(function () {
        const nodegroups = self.config && self.config.triggering_nodegroups;
        return ko.unwrap(nodegroups) || [];
    });

    this.translations = arches.translations;
};

ko.components.register("views/components/functions/imaging-layers-proposal", {
    viewModel: viewModel,
    template: imagingLayersProposalTemplate,
});

export default viewModel;
