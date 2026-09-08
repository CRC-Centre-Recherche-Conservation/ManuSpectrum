// Arches for Science
// GPL-3.0 license
// https://github.com/archesproject/arches-for-science

import ko from 'knockout';
import resourceInstanceSelectWidgetTemplate from 'templates/views/components/resource-instance-creator.htm';
import ResourceInstanceSelectViewModel from 'viewmodels/resource-instance-select';
import 'bindings/select2-query';

const viewModel = function(params) {
    params.value = params.value || ko.observable();
    params.allowInstanceCreation = true;
    params.renderContext = 'workflow';
    params.datatype = 'resource-instance';
    params.disabled = params.disabled || ko.observable(false);
    ResourceInstanceSelectViewModel.apply(this, [params]);

    this.newResource = function() {
        this.select2Config.onSelect({
            _id: params.graphids[0]
        });
    };
};

ko.components.register('resource-instance-creator', {
    viewModel: viewModel,
    template: resourceInstanceSelectWidgetTemplate,
});

export default viewModel;
